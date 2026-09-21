"""Unit tests for FormularyCheckNode (inner step 2)."""

from framework.schemas.agent_status import AgentStatus

from src.nodes.formulary_check_node import FormularyCheckNode


class TestSuccess:
    def test_on_formulary(self):
        out = FormularyCheckNode().execute({"device_or_drug": "ventilator-model-x"})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["formulary_eligible"] is True

    def test_not_on_formulary(self):
        out = FormularyCheckNode().execute({"device_or_drug": "surgical-mask-n95"})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["formulary_eligible"] is False


class TestErrorEdge:
    def test_missing_device_or_drug_no_raise(self):
        out = FormularyCheckNode().execute({})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]
