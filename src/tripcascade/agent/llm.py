"""Pluggable LLM proposal backend.

The LLM's ONLY job is to propose *which* alternative + rationale for a re-plan
(a HARD-tier reasoning task per `skills/model_routing.md`). The deterministic
policy engine (`agent/policy.py`) then builds the Atlas call body and decides
auto vs human. The LLM never free-forms transaction content.

Backends:
- :class:`StubProposalBackend` — deterministic stand-in (default for tests + the
  offline demo so the cascade is reliable). Picks the first alternative and
  computes the fare difference from prices; routes via :class:`Router` so the
  recorded `model_tier_used` is a real routing decision (incl. fallback).
- :class:`DashScopeProposalBackend` — real Qwen call via the OpenAI-compatible
  DashScope endpoint (verified working 2026-08-28 on `dashscope-intl.aliyuncs.com`).
  Uses `httpx` only (no SDK dep). Asks the model to pick an alternative + return
  JSON; the fare difference is computed deterministically from prices (the LLM
  never computes money). Degrades to the stub on any failure (reliability).

Model ID mapping (display name -> DashScope API ID; verified against the live
`/compatible-mode/v1/models` catalog, `resources/dashscope-model.md`):
    Qwen3.8-Max  -> qwen3.8-max   (HARD tier)
    Qwen3.7-Plus -> qwen3.7-plus  (ROUTINE tier)
    Qwen-Plus    -> qwen3.7-plus  (PRD's "Qwen-Plus" maps to this available model)

Honesty: the LLM only PROPOSES. The policy engine builds the Atlas call body
(skills/human_checkpoint_rules.md §3.1). Routing affects reasoning calls only.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol

import httpx

from tripcascade.agent.router import Router, TaskKind
from tripcascade.graph.models import Node, Offer, ReplanProposal

logger = logging.getLogger(__name__)

# Display name -> DashScope API model ID (verified against live catalog 2026-08-28)
MODEL_ID_MAP = {
    "Qwen3.8-Max": "qwen3.8-max",
    "Qwen3.7-Plus": "qwen3.7-plus",
    "Qwen-Plus": "qwen3.7-plus",  # PRD's routine name -> the available frontier model
    "Qwen-Max": "qwen-max",
    "local-open-weight": "local-open-weight",  # fallback (no real call)
}

SYSTEM_PROMPT = (
    "You are TripCascade's re-planning assistant. Given a disrupted flight leg "
    "and a list of re-booking alternatives, choose the best alternative and "
    "explain your reasoning concisely. Consider schedule fit, carrier, and "
    "minimizing downstream disruption. Return ONLY valid JSON, no markdown fences:\n"
    '{"chosen_offer_id": "<offer_id>", "rationale": "<one or two sentences>"}\n'
    "Do NOT compute prices or fare differences — the deterministic policy engine "
    "handles those. Pick from the alternatives provided; if none are suitable, "
    'set "chosen_offer_id" to null.'
)


class ProposalBackend(Protocol):
    """Propose a re-plan for an affected actionable node."""

    def propose_replan(
        self, node: Node, alternatives: list[Offer], cascade_context: str
    ) -> ReplanProposal: ...


def _compute_fare_diff(node: Node, chosen: Offer | None) -> int:
    """Deterministic fare difference (cents) from the chosen offer's price.

    The LLM never computes money; this is the policy engine's job. Positive =
    a price increase (fare difference to settle); negative = a refund.
    """
    if chosen is None or chosen.total_price is None:
        return 0
    orig_cents = int(round(node.total_price * 100)) if node.total_price is not None else 0
    new_cents = int(round(chosen.total_price * 100))
    return new_cents - orig_cents


class StubProposalBackend:
    """Deterministic proposal backend (tests + offline demo).

    Picks the first alternative and computes the fare difference from the
    chosen offer price vs the node's original fare. Routes the call via the
    Router so ``model_tier_used`` reflects a real (hard -> maybe fallback) tier.
    """

    def __init__(self, router: Router) -> None:
        self.router = router

    def propose_replan(
        self, node: Node, alternatives: list[Offer], cascade_context: str
    ) -> ReplanProposal:
        decision = self.router.route(TaskKind.REPLAN_PROPOSAL)
        if not alternatives:
            return ReplanProposal(
                node_id=node.node_id,
                rationale="no alternatives found; advisory hold",
                fare_difference_cents=0,
                model_tier_used=decision.model_tier_used,
            )
        chosen = alternatives[0]
        fare_diff = _compute_fare_diff(node, chosen)
        rationale = (
            f"Re-route {node.node_id} ({node.location_origin}->{node.location_destination}) "
            f"via {chosen.carrier or 'alt'} offer {chosen.offer_id} "
            f"(S${chosen.total_price:.2f} {chosen.currency}; fare diff {fare_diff}c). "
            f"[Stub backend — deterministic stand-in; production routes this reasoning to "
            f"{self.router.settings.hard_model}.] Context: {cascade_context}"
        )
        return ReplanProposal(
            node_id=node.node_id,
            chosen_offer_id=chosen.offer_id,
            alternative_index=0,
            rationale=rationale,
            fare_difference_cents=fare_diff,
            model_tier_used=decision.model_tier_used,
        )


class DashScopeProposalBackend:
    """Real Qwen proposal backend via the OpenAI-compatible DashScope endpoint.

    Uses `httpx` (already a dep) + the OpenAI-compatible chat completions API.
    The model only PROPOSES (which alternative + rationale, as JSON); the
    deterministic policy engine builds the Atlas call body. Degrades to the
    Stub backend on any failure (network, parse, API error) so the demo never
    breaks on a paid-tier hiccup.
    """

    def __init__(self, router: Router) -> None:
        self.router = router
        s = router.settings
        if not s.dashscope_api_key:
            raise RuntimeError("DashScopeProposalBackend requires DASHSCOPE_API_KEY")

    def _model_id(self, display_name: str) -> str:
        """Map a display name (Qwen3.8-Max) to a DashScope API ID (qwen3.8-max)."""
        return MODEL_ID_MAP.get(display_name, display_name.lower())

    def _call_qwen(self, model_id: str, user_msg: str) -> str | None:
        """Make a real OpenAI-compatible chat call; return the content or None."""
        s = self.router.settings
        headers = {"Authorization": f"Bearer {s.dashscope_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 300,
            "temperature": 0.2,
        }
        try:
            with httpx.Client(timeout=90) as client:
                resp = client.post(
                    f"{s.dashscope_base_url}/chat/completions", headers=headers, json=payload
                )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning("DashScope call to %s failed (%s); degrading to stub", model_id, e)
            return None

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        """Robustly extract the JSON object from the model's response."""
        if not content:
            return None
        # strip markdown fences if present
        text = content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # find the first {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None

    def propose_replan(
        self, node: Node, alternatives: list[Offer], cascade_context: str
    ) -> ReplanProposal:
        decision = self.router.route(TaskKind.REPLAN_PROPOSAL)
        model_id = self._model_id(decision.intended_model)

        if not alternatives:
            return ReplanProposal(
                node_id=node.node_id,
                rationale="no alternatives found; advisory hold",
                fare_difference_cents=0,
                model_tier_used=decision.model_tier_used,
            )

        # build the user message describing the disrupted leg + alternatives
        alt_lines = []
        for i, o in enumerate(alternatives):
            seg = (o.segments or [{}])[0] if o.segments else {}
            alt_lines.append(
                f"  {i}. offer_id={o.offer_id} carrier={o.carrier or '?'} "
                f"price={o.total_price:.2f}{o.currency} "
                f"depart={seg.get('departure_time', '?')} arrive={seg.get('arrival_time', '?')}"
            )
        user_msg = (
            f"Disrupted leg: {node.node_id} ({node.location_origin}->{node.location_destination}), "
            f"carrier={node.carrier} flight={node.flight_number or '?'} "
            f"departing {node.scheduled_start.isoformat()}.\n"
            f"Alternatives:\n" + "\n".join(alt_lines) + "\n"
            f"Cascade context: {cascade_context}\n"
            f"Pick the best alternative for re-booking. Return ONLY JSON."
        )

        # route the routine notification drafting too (the router logs it)
        self.router.route(TaskKind.DRAFT_NOTIFICATION)

        content = self._call_qwen(model_id, user_msg)
        parsed = self._parse_json(content) if content else None

        if parsed and parsed.get("chosen_offer_id"):
            chosen_id = parsed["chosen_offer_id"]
            chosen = next((o for o in alternatives if o.offer_id == chosen_id), alternatives[0])
            idx = alternatives.index(chosen) if chosen in alternatives else 0
            rationale = parsed.get("rationale", "") or f"LLM chose {chosen_id}"
            logger.info("DashScope %s chose offer %s for %s", model_id, chosen_id, node.node_id)
        else:
            # degrade: pick first alternative (stub behavior) but note the degradation
            chosen = alternatives[0]
            idx = 0
            rationale = (
                f"[LLM response unparseable; degraded to first alternative] "
                f"Re-route {node.node_id} via {chosen.carrier or 'alt'} offer {chosen.offer_id}."
            )
            logger.warning("DashScope response unparseable for %s; degraded to stub", node.node_id)

        fare_diff = _compute_fare_diff(node, chosen)
        return ReplanProposal(
            node_id=node.node_id,
            chosen_offer_id=chosen.offer_id,
            alternative_index=idx,
            rationale=rationale,
            fare_difference_cents=fare_diff,
            model_tier_used=decision.model_tier_used,
        )


def make_backend(router: Router) -> ProposalBackend:
    """Factory: DashScope (real Qwen) if a key is set + backend != 'stub', else Stub."""
    s = router.settings
    if s.dashscope_api_key and s.llm_backend != "stub":
        try:
            return DashScopeProposalBackend(router)
        except Exception as e:
            logger.warning("DashScope backend init failed (%s); using Stub", e)
    return StubProposalBackend(router)
