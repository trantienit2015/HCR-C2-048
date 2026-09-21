"""AgentCore Platform v1.0 — HCR-C2-048 SupplierScoreNode (inner step 3).

Deterministic weighted-rubric supplier scoring (price/delivery/quality/PMDA
bonus). An optional injected LLM is used ONLY to produce a human-readable
free-text summary note of the ranking — never for the score/ranking decision
itself, which stays fully deterministic and auditable.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import score_suppliers


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


class SupplierScoreNode(FunctionNode):
    """Score and rank candidate suppliers with a deterministic weighted rubric."""

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, llm: Any = None):
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        supplier_candidates = from_json(state.get("supplier_candidates"), [])
        if not supplier_candidates:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["SupplierScoreNode: supplier_candidates missing or empty"],
            }

        pmda_status = state.get("pmda_status", "unknown")
        scored = score_suppliers(supplier_candidates, pmda_status)
        selected_supplier = scored[0]["supplier"] if scored else None

        # LLM is optional and used only for a free-text interpretation note —
        # the ranking/score above is already final and deterministic.
        # The reply MUST be read out of ["content"]: BaseLLM.complete() returns the
        # canonical dict {content, tool_calls, model, usage}. Discarding the return
        # value (as this did) means paying for the call and keeping nothing, with
        # the bare except hiding even a TypeError.
        ranking_note = ""
        if self._llm is not None and scored:
            try:
                reply = self._llm.complete(f"Summarize supplier ranking in one sentence: {scored[:3]}")
                if isinstance(reply, dict):
                    ranking_note = str(reply.get("content") or "").strip()
                elif isinstance(reply, str):
                    ranking_note = reply.strip()
            except Exception as exc:  # noqa: BLE001 — the note is best-effort
                # Observable rather than silent: a persistent failure here means
                # the LLM is misconfigured, which a swallowed exception hides.
                emit_trace_event(
                    "supplier_ranking_note_unavailable",
                    {"correlation_id": state.get("correlation_id"), "reason": type(exc).__name__},
                    state,
                )

        emit_trace_event(
            "suppliers_scored",
            {"correlation_id": state.get("correlation_id"), "candidate_count": len(supplier_candidates)},
            state,
        )

        # Progress shown to the caller while the run is in flight, so a
        # multi-second cold start does not read as a frozen chat. Counts
        # and stage only — never caller content.
        _emit_progress(f"Scored {len(scored)} supplier(s) against the weighted rubric.", "main")
        return {
            "supplier_scores": to_json(scored),
            "selected_supplier": selected_supplier,
            "ranking_note": ranking_note,
            "status": AgentStatus.SUCCESS.value,
        }
