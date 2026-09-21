"""AgentCore Platform v1.0 — HCR-C2-048 ProcurementReportGenNode (inner step 4).

Assemble the structured procurement recommendation report from the PMDA,
formulary, and supplier-scoring outcomes computed by the earlier inner steps.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import generate_procurement_report


class ProcurementReportGenNode(FunctionNode):
    """Generate the structured procurement recommendation report."""

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        device_or_drug = state.get("device_or_drug")
        supplier_scores = from_json(state.get("supplier_scores"), [])
        if not device_or_drug or not supplier_scores:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ProcurementReportGenNode: missing device_or_drug or supplier_scores upstream"],
            }

        report = generate_procurement_report(
            device_or_drug=device_or_drug,
            quantity=int(state.get("quantity") or 0),
            pmda_status=state.get("pmda_status", "unknown"),
            pmda_rationale=state.get("pmda_rationale", ""),
            formulary_eligible=bool(state.get("formulary_eligible", False)),
            formulary_notes=state.get("formulary_notes", ""),
            supplier_scores=supplier_scores,
        )

        emit_trace_event(
            "procurement_report_generated",
            {"correlation_id": state.get("correlation_id"), "recommended_supplier": report.get("recommended_supplier")},
            state,
        )

        return {
            "procurement_report": to_json(report),
            "status": AgentStatus.SUCCESS.value,
        }
