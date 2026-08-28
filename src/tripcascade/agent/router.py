"""Model-tier routing (FR-009, SPECS S-009).

Route the cheap 80% of work to a cheap tier; reserve the expensive top-tier for
the hard 20% (Cost Controllability). Source: `skills/model_routing.md`,
`resources/qoder-model.md` (the Qoder model list).

Tiers (from resources/qoder-model.md):
- ROUTINE: `Qwen3.7-Plus` (0.1x) — parse/format/entity-extract/notification/UI glue.
  (PRD's "Qwen-Plus" maps to this available frontier model.)
- HARD: `Qwen3.8-Max` (0.5x) — cascade reasoning, fare-difference logic, re-plan proposal.
- FALLBACK: `local-open-weight` — when paid tiers are unavailable; keeps the core
  flow off paid-only models. Must be exercised >= once in testing.

The LLM proposes; deterministic code (policy.py) decides and executes. Routing
affects *reasoning* calls only (`skills/model_routing.md` §2.4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from tripcascade.agent.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    ROUTINE = "routine"
    HARD = "hard"
    FALLBACK = "fallback"


class TaskKind(str, Enum):
    # routine (cheap 80%)
    PARSE_INTENT = "parse_intent"
    EXTRACT_ENTITIES = "extract_entities"
    FORMAT_OUTPUT = "format_output"
    DRAFT_NOTIFICATION = "draft_notification"
    UI_GLUE = "ui_glue"
    # hard 20%
    CASCADE_REASONING = "cascade_reasoning"
    FARE_DIFFERENCE_LOGIC = "fare_difference_logic"
    REPLAN_PROPOSAL = "replan_proposal"


_ROUTINE_TASKS = {
    TaskKind.PARSE_INTENT,
    TaskKind.EXTRACT_ENTITIES,
    TaskKind.FORMAT_OUTPUT,
    TaskKind.DRAFT_NOTIFICATION,
    TaskKind.UI_GLUE,
}
_HARD_TASKS = {
    TaskKind.CASCADE_REASONING,
    TaskKind.FARE_DIFFERENCE_LOGIC,
    TaskKind.REPLAN_PROPOSAL,
}


@dataclass
class RoutingDecision:
    """One routing call's decision (the Cost-Controllability evidence)."""

    task_kind: TaskKind
    tier: ModelTier
    model_name: str
    intended_model: str  # what would be used if paid tiers were available
    fallback_used: bool = False
    model_tier_used: str = ""  # the label recorded in the decision-learning log

    def __post_init__(self) -> None:
        self.model_tier_used = self.model_name


class Router:
    """Select a model tier per task; fall back to local-open-weight when paid is down."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.history: list[RoutingDecision] = []

    def is_paid_available(self) -> bool:
        """True if a DashScope/Bailian key is configured (enables real Qwen calls)."""
        return bool(self.settings.dashscope_api_key)

    def route(self, task_kind: TaskKind) -> RoutingDecision:
        """Decide tier + model for a task; record the routing for audit."""
        if task_kind in _ROUTINE_TASKS:
            tier, intended = ModelTier.ROUTINE, self.settings.routine_model
        elif task_kind in _HARD_TASKS:
            tier, intended = ModelTier.HARD, self.settings.hard_model
        else:  # defensive default: routine
            tier, intended = ModelTier.ROUTINE, self.settings.routine_model

        fallback = not self.is_paid_available()
        model_name = self.settings.local_fallback_model if fallback else intended
        if fallback:
            tier = ModelTier.FALLBACK

        decision = RoutingDecision(
            task_kind=task_kind,
            tier=tier,
            model_name=model_name,
            intended_model=intended,
            fallback_used=fallback,
        )
        self.history.append(decision)
        logger.info(
            "routed %s -> tier=%s model=%s (intended=%s fallback=%s)",
            task_kind.value, tier.value, model_name, intended, fallback,
        )
        return decision

    def last_tier_for(self, task_kind: TaskKind) -> str | None:
        """Most recent model_tier_used for a task kind (test helper)."""
        for d in reversed(self.history):
            if d.task_kind == task_kind:
                return d.model_tier_used
        return None
