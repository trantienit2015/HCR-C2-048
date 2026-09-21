"""AgentCore Platform v1.0 — HCR-C2-048 domain service layer.

Deterministic PMD Act compliance, formulary-eligibility, and supplier-scoring
logic for the Medical Equipment & Pharma Procurement Compliance Agent. Pure
functions only — no framework imports, no side effects, no credentials. Nodes
call these; a real deployment would back the lookup tables below with a
KB/DB retrieval, but the rubric/decision logic itself stays deterministic
(not delegated to an LLM) so procurement compliance decisions are auditable
and reproducible.
"""

from __future__ import annotations

from typing import Any
# --- Reference data (would be sourced from PMDA corpus / hospital formulary
# KB in a real deployment; kept in-process here so the agent is deterministic
# and does not require an external KB connection to be reviewable/testable). ---

_PMDA_APPROVED_ITEMS = {
    "ventilator-model-x",
    "infusion-pump-a",
    "surgical-mask-n95",
    "insulin-glargine",
    "amoxicillin-500mg",
}
_PMDA_UNKNOWN_ITEMS: set[str] = set()

_FORMULARY_ITEMS = {
    "ventilator-model-x",
    "infusion-pump-a",
    "insulin-glargine",
    "amoxicillin-500mg",
}


def normalize_item_code(raw: str | None) -> str:
    return (raw or "").strip().lower()


def check_pmda_approval(device_or_drug: str) -> tuple[str, str]:
    """Deterministic PMD Act approval-status check.

    Returns (status, rationale). status is one of
    "approved" | "not_approved" | "unknown".
    """
    item = normalize_item_code(device_or_drug)
    if not item:
        return "unknown", "No device/drug identifier supplied."
    if item in _PMDA_APPROVED_ITEMS:
        return "approved", f"'{device_or_drug}' matches a PMDA-approved entry in the reference corpus."
    if item in _PMDA_UNKNOWN_ITEMS:
        return (
            "unknown",
            f"'{device_or_drug}' is not present in the PMDA reference corpus — manual verification required.",
        )
    return "not_approved", f"'{device_or_drug}' does not match any PMDA-approved entry (PMD Act check failed)."


def check_formulary_eligibility(device_or_drug: str) -> tuple[bool, str]:
    """Deterministic hospital-formulary eligibility check.

    Returns (eligible, notes).
    """
    item = normalize_item_code(device_or_drug)
    if not item:
        return False, "No device/drug identifier supplied."
    if item in _FORMULARY_ITEMS:
        return True, f"'{device_or_drug}' is on the hospital formulary."
    return False, f"'{device_or_drug}' is NOT on the hospital formulary — non-formulary purchase review required."


def score_suppliers(suppliers: list[dict[str, Any]], pmda_status: str) -> list[dict[str, Any]]:
    """Deterministic weighted-rubric supplier scoring.

    Rubric (0-100): price 30% (lower is better, normalized against the
    candidate set) + delivery 20% (fewer days is better) + quality_score
    40% (already 0-100 from the supplier's quality record) + pmda bonus 10%
    (only if the overall PMDA verdict is "approved").
    """
    if not suppliers:
        return []

    prices = [max(float(s.get("price", 0) or 0), 0.0) for s in suppliers]
    max_price = max(prices) if prices else 0.0
    deliveries = [max(float(s.get("delivery_days", 0) or 0), 0.0) for s in suppliers]
    max_delivery = max(deliveries) if deliveries else 0.0
    pmda_bonus = 10.0 if pmda_status == "approved" else 0.0

    scored = []
    for supplier in suppliers:
        price = max(float(supplier.get("price", 0) or 0), 0.0)
        delivery = max(float(supplier.get("delivery_days", 0) or 0), 0.0)
        quality = min(max(float(supplier.get("quality_score", 0) or 0), 0.0), 100.0)

        price_score = 30.0 * (1.0 - (price / max_price)) if max_price > 0 else 30.0
        delivery_score = 20.0 * (1.0 - (delivery / max_delivery)) if max_delivery > 0 else 20.0
        quality_score = 40.0 * (quality / 100.0)
        total = round(price_score + delivery_score + quality_score + pmda_bonus, 2)

        scored.append(
            {
                "supplier": supplier.get("name", "unknown"),
                "score": total,
                "is_new_supplier": bool(supplier.get("is_new_supplier", False)),
                "breakdown": {
                    "price_score": round(price_score, 2),
                    "delivery_score": round(delivery_score, 2),
                    "quality_score": round(quality_score, 2),
                    "pmda_bonus": pmda_bonus,
                },
            }
        )

    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored


def generate_procurement_report(
    device_or_drug: str,
    quantity: int,
    pmda_status: str,
    pmda_rationale: str,
    formulary_eligible: bool,
    formulary_notes: str,
    supplier_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the structured procurement recommendation report."""
    top_supplier = supplier_scores[0] if supplier_scores else None
    return {
        "device_or_drug": device_or_drug,
        "quantity": quantity,
        "pmda_status": pmda_status,
        "pmda_rationale": pmda_rationale,
        "formulary_eligible": formulary_eligible,
        "formulary_notes": formulary_notes,
        "recommended_supplier": top_supplier.get("supplier") if top_supplier else None,
        "recommended_supplier_score": top_supplier.get("score") if top_supplier else None,
        "supplier_ranking": supplier_scores,
    }


def redact_pricing_for_external(report: dict[str, Any]) -> dict[str, Any]:
    """S-3 preservation/filtering variant — strip internal price breakdown fields
    before the report leaves the trust boundary to an external copy, while
    preserving the safety-critical PMDA/formulary verdicts intact.
    """
    redacted = dict(report)
    redacted_ranking = []
    for entry in report.get("supplier_ranking", []) or []:
        e = dict(entry)
        e.pop("breakdown", None)
        redacted_ranking.append(e)
    redacted["supplier_ranking"] = redacted_ranking
    return redacted


def decide_approval(
    pmda_status: str,
    formulary_eligible: bool,
    supplier_scores: list[dict[str, Any]],
    auto_approve_threshold: float,
) -> tuple[str, bool, str]:
    """Deterministic approval routing.

    Returns (approval_status, hitl_flag, reason). approval_status is one of
    "auto_approved" | "hitl_required" | "rejected".
    """
    if pmda_status == "not_approved":
        return "rejected", False, "PMD Act approval check failed — request rejected."

    top_supplier = supplier_scores[0] if supplier_scores else None
    top_score = top_supplier.get("score", 0) if top_supplier else 0
    is_new_supplier = bool(top_supplier.get("is_new_supplier", False)) if top_supplier else True

    if pmda_status == "approved" and formulary_eligible and top_score >= auto_approve_threshold and not is_new_supplier:
        return (
            "auto_approved",
            False,
            "PMDA-approved, formulary-eligible, top supplier score above threshold — auto-approved.",
        )

    reasons = []
    if pmda_status != "approved":
        reasons.append("PMDA status unresolved")
    if not formulary_eligible:
        reasons.append("non-formulary item")
    if top_score < auto_approve_threshold:
        reasons.append("supplier score below auto-approve threshold")
    if is_new_supplier:
        reasons.append("new/unvetted supplier")
    return "hitl_required", True, "Routed to human review: " + ", ".join(reasons)
