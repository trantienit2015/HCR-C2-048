# HCR-C2-048 — Integration test: full outer graph compile + invoke (Cat 2).

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


class FakeLLM:
    def complete(self, *a, **k):
        return "supplier ranking summary"


def _ctx(session="it-1"):
    return InvocationContext(session_id=session, caller_trust_level=TrustLevel.INTERNAL, caller_id="tester")


def _agent():
    a = Graph(config={"llm": FakeLLM(), "max_retry": 1, "auto_approve_threshold": 80.0, "pmda_db_version": "2026.1"})
    a.compile()
    return a


VALID_REQUEST = json.dumps(
    {
        "device_or_drug": "ventilator-model-x",
        "quantity": 2,
        "supplier_candidates": [
            # Established supplier: low price + fast delivery + high quality ->
            # weighted score comfortably clears the 80.0 auto_approve_threshold.
            {"name": "Acme Medical", "price": 1000, "delivery_days": 2, "quality_score": 95, "is_new_supplier": False},
            {"name": "NewCo Supplies", "price": 5000, "delivery_days": 10, "quality_score": 50, "is_new_supplier": True},
        ],
        "clinical_justification": "ICU capacity expansion for winter surge.",
    }
)


def _contract(result: dict) -> dict:
    """The machine-readable payload, from `final_output`.

    NOT from `output`: that is the chat reply and is prose. Parsing `output`
    as JSON would pass only while the agent is unreadable to a human, which
    is exactly the defect these tests should catch rather than enshrine.
    """
    raw = result.get("final_output")
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


def _reply(result: dict) -> str:
    """The chat reply — must be prose a person can read."""
    return result.get("output") or ""


def test_full_pipeline_auto_approve():
    result = _agent().invoke(VALID_REQUEST, ctx=_ctx())
    assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    nh = result.get("node_history") or []
    assert len(nh) >= 5, f"expected >=5 nodes, got {len(nh)}: {nh}"
    contract = _contract(result)
    assert contract.get("approval_status") == "auto_approved"
    assert contract.get("pmda_status") == "approved"
    assert contract.get("formulary_eligible") is True

    # the chat reply carries the same verdict, in words
    reply = _reply(result)
    try:
        json.loads(reply)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("output is JSON — the chat reader gets raw JSON")
    assert "auto_approved" in reply
    assert "PMDA" in reply


def test_pmda_not_approved_is_rejected():
    payload = json.loads(VALID_REQUEST)
    payload["device_or_drug"] = "unlisted-experimental-device"
    result = _agent().invoke(json.dumps(payload), ctx=_ctx("it-2"))
    assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    assert _contract(result).get("approval_status") == "rejected"
    assert "rejected" in _reply(result)


def test_empty_input_errors():
    result = _agent().invoke("", ctx=_ctx("it-3"))
    assert result["status"] in (
        AgentStatus.ERROR,
        AgentStatus.ERROR.value,
        AgentStatus.CANCELLED,
        AgentStatus.CANCELLED.value,
    )


def test_no_credentials_in_output():
    result = _agent().invoke(VALID_REQUEST, ctx=_ctx("it-4"))
    blob = json.dumps(result, default=str).lower()
    assert "sk-" not in blob and "eyj" not in blob


def test_external_report_redacts_pricing_breakdown():
    result = _agent().invoke(VALID_REQUEST, ctx=_ctx("it-5"))
    report = _contract(result)
    assert report
    for entry in report.get("supplier_ranking", []):
        assert "breakdown" not in entry
    assert report.get("pmda_status") == "approved"
    # pricing must not reappear via the human-facing surface either
    assert "breakdown" not in _reply(result)
