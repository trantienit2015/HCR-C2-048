"""AgentCore Platform v1.0 — HCR-C2-048 ApprovalRouteNode (outer post_process slot).

Decide the final approval routing (auto-approve / HITL-required / rejected)
from the merged PMDA / formulary / supplier-scoring outcome produced by the
inner subgraph, and apply the S-3 pricing-redaction output gate before the
report leaves the trust boundary.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import decide_approval, redact_pricing_for_external


def _emit_progress(message: str, stage: str) -> None:
    """Emit a caller-visible progress event; no-op if unsupported.

    Imported lazily: shared.services.events ships with agentcore 1.0.2+, and a
    module-level import would break test collection on an older local wheel even
    though the deployed image has it. Outside the Marketplace the emitter is a
    no-op, so a failure here must never affect the run.
    """
    try:
        from shared.services.events import emitter
        from shared.services.events.types import EventType

        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message=message,
            metadata={"stage": stage},
        )
    except Exception:  # noqa: BLE001 — progress is cosmetic, never blocking
        pass


class ApprovalRouteNode(FunctionNode):
    """Route the procurement request to auto-approval, HITL, or rejection."""

    # S-1: outer boundary node — matches agent.yaml required_trust_level.
    # S-1: outer post_process — agent response boundary; matches agent.yaml required_trust_level.
    # VERIFIED_EXTERNAL not INTERNAL: the Marketplace runner stamps VERIFIED_EXTERNAL unconditionally and grants INTERNAL to nobody, so an INTERNAL requirement is refused before execute() on every invocation.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, auto_approve_threshold: float = 80.0):
        self._auto_approve_threshold = auto_approve_threshold

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        procurement_report = from_json(state.get("procurement_report"), None)
        if not procurement_report:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ApprovalRouteNode: procurement_report missing — cannot route approval"],
            }

        supplier_scores = from_json(state.get("supplier_scores"), [])
        pmda_status = state.get("pmda_status", "unknown")
        formulary_eligible = bool(state.get("formulary_eligible", False))

        approval_status, hitl_flag, reason = decide_approval(
            pmda_status=pmda_status,
            formulary_eligible=formulary_eligible,
            supplier_scores=supplier_scores,
            auto_approve_threshold=self._auto_approve_threshold,
        )

        external_report = redact_pricing_for_external(procurement_report)
        external_report["approval_status"] = approval_status
        external_report["approval_reason"] = reason

        emit_trace_event(
            "procurement_approval_routed",
            {
                "correlation_id": state.get("correlation_id"),
                "approval_status": approval_status,
                "hitl_flag": hitl_flag,
            },
            state,
        )

        # Progress shown to the caller while the run is in flight, so a
        # multi-second cold start does not read as a frozen chat. Counts
        # and stage only — never caller content.
        _emit_progress("Routing the approval decision.", "post_process")
        return {
            "approval_status": approval_status,
            "hitl_flag": hitl_flag,
            # result = the JSON contract a parent Cat 2 agent consumes.
            "result": to_json(external_report),
            # formatted_output = what a person reads in chat. get_output()
            # surfaces this, so JSON here means the reader gets raw JSON.
            "formatted_output": self._render(
                external_report,
                approval_status,
                reason,
                hitl_flag,
                state.get("ranking_note", ""),
            ),
            "status": AgentStatus.SUCCESS.value,
        }

    @staticmethod
    def _render(report: dict[str, Any], approval_status: str, reason: str, hitl_flag: bool, ranking_note: str) -> str:
        """Markdown summary of the procurement recommendation for a human reader.

        Built from the EXTERNAL (pricing-redacted) report only, so the reader-facing
        surface can never carry pricing the JSON contract already stripped.
        """
        item = report.get("device_or_drug") or "(unspecified item)"
        qty = report.get("quantity")
        lines = [f"## Procurement compliance review — {item}", ""]
        if qty:
            lines.append(f"**Quantity requested:** {qty}")

        pmda = report.get("pmda_status", "unknown")
        eligible = report.get("formulary_eligible")
        lines.append(f"**PMDA approval status:** {pmda}")
        if report.get("pmda_rationale"):
            lines.append(f"  - {report['pmda_rationale']}")
        lines.append("**Hospital formulary:** " + ("eligible" if eligible else "NOT eligible"))
        if report.get("formulary_notes"):
            lines.append(f"  - {report['formulary_notes']}")
        lines.append("")

        supplier = report.get("recommended_supplier")
        score = report.get("recommended_supplier_score")
        if supplier:
            score_text = f" (weighted score {score}/100)" if score is not None else ""
            lines.append(f"**Recommended supplier:** {supplier}{score_text}")
        else:
            lines.append("**Recommended supplier:** none — no candidate qualified.")
        if ranking_note:
            lines.append(f"  - {ranking_note}")
        lines.append("")

        # The decision and its consequence — the part the reader acts on.
        lines.append(f"**Approval routing:** {approval_status}")
        if reason:
            lines.append(f"  - {reason}")
        if hitl_flag:
            lines.append("  - Human review is required before this order proceeds.")
        return "\n".join(lines)

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3 preservation variant: the external (redacted) report must still
        carry the PMDA/formulary verdicts — pricing is stripped, safety-critical
        compliance verdicts are never dropped.
        """
        # Re-check the JSON contract (result), NOT formatted_output: the latter is
        # now human-readable prose and does not parse as JSON. Both surfaces are
        # derived from the same external_report, so verifying the contract plus the
        # prose mention below covers each one.
        formatted = from_json(state.get("result"), {})
        rendered = state.get("formatted_output") or ""
        verdict_in_prose = "PMDA" in rendered and "formulary" in rendered.lower()
        if (
            not isinstance(formatted, dict)
            or "pmda_status" not in formatted
            or "formulary_eligible" not in formatted
            or (rendered and not verdict_in_prose)
        ):
            emit_trace_event("approval_route_safety_recheck_blocked", {}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ApprovalRouteNode: S-3 re-check blocked output missing PMDA/formulary verdict"],
            }
        return state
