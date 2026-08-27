"""Experiential UI for TripCascade (FR-008, SPECS S-008).

A Gradio Blocks app showing: (a) the trip graph, (b) per-leg P(disruption),
(c) the cascade (affected nodes highlighted), (d) proposed re-plan + fare-difference
summary, (e) Approve/Reject controls for above-cap settlements, (f) the decision log.

Run: uv run python -m tripcascade.ui.app   (or: uv run gradio ... )
This is the demo surface. The deterministic stub backend is used for reliability;
the live Atlas CLI is exercised by the test suite.
"""

from __future__ import annotations

import logging

import gradio as gr

from tripcascade.agent.config import get_settings
from tripcascade.agent.decision_log import DecisionLog
from tripcascade.agent.orchestrator import Orchestrator
from tripcascade.atlas_tools.client import StubAtlasClient
from tripcascade.forecast.inference import predict_disruption_prob
from tripcascade.graph.builder import load_demo_itinerary
from tripcascade.watcher.events import make_scripted_event, populate_forecast

logger = logging.getLogger(__name__)

DISRUPTED_LEG = "leg1_pvg_nrt"
SCRIPTED_P = 0.82  # represents the typhoon-augmented forecast signal (demo trigger)


# --- render helpers ---------------------------------------------------------


def _fmt_prob(p: float | None) -> str:
    return f"{p:.1%}" if p is not None else "—"


def render_graph(graph, cascade=None) -> str:
    """Trip graph as a markdown table: node, type, P(disruption), status, actionable."""
    affected = set(cascade.affected_node_ids) if cascade else set()
    at_risk = cascade.at_risk_node_id if cascade else None
    rows = ["| Node | Type | Route | P(disruption) | Status | Actionable |", "|---|---|---|---|---|---|"]
    for n in graph.nodes.values():
        route = f"{n.location_origin or '–'}→{n.location_destination or '–'}"
        flag = "✈️ flight" if n.actionable else "🏨 advisory"
        mark = ""
        if n.node_id == at_risk:
            mark = " 🔴 at-risk"
        elif n.node_id in affected:
            mark = " ⚠️ affected"
        rows.append(
            f"| {n.node_id}{mark} | {n.node_type.value} | {route} | "
            f"{_fmt_prob(n.disruption_probability)} | {n.status.value} | {flag} |"
        )
    cap = graph.settlement_cap_cents
    return "### Trip dependency graph\n" + "\n".join(rows) + f"\n\n*Settlement cap: S${cap / 100:.0f} ({cap}c)*"


def render_decisions(result) -> str:
    """Per-node policy verdicts + fare-difference summary."""
    if result is None:
        return "### Re-plan & policy verdicts\n*Run the scenario to populate.*"
    lines = ["### Re-plan & policy verdicts"]
    for d in result.decisions:
        emoji = {"auto_executed": "✅", "held": "⏸️", "advisory": "✉️"}.get(d.status.value, "•")
        lines.append(f"**{emoji} {d.node_id}** — {d.verdict}")
        if not d.advisory:
            lines.append(
                f"- action: `{d.action.value}` · fare diff: S${d.amount_cents / 100:.0f} "
                f"({d.amount_cents}c) · model: `{d.model_tier_used}`"
            )
    if result.notifications:
        lines.append("\n#### Drafted notifications (advisory nodes)")
        for nid, text in result.notifications:
            lines.append(f"**{nid}**:\n```\n{text}\n```")
    if result.given_up:
        lines.append(f"\n> ⛔ **GAVE UP**: {result.give_up_reason}")
    return "\n".join(lines)


def render_log(log: DecisionLog) -> str:
    recs = log.query()
    if not recs:
        return "### Decision-learning log\n*No decisions yet.*"
    rows = ["| Record | Node | Action | Amount | Cap | Outcome | Reusable | orderNo |",
            "|---|---|---|---|---|---|---|---|"]
    for r in recs:
        rows.append(
            f"| {r.record_id[:10]} | {r.node_id} | {r.action.value} | S${r.amount_cents / 100:.0f} | "
            f"S${r.cap_cents / 100:.0f} | {r.outcome.value} | {r.reusable} | "
            f"{r.atlas_state_refs.get('orderNo') or '—'} |"
        )
    return f"### Decision-learning log ({len(recs)} records)\n" + "\n".join(rows)


# --- app state + callbacks --------------------------------------------------


class AppState:
    def __init__(self):
        self.orchestrator: Orchestrator | None = None
        self.result = None
        self.log = DecisionLog()


def run_scenario():
    """Load demo itinerary, run forecast + scripted disruption, render everything."""
    st = AppState()
    graph = load_demo_itinerary()
    populate_forecast(graph, predict_disruption_prob)  # wire the forecast (real P per leg)
    orc = Orchestrator(graph=graph, client=StubAtlasClient(get_settings()), decision_log=st.log)
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
        return st, "No held decision to approve.", render_log(st.log if st else DecisionLog()), gr.update(visible=False)
    held = st.result.held_for_approval[0]
    r = st.orchestrator.approve(held, "approved by traveler — return re-book confirmed")
    msg = (
        f"✅ **Approved** {held.node_id}: orderNo `{r.orderNo}` "
        f"(asserted={r.asserted}, outcome={r.record.outcome.value})"
    )
    return st, msg, render_log(st.log), gr.update(visible=False)


def reject_held(st: AppState):
    """UI Reject: record the human rejection (no Atlas write)."""
    if st is None or st.result is None or not st.result.held_for_approval:
        return st, "No held decision to reject.", render_log(st.log if st else DecisionLog()), gr.update(visible=False)
    held = st.result.held_for_approval[0]
    rec = st.orchestrator.policy.reject(held, "rejected by traveler — keep original booking")
    msg = f"⛔ **Rejected** {held.node_id}: recorded (outcome={rec.outcome.value})"
    return st, msg, render_log(st.log), gr.update(visible=False)


def build_app():
    with gr.Blocks(title="TripCascade") as demo:
        gr.Markdown(
            "# TripCascade\n"
            "Forecast-driven agentic trip re-planning with bounded autonomy. "
            "One family trip (PVG→NRT→PVG), one typhoon disruption, one cascade."
        )
        state = gr.State()
        with gr.Row():
            run_btn = gr.Button("▶ Run disruption scenario", variant="primary")
        graph_md = gr.Markdown("### Trip dependency graph\n*Click run to load the itinerary.*")
        decisions_md = gr.Markdown("### Re-plan & policy verdicts")
        with gr.Row(visible=False) as approve_row:
            approve_btn = gr.Button("Approve held re-plan (Leg 2)", variant="primary")
            reject_btn = gr.Button("Reject", variant="stop")
            verdict_md = gr.Markdown("")
        log_md = gr.Markdown("### Decision-learning log")

        run_btn.click(
            run_scenario,
            outputs=[state, graph_md, decisions_md, log_md, approve_row],
        )
        approve_btn.click(
            approve_held,
            inputs=[state],
            outputs=[state, verdict_md, log_md, approve_row],
        )
        reject_btn.click(
            reject_held,
            inputs=[state],
            outputs=[state, verdict_md, log_md, approve_row],
        )
    return demo


def main() -> None:
    app = build_app()
    app.launch(server_name="127.0.0.1", server_port=7860, share=False, inbrowser=False, theme=gr.themes.Soft())


if __name__ == "__main__":
    main()
