"""AgentCore Platform v1.0 — HCR-C2-048 ProcurementRequestParseNode (outer pre_process slot).

Parse and validate the incoming procurement request JSON:
{device_or_drug, quantity, supplier_candidates: [...], clinical_justification}.
S-2 domain check: flag institution-confidential markers (patient identifiers)
that must never travel through a procurement-compliance pipeline.
"""

import json
import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import to_json

# Deterministic, non-LLM scan for institution-confidential / patient-identifying
# markers that must never appear in a procurement compliance request (S-2).
# Institution-confidential markers. The separator after an identifier label is
# optional: a conversational caller writes "patient-id 12345678901234" with a
# space, and requiring ":" or "#" let exactly that through. A bare 12-digit run
# (My Number shape) is also rejected on its own.
_CONFIDENTIAL_PATTERNS = re.compile(
    r"(patient[_\s-]?id\s*[:#]?\s*\d|mrn\s*[:#]?\s*\d|\bmy\s*number\b|マイナンバー|\b\d{12}\b)",
    re.IGNORECASE,
)


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


class ProcurementRequestParseNode(FunctionNode):
    """Validate the procurement request and reject institution-confidential input."""

    # S-1: outer boundary node — matches agent.yaml required_trust_level (INTERNAL:
    # this agent is invoked by the hospital procurement system, not public callers).
    # S-1: outer pre_process — first node to receive caller input; matches
    # agent.yaml required_trust_level.
    # VERIFIED_EXTERNAL not INTERNAL: the Marketplace runner stamps
    # VERIFIED_EXTERNAL unconditionally and grants INTERNAL to nobody, so an
    # INTERNAL requirement is refused before execute() on every invocation.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        user_input = state.get("user_input", "")
        if not user_input or not str(user_input).strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ProcurementRequestParseNode: user_input is empty or missing"],
            }

        try:
            payload = json.loads(user_input) if isinstance(user_input, str) else user_input
        except (TypeError, ValueError):
            payload = None

        # A procurement system posts the JSON request object. A person asking in
        # chat types a sentence, which would otherwise be rejected as "not valid
        # JSON" and return an empty reply — indistinguishable from a dead pod.
        # Parse what the sentence does carry; anything still missing is reported
        # by the field checks below, which name the field rather than the format.
        if not isinstance(payload, dict) and isinstance(user_input, str):
            payload = self._request_from_prose(user_input)

        if not isinstance(payload, dict):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ProcurementRequestParseNode: payload must be a JSON object"],
            }

        device_or_drug = str(payload.get("device_or_drug") or "").strip()
        quantity = payload.get("quantity")
        supplier_candidates = payload.get("supplier_candidates") or []
        clinical_justification = str(payload.get("clinical_justification") or "").strip()

        if not device_or_drug:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ProcurementRequestParseNode: device_or_drug is required"],
            }
        if not isinstance(quantity, int) or quantity <= 0:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "ProcurementRequestParseNode: quantity must be a positive integer "
                    "(state how many units are being ordered)"
                ],
            }
        if not isinstance(supplier_candidates, list) or not supplier_candidates:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "ProcurementRequestParseNode: supplier_candidates must be a non-empty list "
                    "(name at least one supplier being considered)"
                ],
            }

        if _CONFIDENTIAL_PATTERNS.search(clinical_justification):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "ProcurementRequestParseNode: clinical_justification contains an institution-confidential "
                    "patient identifier marker — rejected before entering the procurement pipeline"
                ],
            }

        validated = {
            "device_or_drug": device_or_drug,
            "quantity": quantity,
            "supplier_candidates": supplier_candidates,
            "clinical_justification": clinical_justification,
        }

        # Progress shown to the caller while the run is in flight, so a
        # multi-second cold start does not read as a frozen chat. Counts
        # and stage only — never caller content.
        _emit_progress(
            f"Procurement request validated ({len(supplier_candidates)} supplier candidate(s)).", "pre_process"
        )
        emit_trace_event(
            "procurement_request_parsed",
            {
                "correlation_id": state.get("correlation_id"),
                "supplier_count": len(supplier_candidates),
            },
            state,
        )

        return {
            "device_or_drug": device_or_drug,
            "quantity": quantity,
            "supplier_candidates": to_json(supplier_candidates),
            "clinical_justification": clinical_justification,
            "validated_input": to_json(validated),
            "status": AgentStatus.SUCCESS.value,
        }

    # Conversational path only. Deliberately narrow: each field must be introduced
    # by its own cue word, so an unrelated number or name is never promoted into a
    # procurement request. Whatever is missing is reported by the field checks.
    # Conversational path only. Deliberately narrow: each field must be introduced
    # by its own cue word, so an unrelated number or name is never promoted into a
    # procurement request. Whatever is missing is reported by the field checks.
    _QTY_RE = re.compile(
        r"(?:qty|quantity|order(?:ing)?|need|buy|purchase|procure)\D{0,12}(\d{1,6})",
        re.I,
    )
    # The item follows the verb, optionally after a count and a 'units of' phrase,
    # and stops at the next cue word so a trailing clause is not absorbed.
    _ITEM_RE = re.compile(
        r"(?:procure|purchase|order(?:ing)?|buy)\s+(?:\d{1,6}\s+)?(?:units?\s+of\s+)?([A-Za-z0-9][\w\-/.%  ]{2,60}?)(?=\s+(?:from|for|because|due|to\s)| \s*,|\s*\.(?:\s|$)|$)",
        re.I,
    )
    # Supplier stops before a purpose clause ('for the ICU refit') as well as
    # punctuation, so the captured name is the supplier alone.
    _SUPPLIER_RE = re.compile(
        r"from\s+([A-Za-z0-9][\w\-&. ]{2,60}?)(?=\s+(?:for|because|due|to\s)|\s*(?:[,.]|and\s)|$)",
        re.I,
    )

    @classmethod
    def _request_from_prose(cls, raw_text: str) -> dict[str, Any] | None:
        """Build a procurement request from a free-text sentence.

        Returns None when the sentence carries nothing recognizable, so the caller
        falls through to the normal rejection path rather than inventing a request.
        """
        text = (raw_text or "").strip()
        if not text:
            return None

        item_match = cls._ITEM_RE.search(text)
        qty_match = cls._QTY_RE.search(text)
        supplier_match = cls._SUPPLIER_RE.search(text)
        if not (item_match or qty_match or supplier_match):
            return None

        suppliers = []
        if supplier_match:
            # score_suppliers() reads "name" (service.py); a "supplier" key here
            # would score as the literal "unknown" and lose the name in the reply.
            # No price/delivery/quality figures come from prose, so the rubric
            # falls back to its neutral defaults for those dimensions.
            suppliers = [{"name": supplier_match.group(1).strip()}]

        return {
            "device_or_drug": item_match.group(1).strip() if item_match else "",
            "quantity": int(qty_match.group(1)) if qty_match else None,
            "supplier_candidates": suppliers,
            # The whole sentence is the justification; the confidential-marker scan
            # below still applies to it exactly as it does to a structured caller.
            "clinical_justification": text,
        }
