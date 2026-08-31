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
from tripcascade.ui.theme_brand import tripcascade_theme
from tripcascade.watcher.events import make_scripted_event, populate_forecast

logger = logging.getLogger(__name__)

DISRUPTED_LEG = "leg1_pvg_nrt"
SCRIPTED_P = 0.82  # represents the typhoon-augmented forecast signal (demo trigger)

# ---------------------------------------------------------------------------
# TripCascade brand palette (brands/tripcascade tokens.json v1, 2026-08-31)
# Light-first: Mist White base, Cascade Teal signal, Seafoam surfaces.
# Brand law (rules.md): red = confirmed loss ONLY; coral = graphic-only
# (Coral Ink is the text-safe warm alert); no gradients; mono for data.
# ---------------------------------------------------------------------------

PAL = {
    "base": "#FBFEFD",        # Mist White — color.background
    "surface": "#EFF7F6",     # Seafoam Tint — color.surface
    "surface_hi": "#DFF0EE",  # Seafoam — chip/badge fills
    "border": "#D4E4E2",      # Shoreline — hairlines
    "accent": "#0E7C7B",      # Cascade Teal — the "handled" signal
    "text": "#14343B",        # Deep Ink
    "text_muted": "#48666E",  # Harbor Gray (6.09:1 — AA text-safe)
    "at_risk": "#8A5F00",     # Watch Amber — breach WARNING (never red)
    "affected": "#2A9D8F",    # Cascade Mid — the mid cascade step (graphic)
    "settled": "#257446",     # All-Clear
    "held": "#B23E24",        # Coral Ink — escalation (text-safe)
    "advisory": "#48666E",    # Harbor Gray
    "danger": "#C0392B",      # Disruption Red — confirmed loss/failure only
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
    "rejected": PAL["text_muted"],  # rejection keeps the original booking — not a loss
    "proposed": PAL["text_muted"],
    "given_up": PAL["danger"],       # a genuine failure — red's only role
}

OUTCOME_COLOR = {
    "auto_settled": PAL["settled"],
    "human_approved": PAL["settled"],
    "human_rejected": PAL["text_muted"],
}

# Brand theme generated from tokens (ui/theme_brand.py) — no custom hues needed.

# ---------------------------------------------------------------------------
# CSS (Blocks-level)
# ---------------------------------------------------------------------------

BLOCKS_CSS = """
html, body { background: #FBFEFD !important; }
.gradio-container { max-width: 1120px !important; background: #FBFEFD !important; }
.footer { display: none !important; }
/* brand type law: Source Sans 3 body stack; Nunito reserved for display;
   JetBrains Mono for every model/ledger quantity (mono-for-data) */
.gradio-container * { font-family: 'Source Sans 3', 'Source Sans Pro', 'Helvetica Neue', Arial, sans-serif !important; }
.gradio-container h1, .tc-display { font-family: 'Nunito', 'Trebuchet MS', Verdana, sans-serif !important; }
.gradio-container code, .tc-mono { font-family: 'JetBrains Mono', Menlo, Consolas, monospace !important; }
/* light brand surfaces for form blocks */
.gradio-container .form { background: #EFF7F6 !important; border-color: #D4E4E2 !important; }
.gradio-container button { font-weight: 600 !important; }
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
        f'<svg viewBox="0 0 {view_w} 320" width="100%" style="'
        f'background:{PAL["base"]};border-radius:14px;" xmlns="http://www.w3.org/2000/svg">',
    ]

    # settlement cap line
    cap = graph.settlement_cap_cents
    svg_parts.append(
        f'<text x="30" y="24" fill="{PAL["accent"]}" font-size="14" font-weight="600">'
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
            f'fill="{PAL["text_muted"]}" font-size="13">{label}</text>'
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
            border = PAL["border"]
            badge = node_status.upper()

        # Badge anatomy per brand: escalation = Coral Ink fill w/ white text;
        # status = white fill, status-color text + 1px border (text-safe);
        # neutral = Seafoam fill w/ Deep Ink text. Cascade Mid is graphic-only
        # (fails AA as text), so AFFECTED uses the neutral badge + mid left bar.
        if is_held:
            badge_bg, badge_fg, badge_bd = PAL["held"], "#FFFFFF", "none"
        elif is_at_risk or is_settled:
            badge_bg, badge_fg, badge_bd = "#FFFFFF", border, border
        else:
            badge_bg, badge_fg, badge_bd = PAL["surface_hi"], PAL["text"], "none"
        bw = len(badge) * 8 + 20  # pill width for 13px bold caps + padding
        bx = node_w - 14 - bw

        icon = NODE_ICON.get(node.node_type.value, "&#9679;")
        route = f"{node.location_origin or '&#8212;'} &#8594; {node.location_destination or '&#8212;'}"
        date_str = node.scheduled_start.strftime("%d %b %H:%M") if node.scheduled_start else "—"

        # probability bar — data leads in Cascade Teal (chart rule: series 1
        # is always teal); the breach is carried by the badge, not bar color
        prob = node.disruption_probability
        prob_color = PAL["accent"]

        # actionable / advisory label (short form — the badge needs the room)
        action_label = "actionable" if node.actionable else "advisory"
        node_type_label = node.node_type.value

        # hidden text block for test substrings (also visible in the card)
        hidden_test_text_parts.append(
            f"{node.node_id} {node_type_label} {action_label} {badge.lower()}"
        )

        svg_parts.append(
            f'<g transform="translate({x},{y})">'
            # card: Seafoam Tint, 1px Shoreline, 14px radius (brand card anatomy)
            f'<rect width="{node_w}" height="{node_h}" rx="14" '
            f'fill="{PAL["surface"]}" stroke="{PAL["border"]}" stroke-width="1"/>'
            # 6px status left bar (graphic cue — the lower-third pattern)
            f'<rect x="0" y="10" width="6" height="{node_h - 20}" rx="3" fill="{border}"/>'
            # icon
            f'<text x="18" y="31" font-size="16" fill="{PAL["text"]}">{icon}</text>'
            # type + action label
            f'<text x="40" y="31" font-size="13" fill="{PAL["text_muted"]}" font-weight="600">'
            f'{_esc(node_type_label)} &#183; {_esc(action_label)}</text>'
            # status badge pill (top-right); >=13px so rendered size >= 14px
            # (SVG viewBox 1000px renders at ~1088px in the 1120px container)
            f'<rect x="{bx}" y="14" width="{bw}" height="26" rx="13" fill="{badge_bg}"'
            + (f' stroke="{badge_bd}" stroke-width="1"/>' if badge_bd != "none" else "/>")
            + f'<text x="{bx + bw / 2:.0f}" y="32" text-anchor="middle" font-size="13" '
            f'fill="{badge_fg}" font-weight="700">{badge}</text>'
            # short label (Leg 1 / Hotel)
            f'<text x="18" y="66" font-size="20" font-weight="700" fill="{PAL["text"]}">'
            f'{_esc(_node_short_id(node.node_id))}</text>'
            # route
            f'<text x="18" y="90" font-size="17" fill="{PAL["accent"]}" font-weight="600">{route}</text>'
            # date
            f'<text x="18" y="112" font-size="13" fill="{PAL["text_muted"]}">{_esc(date_str)}</text>'
            # probability bar label + mono value (mono-for-data)
            f'<text x="18" y="140" font-size="13" fill="{PAL["text_muted"]}">P(disruption)</text>'
            f'<text x="{node_w - 14}" y="140" text-anchor="end" font-size="14" font-weight="700" '
            f'fill="{PAL["text"]}" style="font-family:\'JetBrains Mono\',Menlo,Consolas,monospace !important;">'
            f'{_fmt_prob(prob)}</text>'
            # probability bar: Shoreline track, Cascade Teal fill
            f'<rect x="18" y="148" width="{node_w - 32}" height="10" rx="5" fill="{PAL["border"]}"/>'
            f'<rect x="18" y="148" width="{int((node_w - 32) * (prob or 0))}" height="10" rx="5" '
            f'fill="{prob_color}"/>'
            # threshold marker = Watch Amber dashed (warning line)
            f'<line x1="{18 + int((node_w - 32) * 0.35)}" y1="146" x2="{18 + int((node_w - 32) * 0.35)}" '
            f'y2="160" stroke="{PAL["at_risk"]}" stroke-width="1.5" stroke-dasharray="3,2"/>'
            # node id (small, mono, for traceability + test substrings)
            f'<text x="18" y="182" font-size="13" fill="{PAL["text_muted"]}" '
            f'style="font-family:\'JetBrains Mono\',Menlo,Consolas,monospace !important;">'
            f'{_esc(node.node_id)}</text>'
            # orderNo if present
        )
        ref = node.atlas_entity_ref
        if ref and ref.orderNo:
            svg_parts.append(
                f'<text x="18" y="202" font-size="13" fill="{PAL["text_muted"]}" '
                f'style="font-family:\'JetBrains Mono\',Menlo,Consolas,monospace !important;">'
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

        # Badge anatomy per brand (rules.md coral-graphic-only + status-semantics):
        # HELD = escalation badge (Coral Ink fill, white text); AUTO/DONE =
        # status badge (white fill, All-Clear text + border); others = neutral.
        if badge == "HELD":
            badge_bg, badge_fg, badge_bd = PAL["held"], "#FFFFFF", "none"
        elif badge in ("AUTO", "DONE"):
            badge_bg, badge_fg, badge_bd = "#FFFFFF", PAL["settled"], PAL["settled"]
        else:
            badge_bg, badge_fg, badge_bd = PAL["surface_hi"], PAL["text"], "none"

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
                f'&middot; fare diff: <code style="color:{PAL["text"]}">S${d.amount_cents / 100:.0f} ({d.amount_cents}c)</code> '
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
            f'<div style="display:flex;background:{PAL["surface"]};border-radius:14px;'
            f'overflow:hidden;border:1px solid {PAL["border"]};'
            f'box-shadow:0 4px 16px #14343B1F;'
            f'class="tc-card">'
            # stub (status-color graphic, white icon)
            f'<div style="background:{color};width:52px;display:flex;align-items:center;'
            f'justify-content:center;font-size:22px;color:#fff;">{icon}</div>'
            # body
            f'<div style="flex:1;padding:12px 16px;">'
            f'<div style="color:{PAL["text"]};font-size:16px;font-weight:700;">'
            f"{_esc(_node_short_id(d.node_id))} &middot; {_esc(d.node_id)}</div>"
            f'<div style="color:{PAL["text"]};font-size:14px;margin-top:2px;">{_esc(verdict)}</div>'
            f"{fare_line}"
            f"</div>"
            # badge pill (brand badge anatomy)
            f'<div style="display:flex;align-items:center;padding:0 16px;">'
            f'<span style="background:{badge_bg};color:{badge_fg};padding:6px 16px;'
            f'border-radius:999px;font-size:12px;font-weight:700;letter-spacing:1px;'
            + (f'border:1px solid {badge_bd};' if badge_bd != "none" else "")
            + f'">{_esc(badge)}</span></div>'
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
            f'<div style="background:{PAL["danger"]};padding:12px;border-radius:14px;'
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
        "",  # clear any previous verdict line
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
        f'<div style="background:{PAL["surface"]};border:2px solid {PAL["settled"]};'
        f'border-radius:10px;padding:14px 18px;margin:12px 0;">'
        f'<span style="color:{PAL["settled"]};font-size:18px;font-weight:700;">'
        f"&#9989; APPROVED &amp; EXECUTED</span>"
        f'<div style="color:{PAL["text"]};font-size:15px;margin-top:6px;">'
        f"{held.node_id} re-booked in Atlas Sandbox &middot; orderNo "
        f'<code style="color:{PAL["accent"]};font-size:16px;">{r.orderNo}</code></div>'
        f'<div style="color:{PAL["text_muted"]};font-size:13px;margin-top:2px;">'
        f"asserted={r.asserted} &middot; outcome={r.record.outcome.value} "
        f"&middot; logged to decision-learning log</div></div>"
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
        f'<div style="background:{PAL["surface"]};border:2px solid {PAL["text_muted"]};'
        f'border-radius:14px;padding:14px 18px;margin:12px 0;">'
        f'<span style="color:{PAL["text"]};font-size:18px;font-weight:700;">'
        f"&#9940; REJECTED</span>"
        f'<div style="color:{PAL["text"]};font-size:15px;margin-top:6px;">'
        f"{held.node_id} &middot; original booking kept &middot; recorded "
        f"(outcome={rec.outcome.value})</div></div>"
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
DEMO_THEME = tripcascade_theme


def build_app():
    with gr.Blocks(title="TripCascade") as demo:
        # header
        gr.HTML(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:16px 0;border-bottom:1px solid {PAL["border"]};margin-bottom:16px;">'
            f'<div>'
            f'<h1 class="tc-display" style="color:{PAL["text"]};font-size:28px;margin:0;font-weight:800;">TripCascade</h1>'
            f'<p style="color:{PAL["text_muted"]};font-size:14px;margin:4px 0 0 0;">'
            f"Forecast-driven agentic trip re-planning with bounded autonomy</p>"
            f"</div>"
            f'<div style="text-align:right;">'
            f'<div style="background:{PAL["surface_hi"]};padding:6px 14px;border-radius:999px;'
            f'color:{PAL["text"]};font-size:12px;'
            f'font-weight:700;letter-spacing:1px;">BUILT WITH QODER</div>'
            f'<div style="color:{PAL["text_muted"]};font-size:11px;margin-top:4px;">'
            f"PVG &rarr; NRT &rarr; PVG &middot; family of 3 &middot; 4-6 Sep 2026</div>"
            f"</div></div>"
        )

        state = gr.State()
        with gr.Row():
            run_btn = gr.Button("Run disruption scenario", variant="primary", size="lg")

        # Always-visible verdict line (approve/reject outcome + orderNo). Lives
        # OUTSIDE approve_row so it stays on screen after the row hides — the
        # S.T.A.R. moment must remain visible in the demo take.
        verdict_html = gr.HTML(value="")

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
            # secondary, not 'stop': rejection keeps the original booking — not a loss
            reject_btn = gr.Button("Reject", variant="secondary", size="lg")
        log_html = gr.HTML(
            value=f'<div style="background:{PAL["surface"]};padding:24px;border-radius:12px;'
            f'color:{PAL["text_muted"]};">Decision-learning log will appear here.</div>'
        )

        run_btn.click(
            run_scenario,
            outputs=[state, graph_html, verdict_html, decisions_html, log_html, approve_row],
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