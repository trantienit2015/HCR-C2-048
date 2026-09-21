"""Unit tests for ApprovalRouteNode (outer post_process slot)."""

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.post_process_node import ApprovalRouteNode

REPORT = {
    "device_or_drug": "ventilator-model-x",
    "quantity": 2,
    "pmda_status": "approved",
    "pmda_rationale": "matches corpus",
    "formulary_eligible": True,
    "formulary_notes": "on formulary",
    "recommended_supplier": "Acme Medical",
    "recommended_supplier_score": 91.2,
    "supplier_ranking": [{"supplier": "Acme Medical", "score": 91.2, "is_new_supplier": False, "breakdown": {"price_score": 10}}],
}


class TestSuccess:
    def test_auto_approve(self):
        out = ApprovalRouteNode(auto_approve_threshold=80.0).execute(
            {
                "procurement_report": json.dumps(REPORT),
                "supplier_scores": json.dumps(REPORT["supplier_ranking"]),
                "pmda_status": "approved",
                "formulary_eligible": True,
            }
        )
        assert out["status"] == AgentStatus.SUCCESS
        assert out["approval_status"] == "auto_approved"
        assert out["hitl_flag"] is False
        # The JSON contract lives in `result`; `formatted_output` is the chat
        # reply and is deliberately prose. Asserting JSON there would pin the
        # very defect that makes the agent unreadable in chat.
        contract = json.loads(out["result"])
        assert "breakdown" not in contract["supplier_ranking"][0]
        assert contract["pmda_status"] == "approved"
        rendered = out["formatted_output"]
        try:
            json.loads(rendered)
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError("formatted_output is JSON — unreadable in chat")
        assert "auto_approved" in rendered
        assert "Acme Medical" in rendered

    def test_hitl_required_for_new_supplier(self):
        report = dict(REPORT)
        ranking = [dict(REPORT["supplier_ranking"][0], is_new_supplier=True)]
        out = ApprovalRouteNode(auto_approve_threshold=80.0).execute(
            {
                "procurement_report": json.dumps(report),
                "supplier_scores": json.dumps(ranking),
                "pmda_status": "approved",
                "formulary_eligible": True,
            }
        )
        assert out["approval_status"] == "hitl_required"
        assert out["hitl_flag"] is True

    def test_rejected_when_pmda_not_approved(self):
        out = ApprovalRouteNode().execute(
            {
                "procurement_report": json.dumps(REPORT),
                "supplier_scores": json.dumps(REPORT["supplier_ranking"]),
                "pmda_status": "not_approved",
                "formulary_eligible": True,
            }
        )
        assert out["approval_status"] == "rejected"


class TestErrorEdge:
    def test_missing_report_no_raise(self):
        out = ApprovalRouteNode().execute({})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]


PROSE_OK = (
    "**PMDA approval status:** approved" + chr(10) + "**Hospital formulary:** eligible"
)


class TestExtraSecurityGateOutput:
    """The hook checks the JSON contract (`result`) AND the prose surface.

    `formatted_output` is human-readable text, so it no longer parses as JSON —
    the contract to re-check is `result`. Both are derived from the same redacted
    report, and a verdict must survive into each one.
    """

    def test_hook_preserves_compliance_verdict(self):
        node = ApprovalRouteNode()
        state = {"result": json.dumps(REPORT), "formatted_output": PROSE_OK}
        out = node._extra_security_gate_output(state)
        assert out is state

    def test_hook_passes_when_only_the_contract_is_present(self):
        """A pre-render state (error path) must not be treated as suppression."""
        node = ApprovalRouteNode()
        state = {"result": json.dumps(REPORT)}
        out = node._extra_security_gate_output(state)
        assert out is state

    def test_hook_blocks_when_verdict_missing(self):
        node = ApprovalRouteNode()
        broken = dict(REPORT)
        broken.pop("pmda_status")
        state = {"result": json.dumps(broken), "formatted_output": PROSE_OK}
        out = node._extra_security_gate_output(state)
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_hook_blocks_when_the_prose_drops_the_verdict(self):
        """A verdict present in JSON but absent from the reader-facing text.

        Scanning only the JSON would let that reach the reader ungated.
        """
        node = ApprovalRouteNode()
        state = {
            "result": json.dumps(REPORT),
            "formatted_output": "Approved, nothing further to review.",
        }
        out = node._extra_security_gate_output(state)
        assert out["status"] == AgentStatus.ERROR
