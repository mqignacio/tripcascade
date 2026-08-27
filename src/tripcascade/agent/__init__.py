"""Agent orchestrator: disruption event -> cascade -> Atlas re-plan -> settlement.

Includes the deterministic policy engine (FR-006): auto-settle <= cap with audit
log; human approval above cap. The LLM proposes; the policy engine decides and
builds the Atlas call body from structured data (never free-form). Also hosts
model-tier routing (FR-009) and the decision-learning log (FR-007).
"""
