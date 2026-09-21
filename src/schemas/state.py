"""AgentCore Platform v1.0 — HCR-C2-048 state schema.

Medical Equipment & Pharma Procurement Compliance Agent.
Flat TypedDict extension of AgentState (ADR-005). Structured payloads
(dict/list) are JSON-string-encoded before being stored in state fields so
every field stays msgpack-safe across a LangGraph checkpoint.
"""

import json

from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def from_json(value: Any, default: Any = None) -> Any:
    if not value:
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# Type-check note: the wheel ships no py.typed, so mypy resolves AgentState to
# Any and reports every NotRequired below as valid-type. The fields are correct
# (NotRequired is required here) -- the report is a packaging artifact, suppressed
# per field. Drop these ignores once the wheel ships py.typed.
class State(AgentState):
    """Agent state for HCR-C2-048.

    All agent-specific fields are NotRequired[...] (This contract) and read via
    state.get(...). Structured payloads (lists/dicts) are stored as JSON
    strings (see to_json/from_json helpers above).

    device_or_drug: name/code of the requested medical device or pharma item.
    quantity: requested unit quantity.
    supplier_candidates: JSON list[dict] of candidate suppliers {name, price,
        delivery_days, quality_score, is_new_supplier}.
    clinical_justification: free-text clinical justification supplied by the requester.
    pmda_status: "approved" | "not_approved" | "unknown" — PMD Act approval verdict.
    pmda_rationale: short deterministic rationale for the PMDA verdict.
    formulary_eligible: whether the item is on the hospital formulary.
    formulary_notes: short deterministic rationale for the formulary verdict.
    supplier_scores: JSON list[dict] {supplier, score, breakdown} sorted best-first.
    selected_supplier: name of the top-scoring supplier.
    procurement_report: JSON dict — structured recommendation report.
    approval_status: "auto_approved" | "hitl_required" | "rejected".
    hitl_flag: True when the request is routed to a human-review queue.
    kb_version: PMDA/formulary corpus version used for this decision.
    """

    device_or_drug: NotRequired[str]  # type: ignore[valid-type]
    quantity: NotRequired[int]  # type: ignore[valid-type]
    supplier_candidates: NotRequired[str]  # type: ignore[valid-type]
    clinical_justification: NotRequired[str]  # type: ignore[valid-type]
    pmda_status: NotRequired[str]  # type: ignore[valid-type]
    pmda_rationale: NotRequired[str]  # type: ignore[valid-type]
    formulary_eligible: NotRequired[bool]  # type: ignore[valid-type]
    formulary_notes: NotRequired[str]  # type: ignore[valid-type]
    supplier_scores: NotRequired[str]  # type: ignore[valid-type]
    selected_supplier: NotRequired[str]  # type: ignore[valid-type]
    procurement_report: NotRequired[str]  # type: ignore[valid-type]
    approval_status: NotRequired[str]  # type: ignore[valid-type]
    hitl_flag: NotRequired[bool]  # type: ignore[valid-type]
    kb_version: NotRequired[str]  # type: ignore[valid-type]
    ranking_note: NotRequired[str]  # type: ignore[valid-type]
    formatted_output: NotRequired[str]  # type: ignore[valid-type]
