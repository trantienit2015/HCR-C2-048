"""Unit tests for ProcurementRequestParseNode (outer pre_process slot)."""

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.pre_process_node import ProcurementRequestParseNode

VALID_PAYLOAD = {
    "device_or_drug": "ventilator-model-x",
    "quantity": 2,
    "supplier_candidates": [
        {"name": "Acme Medical", "price": 5000, "delivery_days": 10, "quality_score": 90, "is_new_supplier": False},
    ],
    "clinical_justification": "ICU capacity expansion for winter surge.",
}


def _node():
    return ProcurementRequestParseNode()


class TestSuccess:
    def test_valid_request_parses(self):
        out = _node().execute({"user_input": json.dumps(VALID_PAYLOAD)})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["device_or_drug"] == "ventilator-model-x"
        assert out["quantity"] == 2
        assert json.loads(out["supplier_candidates"])


class TestErrorEdge:
    def test_empty_input(self):
        out = _node().execute({"user_input": ""})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_invalid_json(self):
        out = _node().execute({"user_input": "not json"})
        assert out["status"] == AgentStatus.ERROR

    def test_missing_device_or_drug(self):
        payload = dict(VALID_PAYLOAD)
        payload["device_or_drug"] = ""
        out = _node().execute({"user_input": json.dumps(payload)})
        assert out["status"] == AgentStatus.ERROR

    def test_invalid_quantity(self):
        payload = dict(VALID_PAYLOAD)
        payload["quantity"] = -1
        out = _node().execute({"user_input": json.dumps(payload)})
        assert out["status"] == AgentStatus.ERROR

    def test_empty_supplier_candidates(self):
        payload = dict(VALID_PAYLOAD)
        payload["supplier_candidates"] = []
        out = _node().execute({"user_input": json.dumps(payload)})
        assert out["status"] == AgentStatus.ERROR

    def test_rejects_institution_confidential_marker(self):
        payload = dict(VALID_PAYLOAD)
        payload["clinical_justification"] = "Patient ID: 12345 requires urgent equipment."
        out = _node().execute({"user_input": json.dumps(payload)})
        assert out["status"] == AgentStatus.ERROR
        assert "confidential" in out["error_log"][0].lower()
