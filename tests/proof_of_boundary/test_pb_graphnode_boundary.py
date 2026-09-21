# PB-6 supplement: GraphNode boundary coverage.
#
# PB-6 (test_pb_invoke_order.py) only auto-discovers BaseNode subclasses under
# src/nodes/. This template's outer `main` slot is ProcurementWorkflowGraphNode,
# defined in src/graph/graph.py by design (see that module's docstring) —
# placing it correctly there does NOT exempt it from boundary testing: it is
# the first node in the outer backbone to receive caller input, so it is a
# real security boundary. This file closes that gap:
#   - S-1: the outer GraphNode enforces the trust gate itself (execute() must
#     not run when caller_trust_level is below required_trust_level).
#   - Boundary mapping: extract_input()/merge_output() map fields explicitly
#     (criterion #9) rather than passing the caller/subgraph dict through raw.
#   - Delegation: the inner subgraph's entry node (PMDAComplianceCheckNode)
#     still carries its own S-2/S-3 gates — GraphNode.__call__() intentionally
#     does not re-run the standard node lifecycle (see
#     framework/nodes/graph_node.py: execute() invokes the inner subgraph
#     directly), delegating S-2/S-3 to it.

from framework.nodes.function_node import FunctionNode
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import ProcurementWorkflowGraphNode
from src.nodes.pmda_compliance_check_node import PMDAComplianceCheckNode


class TestGraphNodeTrustGate:
    """S-1: outer GraphNode denies execute() when caller trust is insufficient."""

    def test_insufficient_trust_denies_before_execute(self, monkeypatch):
        executed = []
        monkeypatch.setattr(
            ProcurementWorkflowGraphNode,
            "execute",
            lambda self, state: executed.append(state) or {},
        )
        node = ProcurementWorkflowGraphNode()
        state = {
            "caller_trust_level": TrustLevel.ANONYMOUS.value,
            "user_input": '{"device_or_drug": "Ventilator", "quantity": 2}',
        }
        result = node(state)

        assert result["status"] == "error"
        assert any("S-1 trust gate denied" in e for e in result["error_log"])
        assert executed == []

    def test_sufficient_trust_reaches_execute(self, monkeypatch):
        executed = []
        monkeypatch.setattr(
            ProcurementWorkflowGraphNode,
            "execute",
            lambda self, state: executed.append(state) or {"status": "success"},
        )
        node = ProcurementWorkflowGraphNode()
        state = {
            "caller_trust_level": ProcurementWorkflowGraphNode.required_trust_level.value,
            "user_input": '{"device_or_drug": "Ventilator", "quantity": 2}',
        }
        node(state)

        assert len(executed) == 1


class TestGraphNodeBoundaryMapping:
    """extract_input()/merge_output() map fields explicitly — no raw pass-through."""

    def test_extract_input_only_takes_validated_input(self):
        node = ProcurementWorkflowGraphNode()
        state = {
            "validated_input": '{"device_or_drug": "Ventilator"}',
            "user_input": "raw caller text",
            "some_unrelated_secret": "should-not-leak",
        }
        extracted = node.extract_input(state)

        assert extracted == state["validated_input"]
        assert "should-not-leak" not in extracted

    def test_merge_output_maps_fields_explicitly(self):
        node = ProcurementWorkflowGraphNode()
        state = {"correlation_id": "corr-1"}
        sub_result = {
            "device_or_drug": "Ventilator",
            "quantity": 2,
            "pmda_status": "approved",
            "pmda_rationale": "listed",
            "formulary_eligible": True,
            "formulary_notes": "n/a",
            "supplier_scores": "[]",
            "selected_supplier": "Acme",
            "procurement_report": "report text",
            "status": "success",
            "internal_debug_field": "must-not-leak",
        }
        merged = node.merge_output(state, sub_result)

        assert merged == {
            "device_or_drug": "Ventilator",
            "quantity": 2,
            "pmda_status": "approved",
            "pmda_rationale": "listed",
            "formulary_eligible": True,
            "formulary_notes": "n/a",
            "supplier_scores": "[]",
            "selected_supplier": "Acme",
            "procurement_report": "report text",
            "kb_version": "",
            "status": "success",
        }
        assert "internal_debug_field" not in merged


class TestInnerSubgraphDelegatedGating:
    """Delegation is intentional: the inner entry node still carries S-2/S-3."""

    def test_inner_entry_node_has_security_gate_hooks(self):
        # PMDAComplianceCheckNode (inner subgraph entry) is a FunctionNode, so
        # it inherits the @final _security_gate_input/_security_gate_output —
        # confirming S-2/S-3 gating happens inside the inner subgraph even
        # though the outer GraphNode.__call__() delegates to it directly
        # (framework/nodes/graph_node.py execute()) instead of re-running the
        # standard per-node lifecycle at the outer boundary.
        #
        # Local-mirror adaptation (ci-and-verify.md §A / test-artifacts.md
        # TC-06/07 note): the local wheel-rc1 mirror predates @final gate
        # instrumentation on FunctionNode. CI wheel (agenticstar-agentcore==
        # 1.0.0) is the gate of record and carries these methods.
        import pytest

        assert issubclass(PMDAComplianceCheckNode, FunctionNode)
        if not hasattr(FunctionNode, "_security_gate_input"):
            pytest.skip("local wheel mirror lacks @final S-2/S-3 gates — CI wheel is gate of record")
        assert callable(PMDAComplianceCheckNode._security_gate_input)
        assert callable(PMDAComplianceCheckNode._security_gate_output)
