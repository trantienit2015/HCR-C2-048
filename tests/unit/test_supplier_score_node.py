"""Unit tests for SupplierScoreNode (inner step 3)."""

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.supplier_score_node import SupplierScoreNode

CANDIDATES = [
    {"name": "Acme Medical", "price": 5000, "delivery_days": 10, "quality_score": 90, "is_new_supplier": False},
    {"name": "NewCo Supplies", "price": 3000, "delivery_days": 5, "quality_score": 60, "is_new_supplier": True},
]


class TestSuccess:
    def test_scores_and_ranks_suppliers(self):
        out = SupplierScoreNode().execute(
            {"supplier_candidates": json.dumps(CANDIDATES), "pmda_status": "approved"}
        )
        assert out["status"] == AgentStatus.SUCCESS
        scores = json.loads(out["supplier_scores"])
        assert len(scores) == 2
        assert scores[0]["score"] >= scores[1]["score"]
        assert out["selected_supplier"] == scores[0]["supplier"]

    def test_optional_llm_is_best_effort_and_non_blocking(self):
        class FakeLLM:
            def complete(self, *a, **k):
                raise RuntimeError("llm unavailable")

        out = SupplierScoreNode(llm=FakeLLM()).execute(
            {"supplier_candidates": json.dumps(CANDIDATES), "pmda_status": "approved"}
        )
        assert out["status"] == AgentStatus.SUCCESS


class TestErrorEdge:
    def test_missing_candidates_no_raise(self):
        out = SupplierScoreNode().execute({})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]
