"""AgentCore Platform v1.0 — HCR-C2-048 FormularyCheckNode (inner step 2).

Deterministic hospital-formulary eligibility check on the device/drug that
PMDAComplianceCheckNode already resolved into the (inner) graph state.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.service import check_formulary_eligibility


class FormularyCheckNode(FunctionNode):
    """Verify the requested device/drug is on the hospital formulary."""

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        device_or_drug = state.get("device_or_drug")
        if not device_or_drug:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["FormularyCheckNode: device_or_drug missing from pipeline state"],
            }

        formulary_eligible, formulary_notes = check_formulary_eligibility(device_or_drug)

        emit_trace_event(
            "formulary_eligibility_checked",
            {"correlation_id": state.get("correlation_id"), "formulary_eligible": formulary_eligible},
            state,
        )

        return {
            "formulary_eligible": formulary_eligible,
            "formulary_notes": formulary_notes,
            "status": AgentStatus.SUCCESS.value,
        }
