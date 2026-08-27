"""Decision-learning log (FR-007, SPECS §4.3).

Every auto-settlement and every above-cap human verdict is written as a
structured, reusable record to `logs/decision_log.jsonl` (JSONL, append-only).
The corpus is the moat: today's human judgement -> tomorrow's threshold
(`resources/founder_lessons.md`). Records are `reusable=true` by default.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tripcascade.graph.models import ActionType, DecisionRecord, Outcome

logger = logging.getLogger(__name__)

# SPECS §4.3 required fields (schema validation)
REQUIRED_FIELDS = (
    "record_id",
    "timestamp",
    "node_id",
    "action",
    "amount_cents",
    "cap_cents",
    "outcome",
    "human_verdict",
    "reasoning_trace",
    "model_tier_used",
    "atlas_state_refs",
    "reusable",
)


class DecisionLog:
    """Append-only JSONL decision log with schema validation + query."""

    def __init__(self, path: Path | str | None = None) -> None:
        from tripcascade.agent.config import get_settings

        self.path = Path(path) if path else get_settings().decision_log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, record: DecisionRecord) -> DecisionRecord:
        """Validate + append a record. Returns the record (for chaining)."""
        self.validate_schema(record)
        with self.path.open("a") as f:
            f.write(record.model_dump_json() + "\n")
        logger.info("decision logged: %s outcome=%s node=%s", record.record_id, record.outcome, record.node_id)
        return record

    def query(self, node_id: str | None = None) -> list[DecisionRecord]:
        """Return records, optionally filtered by node_id."""
        records: list[DecisionRecord] = []
        if not self.path.exists():
            return records
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = DecisionRecord(**json.loads(line))
            except Exception as e:
                logger.warning("skipping malformed log line: %s", e)
                continue
            if node_id is None or rec.node_id == node_id:
                records.append(rec)
        return records

    def clear(self) -> None:
        """Truncate the log (demo reset)."""
        self.path.write_text("")

    @staticmethod
    def validate_schema(record: DecisionRecord) -> None:
        """Assert all SPECS §4.3 fields present + enums valid."""
        dumped = record.model_dump()
        missing = [f for f in REQUIRED_FIELDS if f not in dumped]
        assert not missing, f"decision record missing fields: {missing}"
        assert isinstance(record.amount_cents, int), "amount_cents must be int"
        assert isinstance(record.cap_cents, int), "cap_cents must be int"
        assert isinstance(record.reusable, bool), "reusable must be bool"
        assert isinstance(record.action, ActionType), "action must be ActionType enum"
        assert isinstance(record.outcome, Outcome), "outcome must be Outcome enum"
        assert record.outcome in (
            Outcome.AUTO_SETTLED,
            Outcome.HUMAN_APPROVED,
            Outcome.HUMAN_REJECTED,
        ), f"invalid outcome: {record.outcome}"

    @staticmethod
    def new_record_id() -> str:
        return f"dec_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
