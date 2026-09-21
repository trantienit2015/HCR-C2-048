"""AgentCore Platform v1.0 — HCR-C2-048 PMDAComplianceCheckNode (inner step 1).

First inner node — the inner subgraph only sees the JSON string forwarded via
GraphNode.extract_input() (seeded into state["user_input"] by BaseGraph.invoke()),
never the outer state directly (GraphNode subgraph boundary). Reconstructs the
procurement request payload and runs the deterministic PMD Act approval check.
"""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import to_json
from src.services.service import check_pmda_approval


class PMDAComplianceCheckNode(FunctionNode):
    """Verify PMD Act approval status for the requested device/drug."""

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            payload = None

        if not isinstance(payload, dict) or not payload.get("device_or_drug"):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PMDAComplianceCheckNode: procurement request payload missing or invalid"],
            }

        device_or_drug = payload["device_or_drug"]
        quantity = payload.get("quantity")
        supplier_candidates = payload.get("supplier_candidates") or []
        clinical_justification = payload.get("clinical_justification", "")

        pmda_status, pmda_rationale = check_pmda_approval(device_or_drug)

        emit_trace_event(
            "pmda_compliance_checked",
            {"correlation_id": state.get("correlation_id"), "pmda_status": pmda_status},
            state,
        )

        return {
            "device_or_drug": device_or_drug,
            "quantity": quantity,
            "supplier_candidates": to_json(supplier_candidates),
            "clinical_justification": clinical_justification,
            "pmda_status": pmda_status,
            "pmda_rationale": pmda_rationale,
            "status": AgentStatus.SUCCESS.value,
        }
