# Model-Tier Routing — TripCascade

Shared by **pi** and **Qoder**. Load when selecting a model for a task. Source: `doc/PRD.md` §4 (model-tier routing), `doc/SPECS.md` S-009 (FR-009). Goal: route the cheap 80% of work to cheap tiers; reserve the expensive top-tier for the hard 20% (Cost Controllability rubric evidence).

## 1. The tiers

| Workload | Model | Tier | When |
|---|---|---|---|
| **Routine** — intent parse, entity extraction, formatting, UI glue, notification drafting | `Qwen-Plus` **or** a locally-served open-weight Qwen on the Mac mini M4 Pro | 0.3-1.0x | High volume; latency-sensitive; deterministic-shaped output. |
| **Hard** — dependency-graph cascade reasoning, fare-difference logic, re-plan proposal + rationale | `Qwen3.8-Max` | 1.6x | The hard 20%; called sparingly. |
| **Fallback** — core flow resilience | Local open-weight Qwen on the Mac mini M4 Pro | free | When paid tiers are unavailable/exhausted; keeps the core flow off paid-only. |

## 2. Rules

1. **Label every call** with `model_tier_used` in the decision-learning record (FR-007) and logs. This is the Cost-Controllability evidence.
2. **Default to the cheapest tier that can do the job.** Escalate to `Qwen3.8-Max` only when the task is genuinely hard reasoning (cascade, fare-diff).
3. **The local open-weight fallback must be exercised at least once** in testing (FR-009 verification) — the core flow cannot be solely on a paid top-tier.
4. **The LLM proposes; deterministic code decides and executes.** Model routing affects *reasoning* calls only. The policy engine (FR-006) is always deterministic code; the LLM never free-forms transaction content regardless of tier.
5. **Credits:** hackathon Qoder credits + free `Qwen3.8-Max` credits (Mike-approved). Route routine work to cheap tiers to conserve them.

## 3. Routing decision (pseudo)

```
if task in {parse_intent, extract_entities, format_output, draft_notification, ui_glue}:
    model = Qwen-Plus or local_open_weight
elif task in {cascade_reasoning, fare_difference_logic, replan_proposal}:
    model = Qwen3.8-Max
if model unavailable or credits exhausted:
    model = local_open_weight  # fallback; log it
```

## 4. Resilience

If a paid tier call fails or times out, fall back to the local open-weight model and continue the core flow. Log the fallback. Never let a paid-tier outage block the demo's core cascade.
