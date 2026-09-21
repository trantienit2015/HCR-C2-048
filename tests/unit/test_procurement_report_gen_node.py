"""Unit tests for ProcurementReportGenNode (inner step 4)."""

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.procurement_report_gen_node import ProcurementReportGenNode

SCORES = [{"supplier": "Acme Medical", "score": 91.2, "is_new_supplier": False, "breakdown": {}}]


class TestSuccess:
    def test_generates_report(self):
        out = ProcurementReportGenNode().execute(
            {
                "device_or_drug": "ventilator-model-x",
                "quantity": 2,
                "pmda_status": "approved",
                "pmda_rationale": "matches corpus",
                "formulary_eligible": True,
                "formulary_notes": "on formulary",
                "supplier_scores": json.dumps(SCORES),
            }
        )
        assert out["status"] == AgentStatus.SUCCESS
        report = json.loads(out["procurement_report"])
        assert report["recommended_supplier"] == "Acme Medical"
        assert report["pmda_status"] == "approved"


class TestErrorEdge:
    def test_missing_upstream_fields_no_raise(self):
        out = ProcurementReportGenNode().execute({})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]
