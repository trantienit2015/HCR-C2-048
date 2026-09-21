"""Unit tests for PMDAComplianceCheckNode (inner step 1)."""

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.pmda_compliance_check_node import PMDAComplianceCheckNode

PAYLOAD = {
    "device_or_drug": "ventilator-model-x",
    "quantity": 2,
    "supplier_candidates": [{"name": "Acme", "price": 100}],
    "clinical_justification": "ICU expansion.",
}


class TestSuccess:
    def test_approved_item(self):
        out = PMDAComplianceCheckNode().execute({"user_input": json.dumps(PAYLOAD)})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["pmda_status"] == "approved"

    def test_not_approved_item(self):
        payload = dict(PAYLOAD, device_or_drug="unlisted-experimental-device")
        out = PMDAComplianceCheckNode().execute({"user_input": json.dumps(payload)})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["pmda_status"] == "not_approved"


class TestErrorEdge:
    def test_empty_state_no_raise(self):
        out = PMDAComplianceCheckNode().execute({})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_missing_device_or_drug(self):
        payload = dict(PAYLOAD)
        payload.pop("device_or_drug")
        out = PMDAComplianceCheckNode().execute({"user_input": json.dumps(payload)})
        assert out["status"] == AgentStatus.ERROR
