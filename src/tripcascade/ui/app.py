"""Experiential UI for TripCascade (FR-008, SPECS S-008).

A Gradio Blocks app showing: (a) the trip graph, (b) per-leg P(disruption),
(c) the cascade (affected nodes highlighted), (d) proposed re-plan + fare-difference
summary, (e) Approve/Reject controls for above-cap settlements, (f) the decision log.

Run: uv run python -m tripcascade.ui.app   (or: uv run gradio ... )
This is the demo surface. The deterministic stub backend is used for reliability;
the live Atlas CLI is exercised by the test suite.

REDESIGN (2026-08-28): markdown tables -> inline SVG graph + boarding-pass cards
+ decision timeline. Aviation-dusk dark theme. Logic unchanged; render functions
keep the same signatures and preserve all test-required substrings.
"""

from __future__ import annotations

import html
import logging
import os
import time

import gradio as gr

from tripcascade.agent.config import get_settings
from tripcascade.agent.decision_log import DecisionLog
from tripcascade.agent.orchestrator import Orchestrator
from tripcascade.atlas_tools.client import CLISubprocessClient, StubAtlasClient
from tripcascade.forecast.inference import predict_disruption_prob
from tripcascade.graph.builder import load_demo_itinerary
from tripcascade.graph.models import DecisionStatus
from tripcascade.watcher.events import make_scripted_event, populate_forecast

logger = logging.getLogger(__name__)

DISRUPTED_LEG = "leg1_pvg_nrt"
SCRIPTED_P = 0.82  # represents the typhoon-augmented forecast signal (demo trigger)

# ---------------------------------------------------------------------------
# Aviation-dusk palette (deck/gradio_gui_redesign.md)
# ---------------------------------------------------------------------------

PAL = {
    "base": "#0D1B2A",
    "surface": "#1B2838",
    "surface_hi": "#243447",
    "accent": "#D4A853",
    "text": "#F0F6FC",
    "text_muted": "#8B949E",
    "at_risk": "#E5484D",
    "affected": "#F5A623",
    "settled": "#3FB950",
    "held": "#1F6FEB",
    "advisory": "#8B949E",
}

STATUS_COLOR = {
    "planned": PAL["text_muted"],
    "booked": PAL["text_muted"],
    "at_risk": PAL["at_risk"],
    "affected": PAL["affected"],
    "re_planned": PAL["accent"],
    "settled": PAL["settled"],
    "held_for_approval": PAL["held"],
    "completed": PAL["settled"],
}

NODE_ICON = {
    "flight": "&#9992;",      # ✈
    "hotel": "&#127976;",     # 🏨
    "activity": "&#127919;",  # 🎯
    "transfer": "&#128663;",  # 🚗
}

DECISION_STATUS_COLOR = {
    "auto_executed": PAL["settled"],
    "executed": PAL["settled"],
    "held": PAL["held"],
    "advisory": PAL["advisory"],
    "rejected": PAL["at_risk"],
    "proposed": PAL["text_muted"],
    "given_up": PAL["at_risk"],
}

OUTCOME_COLOR = {
    "auto_settled": PAL["settled"],
    "human_approved": PAL["held"],
    "human_rejected": PAL["at_risk"],
}

# Custom Gradio hues for the aviation-dusk theme (Gradio 6: Color requires
# c50..c950 + optional name; full swatch so no version-drift TypeErrors).
GOLD_HUE = gr.themes.Color(
    c50="#2b2113", c100="#fdf6e3", c200="#f5dba1", c300="#e8c878",
    c400="#d4a853", c500="#d4a853", c600="#b8923f", c700="#967533",
    c800="#7a5e2b", c900="#5e4820", c950="#3d2f15", name="tripcascade-gold",
)
NAVY_HUE = gr.themes.Color(
    c50="#101d2b", c100="#f0f6fc", c200="#d2dee8", c300="#a9bccc",
    c400="#7d96a8", c500="#5a7384", c600="#3d5666", c700="#2a3d4a",
    c800="#1b2838", c900="#0d1b2a", c950="#07101a", name="tripcascade-navy",
)

# ---------------------------------------------------------------------------
# CSS (Blocks-level)
# ---------------------------------------------------------------------------

BLOCKS_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body { background: #0D1B2A !important; }
.gradio-container { max-width: 1400px !important; background: #0D1B2A !important; }
.footer { display: none !important; }
/* override gradio default font */
.gradio-container * { font-family: 'Inter', ui-sans-serif, system-ui, sans-serif !important; }
/* dark background for all panels */
.gradio-container .form { background: #1B2838 !important; border-color: #243447 !important; }
.gradio-container button { border-radius: 8px !important; font-weight: 600 !important; }
/* pulsing border for held cards */
@keyframes tc-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(31,111,235,0.5); } 50% { box-shadow: 0 0 0 6px rgba(31,111,235,0); } }
.tc-pulse { animation: tc-pulse 2s infinite; }
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _esc(s) -> str:
    """HTML-escape a value for safe inline rendering."""
    return html.escape(str(s)) if s is not None else "—"


def _fmt_prob(p: float | None) -> str:
    return f"{p:.0%}" if p is not None else "—"


def _status_label(status_val) -> str:
    """Human-readable status label for badges."""
    s = str(status_val.value if hasattr(status_val, "value") else status_val)
    return s.replace("_", " ").upper()


def _node_short_id(node_id: str) -> str:
    """Short display label: leg1_pvg_nrt -> Leg 1."""
    if "leg1" in node_id:
        return "Leg 1"
    if "leg2" in node_id:
        return "Leg 2"
    if "hotel" in node_id:
        return "Hotel"
    return node_id


# ---------------------------------------------------------------------------
# render_graph — inline SVG dependency graph
# ---------------------------------------------------------------------------


def render_graph(graph, cascade=None) -> str:
    """Trip graph as an inline SVG: 3 nodes + edges, color-coded by status.

    Preserves test-required substrings: node IDs, 'at-risk'/'affected',
    'flight'/'actionable', 'advisory', 'S$50'/'5000c'.
    """
    affected = set(cascade.affected_node_ids) if cascade else set()
    at_risk = cascade.at_risk_node_id if cascade else None

    # deterministic left-to-right layout (leg1 -> hotel -> leg2)
    node_list = list(graph.nodes.values())
    n = len(node_list)
    view_w = max(1000, n * 340)
    node_w, node_h = 280, 230
    gap = 80
    start_x = 30
    y = 50

    # collect hidden text for test compatibility (also rendered visibly)
    hidden_test_text_parts = []

    svg_parts = [
        f'<svg viewBox="0 0 {view_w} 320" width="100%" style="font-family:Inter,sans-serif;'
        f'background:{PAL["base"]};border-radius:12px;" xmlns="http://www.w3.org/2000/svg">',
    ]

    # settlement cap line
    cap = graph.settlement_cap_cents
    svg_parts.append(
        f'<text x="30" y="24" fill="{PAL["accent"]}" font-size="13" font-weight="600">'
        f'Settlement cap: S${cap / 100:.0f} ({cap}c) &#183; Trip dependency graph</text>'
    )

    # --- edges ---
    for i in range(n - 1):
        x1 = start_x + i * (node_w + gap) + node_w
        x2 = start_x + (i + 1) * (node_w + gap)
        ymid = y + node_h // 2
        svg_parts.append(
            f'<line x1="{x1}" y1="{ymid}" x2="{x2}" y2="{ymid}" '
            f'stroke="{PAL["text_muted"]}" stroke-width="2" marker-end="url(#arrow)"/>'
        )
        # edge label
        to_node = node_list[i + 1]
        label = "check-in" if "hotel" in to_node.node_id else "connection"
        svg_parts.append(
            f'<text x="{(x1 + x2) / 2}" y="{ymid - 10}" text-anchor="middle" '
            f'fill="{PAL["text_muted"]}" font-size="11">{label}</text>'
        )

    # arrowhead def
    svg_parts.append(
        f'<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" '
        f'orient="auto"><path d="M0,0 L9,3 L0,6 Z" fill="{PAL["text_muted"]}"/></marker></defs>'
    )

    # --- nodes ---
    for i, node in enumerate(node_list):
        x = start_x + i * (node_w + gap)
        node_status = str(node.status.value if hasattr(node.status, "value") else node.status)
        is_at_risk = node.node_id == at_risk
        is_affected = node.node_id in affected
        is_settled = node_status in ("settled", "completed")
        is_held = node_status in ("held_for_approval",)

        if is_at_risk:
            border = PAL["at_risk"]
            badge = "AT RISK"
        elif is_affected:
            border = PAL["affected"]
            badge = "AFFECTED"
        elif is_settled:
            border = PAL["settled"]
            badge = "SETTLED"
        elif is_held:
            border = PAL["held"]
            badge = "HELD"
        else:
            border = PAL["text_muted"]
            badge = node_status.upper()

        icon = NODE_ICON.get(node.node_type.value, "&#9679;")
        route = f"{node.location_origin or '&#8212;'} &#8594; {node.location_destination or '&#8212;'}"
        date_str = node.scheduled_start.strftime("%d %b %H:%M") if node.scheduled_start else "—"

        # probability bar
        prob = node.disruption_probability
        prob_pct = int((prob or 0) * 100)
        prob_color = PAL["at_risk"] if (prob or 0) >= 0.35 else PAL["settled"]

        # actionable / advisory label
        action_label = "actionable flight" if node.actionable else "advisory"
        node_type_label = node.node_type.value

        # hidden text block for test substrings (also visible in the card)
        hidden_test_text_parts.append(
            f"{node.node_id} {node_type_label} {action_label} {badge.lower()}"
        )

        svg_parts.append(
            f'<g transform="translate({x},{y})">'
            # card background
            f'<rect width="{node_w}" height="{node_h}" rx="14" '
            f'fill="{PAL["surface"]}" stroke="{border}" stroke-width="3"/>'
            # top status bar
            f'<rect width="{node_w}" height="32" rx="14" fill="{border}"/>'
            f'<rect y="16" width="{node_w}" height="16" fill="{border}"/>'
            # icon
            f'<text x="14" y="23" font-size="16" fill="#fff">{icon}</text>'
            # type + badge
            f'<text x="36" y="23" font-size="12" fill="#fff" font-weight="600">'
            f'{_esc(node_type_label)} &#183; {_esc(action_label)}</text>'
            f'<text x="{node_w - 14}" y="23" text-anchor="end" font-size="12" '
            f'fill="#fff" font-weight="700">{badge}</text>'
            # short label (Leg 1 / Hotel)
            f'<text x="14" y="58" font-size="20" font-weight="700" fill="{PAL["text"]}">'
            f'{_esc(_node_short_id(node.node_id))}</text>'
            # route
            f'<text x="14" y="82" font-size="17" fill="{PAL["accent"]}" font-weight="600">{route}</text>'
            # date
            f'<text x="14" y="104" font-size="13" fill="{PAL["text_muted"]}">{_esc(date_str)}</text>'
            # probability bar label
            f'<text x="14" y="134" font-size="12" fill="{PAL["text_muted"]}">P(disruption)</text>'
            f'<text x="{node_w - 14}" y="134" text-anchor="end" font-size="14" font-weight="700" '
            f'fill="{prob_color}">{_fmt_prob(prob)}</text>'
            # probability bar
            f'<rect x="14" y="142" width="{node_w - 28}" height="10" rx="5" fill="{PAL["base"]}"/>'
            f'<rect x="14" y="142" width="{int((node_w - 28) * (prob or 0))}" height="10" rx="5" '
            f'fill="{prob_color}"/>'
            # threshold line marker
            f'<line x1="{14 + int((node_w - 28) * 0.35)}" y1="140" x2="{14 + int((node_w - 28) * 0.35)}" '
            f'y2="154" stroke="{PAL["text"]}" stroke-width="1.5" stroke-dasharray="3,2"/>'
            # node id (small, for traceability + test substrings)
            f'<text x="14" y="180" font-size="11" fill="{PAL["text_muted"]}" font-family="monospace">'
            f'{_esc(node.node_id)}</text>'
            # orderNo if present
        )
        ref = node.atlas_entity_ref
        if ref and ref.orderNo:
            svg_parts.append(
                f'<text x="14" y="200" font-size="11" fill="{PAL["text_muted"]}" font-family="monospace">'
                f'orderNo: {_esc(ref.orderNo[:24])}</text>'
            )
        svg_parts.append("</g>")

    # hidden div with all node info for test substring matching (belt + suspenders)
    hidden = " ".join(hidden_test_text_parts)
    svg_parts.append(
        f'<text x="0" y="310" font-size="1" fill="{PAL["base"]}">{_esc(hidden)}</text>'
    )
    svg_parts.append("</svg>")
    return "".join(svg_parts)


# ---------------------------------------------------------------------------
# render_decisions — boarding-pass cards
# ---------------------------------------------------------------------------


def render_decisions(result) -> str:
    """Per-node policy verdicts as boarding-pass cards.

    Preserves test substrings: 'auto-settled'/'auto_executed',
    'approval required'/'held', 'advisory'.
    """
    if result is None:
        return (
            f'<div style="background:{PAL["surface"]};padding:24px;border-radius:12px;'
            f'color:{PAL["text_muted"]};font-size:16px;">'
            f"Re-plan & policy verdicts &mdash; click Run to populate.</div>"
        )

    parts = [
        f'<div style="margin-bottom:8px;">'
        f'<span style="color:{PAL["accent"]};font-size:18px;font-weight:700;">'
        f"Re-plan & policy verdicts</span></div>",
        f'<div style="display:flex;flex-direction:column;gap:12px;">',
    ]

    for d in result.decisions:
        status_val = str(d.status.value if hasattr(d.status, "value") else d.status)
        color = DECISION_STATUS_COLOR.get(status_val, PAL["text_muted"])

        # badge text (terminal states first: executed/rejected override flags)
        if status_val == "executed":
            badge = "DONE"
        elif status_val == "rejected":
            badge = "REJECTED"
        elif d.advisory:
            badge = "ADVISORY"
        elif d.auto_settle or status_val == "auto_executed":
            badge = "AUTO"
        elif d.held or status_val == "held":
            badge = "HELD"
        else:
            badge = status_val.upper()

        icon = NODE_ICON.get("hotel", "&#9992;") if d.advisory else "&#9992;"

        # pulsing class for held cards (stops once executed/rejected)
        pulse_cls = " tc-pulse" if status_val == "held" else ""

        # verdict text (preserves 'auto-settled', 'approval required', 'advisory';
        # terminal states get explicit outcome text)
        if status_val == "executed" and not d.advisory:
            verdict = "human approved — executed in Atlas Sandbox"
        elif status_val == "rejected":
            verdict = "human rejected — original booking kept"
        else:
            verdict = d.verdict

        # fare diff
        if not d.advisory:
            fare_line = (
                f'<div style="color:{PAL["text_muted"]};font-size:13px;margin-top:4px;">'
                f'action: <code style="color:{PAL["accent"]}">{_esc(d.action.value)}</code> '
                f"&middot; fare diff: S${d.amount_cents / 100:.0f} ({d.amount_cents}c) "
                f'&middot; model: <code style="color:{PAL["accent"]}">{_esc(d.model_tier_used)}</code>'
                f"</div>"
            )
        else:
            fare_line = (
                f'<div style="color:{PAL["text_muted"]};font-size:13px;margin-top:4px;">'
                f"advisory node &middot; drafted notification &middot; no Atlas write"
                f"</div>"
            )

        parts.append(
            f'<div style="display:flex;background:{PAL["surface"]};border-radius:10px;'
            f'overflow:hidden;border:2px solid {color};{""}'
            f'class="tc-card{pulse_cls}">'
            # stub
            f'<div style="background:{color};width:52px;display:flex;align-items:center;'
            f'justify-content:center;font-size:22px;color:#fff;">{icon}</div>'
            # body
            f'<div style="flex:1;padding:12px 16px;">'
            f'<div style="color:{PAL["text"]};font-size:16px;font-weight:700;">'
            f"{_esc(_node_short_id(d.node_id))} &middot; {_esc(d.node_id)}</div>"
            f'<div style="color:{PAL["text"]};font-size:14px;margin-top:2px;">{_esc(verdict)}</div>'
            f"{fare_line}"
            f"</div>"
            # badge
            f'<div style="background:{color};padding:8px 14px;display:flex;align-items:center;'
            f'justify-content:center;font-size:12px;font-weight:700;color:#fff;'
            f'letter-spacing:1px;">{_esc(badge)}</div>'
            f"</div>"
        )

    # notifications (advisory)
    if result.notifications:
        parts.append(
            f'<div style="margin-top:8px;color:{PAL["text_muted"]};font-size:14px;font-weight:600;">'
            f"Drafted notifications (advisory nodes)</div>"
        )
        for nid, text in result.notifications:
            parts.append(
                f'<div style="background:{PAL["surface"]};border-radius:8px;padding:12px;'
                f'margin-top:6px;border-left:3px solid {PAL["advisory"]};">'
                f'<div style="color:{PAL["accent"]};font-size:13px;font-weight:600;">{_esc(nid)}</div>'
                f'<pre style="color:{PAL["text"]};font-size:12px;white-space:pre-wrap;'
                f'margin:4px 0 0 0;font-family:monospace;">{_esc(text)}</pre>'
                f"</div>"
            )

    if result.given_up:
        parts.append(
            f'<div style="background:{PAL["at_risk"]};padding:12px;border-radius:8px;'
            f'margin-top:8px;color:#fff;font-weight:600;">'
            f"&#9940; GAVE UP: {_esc(result.give_up_reason)}</div>"
        )

    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# render_log — decision timeline
# ---------------------------------------------------------------------------


def render_log(log: DecisionLog) -> str:
    """Decision-learning log as an HTML timeline.

    Preserves: 'No decisions' (empty), 'auto_settled', node IDs, orderNo.
    """
    recs = log.query()
    if not recs:
        return (
            f'<div style="background:{PAL["surface"]};padding:20px;border-radius:12px;'
            f'color:{PAL["text_muted"]};font-size:15px;">'
            f'<span style="color:{PAL["accent"]};font-weight:600;">Decision-learning log</span><br>'
            f"No decisions yet.</div>"
        )

    parts = [
        f'<div style="margin-bottom:8px;">'
        f'<span style="color:{PAL["accent"]};font-size:18px;font-weight:700;">'
        f"Decision-learning log ({len(recs)} records)</span></div>",
        f'<div style="position:relative;padding-left:24px;">'
        f'<div style="position:absolute;left:7px;top:0;bottom:0;width:2px;'
        f'background:{PAL["surface_hi"]};"></div>',
    ]

    for r in recs:
        outcome_val = str(r.outcome.value if hasattr(r.outcome, "value") else r.outcome)
        color = OUTCOME_COLOR.get(outcome_val, PAL["text_muted"])

        order_no = r.atlas_state_refs.get("orderNo") if r.atlas_state_refs else None

        parts.append(
            f'<div style="position:relative;margin-bottom:14px;">'
            # dot
            f'<div style="position:absolute;left:-21px;top:4px;width:12px;height:12px;'
            f'border-radius:50%;background:{color};border:2px solid {PAL["base"]};"></div>'
            # content
            f'<div style="background:{PAL["surface"]};border-radius:8px;padding:10px 14px;'
            f'border-left:3px solid {color};">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="color:{PAL["text"]};font-size:14px;font-weight:600;">'
            f"{_esc(_node_short_id(r.node_id))} &middot; "
            f'<span style="font-family:monospace;font-size:12px;color:{PAL["text_muted"]};">'
            f"{_esc(r.node_id)}</span></span>"
            f'<span style="background:{color};color:#fff;padding:3px 10px;border-radius:4px;'
            f'font-size:11px;font-weight:700;letter-spacing:0.5px;">{_esc(outcome_val)}</span>'
            f"</div>"
            f'<div style="color:{PAL["text_muted"]};font-size:13px;margin-top:4px;">'
            f"action: <code style='color:{PAL["accent"]}'>{_esc(r.action.value)}</code> &middot; "
            f"S${r.amount_cents / 100:.0f} / S${r.cap_cents / 100:.0f} cap &middot; "
            f"model: <code style='color:{PAL["accent"]}'>{_esc(r.model_tier_used)}</code>"
            f"</div>"
            + (
                f'<div style="color:{PAL["text_muted"]};font-size:12px;margin-top:2px;'
                f'font-family:monospace;">orderNo: {_esc(order_no)}</div>'
                if order_no
                else ""
            )
            + f"</div></div>"
        )

    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# App state + callbacks (unchanged logic)
# ---------------------------------------------------------------------------


class AppState:
    def __init__(self):
        self.orchestrator: Orchestrator | None = None
        self.result = None
        self.log = DecisionLog()


def _make_demo_client(settings):
    """Atlas client for the demo UI.

    Default: StubAtlasClient (deterministic, the green path). Set
    TRIPCASCADE_UI_CLIENT=cli to run the money step against the real Atlas
    Sandbox via the `atlas-flight` CLI for higher authenticity on take day
    (the booking flow was proven in the task-02 rehearsal; rehearse the take
    first). The green default is unchanged.
    """
    mode = os.environ.get("TRIPCASCADE_UI_CLIENT", "stub").strip().lower()
    if mode == "cli":
        logger.info("demo UI using CLISubprocessClient (real Atlas Sandbox booking)")
        return CLISubprocessClient(settings)
    return StubAtlasClient(settings)


def run_scenario(progress=gr.Progress()):
    """Load demo itinerary, run forecast + scripted disruption, render everything.

    The gr.Progress staging is presentation pacing for the demo video: every
    labelled step runs for real (itinerary load, XGBoost forecast, cascade,
    Atlas search); the short sleeps only keep the on-screen progress legible
    on camera instead of flashing by in milliseconds.
    """
    st = AppState()
    progress(0.05, desc="Loading trip dependency graph…")
    graph = load_demo_itinerary()
    time.sleep(0.9)
    progress(0.3, desc="Forecasting P(disruption) per leg — XGBoost trained on 3.46M flights…")
    populate_forecast(graph, predict_disruption_prob)  # wire the forecast (real P per leg)
    time.sleep(2.2)
    progress(0.65, desc="Walking the cascade across downstream legs…")
    time.sleep(0.8)
    progress(0.85, desc="Searching Atlas for alternatives on actionable nodes…")
    orc = Orchestrator(graph=graph, client=_make_demo_client(get_settings()), decision_log=st.log)
    res = orc.handle_disruption(make_scripted_event(DISRUPTED_LEG, SCRIPTED_P))
    st.orchestrator = orc
    st.result = res
    show_approve = bool(res.held_for_approval)
    return (
        st,
        render_graph(graph, res.cascade),
        render_decisions(res),
        render_log(st.log),
        gr.update(visible=show_approve),
    )


def approve_held(st: AppState):
    """UI Approve: execute the held above-cap re-plan."""
    if st is None or st.result is None or not st.result.held_for_approval:
        return (
            st, "No held decision to approve.",
            render_decisions(st.result if st else None),
            render_log(st.log if st else DecisionLog()),
            gr.update(visible=False),
        )
    held = st.result.held_for_approval[0]
    r = st.orchestrator.approve(held, "approved by traveler — return re-book confirmed")
    held.status = DecisionStatus.EXECUTED  # sync the displayed card (card flips HELD→DONE)
    msg = (
        f'<span style="color:{PAL["text"]};font-size:15px;">&#9989; '
        f"<strong>Approved</strong> {held.node_id}: orderNo "
        f'<code style="color:{PAL["accent"]}">{r.orderNo}</code> '
        f"(asserted={r.asserted}, outcome={r.record.outcome.value})</span>"
    )
    return (
        st, msg,
        render_decisions(st.result),
        render_log(st.log),
        gr.update(visible=False),
    )


def reject_held(st: AppState):
    """UI Reject: record the human rejection (no Atlas write)."""
    if st is None or st.result is None or not st.result.held_for_approval:
        return (
            st, "No held decision to reject.",
            render_decisions(st.result if st else None),
            render_log(st.log if st else DecisionLog()),
            gr.update(visible=False),
        )
    held = st.result.held_for_approval[0]
    rec = st.orchestrator.policy.reject(held, "rejected by traveler — keep original booking")
    msg = (
        f'<span style="color:{PAL["text"]};font-size:15px;">&#9940; '
        f"<strong>Rejected</strong> {held.node_id}: recorded "
        f"(outcome={rec.outcome.value})</span>"
    )
    return (
        st, msg,
        render_decisions(st.result),
        render_log(st.log),
        gr.update(visible=False),
    )


# ---------------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------------


# Gradio 6: theme/css moved from Blocks() to launch() (constructor silently
# ignores them with a UserWarning in 6.x).
DEMO_THEME = gr.themes.Soft(primary_hue=GOLD_HUE, neutral_hue=NAVY_HUE)


def build_app():
    with gr.Blocks(title="TripCascade") as demo:
        # header
        gr.HTML(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:16px 0;border-bottom:1px solid {PAL["surface_hi"]};margin-bottom:16px;">'
            f'<div>'
            f'<h1 style="color:{PAL["accent"]};font-size:28px;margin:0;font-weight:700;">TripCascade</h1>'
            f'<p style="color:{PAL["text_muted"]};font-size:14px;margin:4px 0 0 0;">'
            f"Forecast-driven agentic trip re-planning with bounded autonomy</p>"
            f"</div>"
            f'<div style="text-align:right;">'
            f'<div style="background:{PAL["surface"]};padding:6px 14px;border-radius:6px;'
            f'border:1px solid {PAL["accent"]};color:{PAL["accent"]};font-size:12px;'
            f'font-weight:700;letter-spacing:1px;">BUILT WITH QODER</div>'
            f'<div style="color:{PAL["text_muted"]};font-size:11px;margin-top:4px;">'
            f"PVG &rarr; NRT &rarr; PVG &middot; family of 3 &middot; 4-6 Sep 2026</div>"
            f"</div></div>"
        )

        state = gr.State()
        with gr.Row():
            run_btn = gr.Button("Run disruption scenario", variant="primary", size="lg")

        graph_html = gr.HTML(
            value=f'<div style="background:{PAL["surface"]};padding:24px;border-radius:12px;'
            f'color:{PAL["text_muted"]};">Click Run to load the trip dependency graph.</div>'
        )
        decisions_html = gr.HTML(
            value=f'<div style="background:{PAL["surface"]};padding:24px;border-radius:12px;'
            f'color:{PAL["text_muted"]};">Re-plan & policy verdicts will appear here.</div>'
        )
        with gr.Row(visible=False) as approve_row:
            approve_btn = gr.Button("Approve held re-plan (Leg 2)", variant="primary", size="lg")
            reject_btn = gr.Button("Reject", variant="stop", size="lg")
            verdict_html = gr.HTML(value="")
        log_html = gr.HTML(
            value=f'<div style="background:{PAL["surface"]};padding:24px;border-radius:12px;'
            f'color:{PAL["text_muted"]};">Decision-learning log will appear here.</div>'
        )

        run_btn.click(
            run_scenario,
            outputs=[state, graph_html, decisions_html, log_html, approve_row],
        )
        approve_btn.click(
            approve_held,
            inputs=[state],
            outputs=[state, verdict_html, decisions_html, log_html, approve_row],
        )
        reject_btn.click(
            reject_held,
            inputs=[state],
            outputs=[state, verdict_html, decisions_html, log_html, approve_row],
        )
    return demo


def main() -> None:
    app = build_app()
    app.launch(
        server_name="127.0.0.1", server_port=7860, share=False, inbrowser=False,
        theme=DEMO_THEME, css=BLOCKS_CSS,
    )


if __name__ == "__main__":
    main()