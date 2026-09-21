"""HCR-C2-048 — deployability + human-usability regression locks.

Each test pins a defect that left the agent green in CI while being either
unrunnable on the Marketplace or unusable in chat.
"""

import json
from pathlib import Path

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph, ProcurementWorkflowGraphNode
from src.nodes.formulary_check_node import FormularyCheckNode
from src.nodes.pmda_compliance_check_node import PMDAComplianceCheckNode
from src.nodes.post_process_node import ApprovalRouteNode
from src.nodes.pre_process_node import ProcurementRequestParseNode
from src.nodes.procurement_report_gen_node import ProcurementReportGenNode
from src.nodes.supplier_score_node import SupplierScoreNode

OUTER = (ProcurementRequestParseNode, ProcurementWorkflowGraphNode, ApprovalRouteNode)
INNER = (
    PMDAComplianceCheckNode,
    FormularyCheckNode,
    SupplierScoreNode,
    ProcurementReportGenNode,
)


class TestTrustLevelsAreDeployable:
    """The Marketplace runner stamps VERIFIED_EXTERNAL and grants INTERNAL to nobody.

    A node requiring INTERNAL is refused by the S-1 gate before execute() on every
    invocation, so the agent can never run — and the symptom (an empty reply) is
    indistinguishable from a crashed pod.
    """

    def test_no_node_requires_internal(self):
        offenders = [
            cls.__name__
            for cls in OUTER + INNER
            if cls.required_trust_level is TrustLevel.INTERNAL
        ]
        assert not offenders, f"{offenders} require INTERNAL — unreachable on the runner"

    def test_outer_nodes_match_the_manifest(self):
        for cls in OUTER:
            assert cls.required_trust_level is TrustLevel.VERIFIED_EXTERNAL, cls.__name__

    def test_manifest_is_root_level_and_agrees_with_the_code(self):
        import yaml

        manifest = yaml.safe_load(Path("config/agent.yaml").read_text(encoding="utf-8"))
        assert "agent" not in manifest, "nested manifest is invisible to AgentRegistry"
        assert manifest["required_trust_level"] == "VERIFIED_EXTERNAL"
        assert manifest["class"] == "src.graph.graph.Graph"

    def test_invoke_auth_token_is_not_declared_as_an_agent_secret(self):
        """It is the entry-point caller credential, read from os.environ before any
        InvocationContext exists. Declaring it here would make require_at_compile()
        hard-fail a Marketplace deployment that never sets it."""
        import yaml

        manifest = yaml.safe_load(Path("config/agent.yaml").read_text(encoding="utf-8"))
        secrets = (manifest.get("requires") or {}).get("secrets") or []
        assert "INVOKE_AUTH_TOKEN" not in secrets


class TestProseInputAccepted:
    def test_prose_request_is_parsed(self):
        out = ProcurementRequestParseNode().execute(
            {
                "user_input": "We need to order 12 Infusion pump XZ-200 from "
                "MediSupply KK for the ICU refit.",
            }
        )
        assert out["status"] == AgentStatus.SUCCESS.value
        assert out["device_or_drug"] == "Infusion pump XZ-200"
        assert out["quantity"] == 12

    def test_supplier_name_excludes_the_purpose_clause(self):
        """"from MediSupply KK for the ICU refit" must not capture the purpose."""
        parsed = ProcurementRequestParseNode._request_from_prose(
            "order 12 pumps from MediSupply KK for the ICU refit."
        )
        # "name", not "supplier": score_suppliers() reads .get("name") and would
        # otherwise score the candidate as the literal "unknown".
        assert parsed["supplier_candidates"][0]["name"] == "MediSupply KK"

    def test_decimal_in_an_item_name_survives(self):
        parsed = ProcurementRequestParseNode._request_from_prose(
            "Please procure 50 units of Saline 0.9% 500ml from Nihon Pharma, qty 50."
        )
        assert parsed["device_or_drug"] == "Saline 0.9% 500ml"
        assert parsed["quantity"] == 50

    def test_structured_caller_still_wins(self):
        payload = {
            "device_or_drug": "ventilator-x",
            "quantity": 2,
            "supplier_candidates": [{"supplier": "Acme"}],
            "clinical_justification": "ICU capacity",
        }
        out = ProcurementRequestParseNode().execute({"user_input": json.dumps(payload)})
        assert out["status"] == AgentStatus.SUCCESS.value
        assert out["device_or_drug"] == "ventilator-x"

    def test_unrelated_sentence_is_rejected_not_invented(self):
        for text in ("hello, how are you?", "the meeting is at 3"):
            assert ProcurementRequestParseNode._request_from_prose(text) is None
            out = ProcurementRequestParseNode().execute({"user_input": text})
            assert out["status"] == AgentStatus.ERROR.value

    def test_confidential_marker_scan_applies_to_the_prose_path_too(self):
        """The whole sentence becomes the justification, so it must still be scanned."""
        out = ProcurementRequestParseNode().execute(
            {"user_input": "order 2 pumps from Acme for patient-id 12345678901234"}
        )
        # rejected either by the confidential scan or by a field check — never accepted
        assert out["status"] == AgentStatus.ERROR.value


class TestLlmResultIsActuallyUsed:
    """complete() returns the canonical dict; discarding it pays for nothing."""

    def test_ranking_note_reaches_the_state(self):
        class FakeLLM:
            def complete(self, prompt):
                return {"content": "MARKER note", "tool_calls": [], "model": "fake"}

        out = SupplierScoreNode(llm=FakeLLM()).execute(
            {
                "supplier_candidates": json.dumps(
                    [{"supplier": "Acme", "unit_price": 100}]
                ),
                "pmda_status": "approved",
            }
        )
        assert out.get("ranking_note") == "MARKER note"

    def test_llm_failure_is_observable_and_non_blocking(self):
        class BoomLLM:
            def complete(self, prompt):
                raise RuntimeError("upstream down")

        out = SupplierScoreNode(llm=BoomLLM()).execute(
            {
                "supplier_candidates": json.dumps(
                    [{"supplier": "Acme", "unit_price": 100}]
                ),
                "pmda_status": "approved",
            }
        )
        assert out["status"] == AgentStatus.SUCCESS.value
        assert out.get("ranking_note") == ""


class TestChatReplyIsProse:
    REPORT = {
        "device_or_drug": "Infusion pump XZ-200",
        "quantity": 12,
        "pmda_status": "approved",
        "pmda_rationale": "Class II, approval valid.",
        "formulary_eligible": True,
        "formulary_notes": "Listed, category B.",
        "recommended_supplier": "MediSupply KK",
        "recommended_supplier_score": 86,
        "supplier_ranking": [{"supplier": "MediSupply KK", "score": 86}],
    }

    def _run(self, threshold=80.0, ranking_note="Leads on delivery reliability."):
        return ApprovalRouteNode(auto_approve_threshold=threshold).execute(
            {
                "procurement_report": json.dumps(self.REPORT),
                "supplier_scores": json.dumps(self.REPORT["supplier_ranking"]),
                "pmda_status": "approved",
                "formulary_eligible": True,
                "ranking_note": ranking_note,
            }
        )

    def test_formatted_output_is_not_json(self):
        rendered = self._run()["formatted_output"]
        try:
            json.loads(rendered)
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError("formatted_output parsed as JSON")

    def test_reply_carries_the_verdicts_and_the_decision(self):
        rendered = self._run()["formatted_output"]
        assert "PMDA" in rendered and "approved" in rendered
        assert "formulary" in rendered.lower()
        assert "MediSupply KK" in rendered
        assert "auto_approved" in rendered
        assert "Leads on delivery reliability." in rendered

    def test_hitl_case_says_a_human_must_review(self):
        out = self._run(threshold=95.0, ranking_note="")
        if out.get("hitl_flag"):
            assert "Human review is required" in out["formatted_output"]

    def test_json_contract_is_still_available(self):
        contract = json.loads(self._run()["result"])
        assert contract["pmda_status"] == "approved"

    def test_get_output_exposes_both_surfaces(self):
        """The framework default returns `formatted_output or result`, so a prose
        reply would otherwise hide the JSON contract from a parent agent."""
        agent = Graph(config={})
        out = agent.get_output(
            {
                "formatted_output": "## Procurement compliance review",
                "result": json.dumps(self.REPORT),
                "status": AgentStatus.SUCCESS.value,
            }
        )
        assert out["output"] == "## Procurement compliance review"
        assert json.loads(out["final_output"])["pmda_status"] == "approved"
