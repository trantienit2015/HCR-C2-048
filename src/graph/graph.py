"""AgentCore Platform v1.0 — HCR-C2-048 outer graph (Cat 2).

Outer (AgentBaseGraph): initialize -> pre_process(ProcurementRequestParseNode)
-> main(ProcurementWorkflowGraphNode) -> post_process(ApprovalRouteNode) -> finalize.
Inner (BaseGraph): pmda_compliance_check -> formulary_check -> supplier_score
-> procurement_report_gen.

The GraphNode wrapper lives in THIS file (not src/nodes/) so the PB-6
invoke-order probe does not mis-assert its deliberately-delegated lifecycle
(see reference/cat2-pattern.md).
"""

from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.post_process_node import ApprovalRouteNode
from src.nodes.pre_process_node import ProcurementRequestParseNode
from src.schemas.state import State


class ProcurementWorkflowGraphNode(GraphNode):
    """Wraps the inner PMDA/formulary/supplier-scoring workflow (main slot)."""

    # S-1: outer main-slot wrapper — first node in the outer backbone receiving
    # caller input; matches agent.yaml required_trust_level + sibling outer nodes.
    # S-1: outer main slot (GraphNode wrapper) — receives caller input; matches agent.yaml required_trust_level.
    # VERIFIED_EXTERNAL not INTERNAL: the Marketplace runner stamps VERIFIED_EXTERNAL unconditionally and grants INTERNAL to nobody, so an INTERNAL requirement is refused before execute() on every invocation.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def __init__(self, llm: Any = None, pmda_db_version: str = "", top_k: int = 5):
        super().__init__()
        self._llm = llm
        self._pmda_db_version = pmda_db_version
        self._top_k = top_k

    def get_subgraph(self) -> Any:
        from src.graph.domain_workflow_graph import ProcurementWorkflowGraph

        sg = ProcurementWorkflowGraph(config=self._parent_config())
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        emit_trace_event(
            "procurement_workflow_dispatched",
            {"correlation_id": state.get("correlation_id")},
            state,
        )
        return cast(str, state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "procurement_workflow_completed",
            {"correlation_id": state.get("correlation_id"), "status": str(sub_result.get("status"))},
            state,
        )
        return {
            "device_or_drug": sub_result.get("device_or_drug"),
            "quantity": sub_result.get("quantity"),
            "pmda_status": sub_result.get("pmda_status"),
            "pmda_rationale": sub_result.get("pmda_rationale"),
            "formulary_eligible": sub_result.get("formulary_eligible"),
            "formulary_notes": sub_result.get("formulary_notes"),
            "supplier_scores": sub_result.get("supplier_scores"),
            "selected_supplier": sub_result.get("selected_supplier"),
            "procurement_report": sub_result.get("procurement_report"),
            "kb_version": self._pmda_db_version,
            "status": sub_result.get("status"),
        }

    def _parent_config(self) -> dict[str, Any]:
        return {"llm": self._llm, "top_k": self._top_k}


class Graph(AgentBaseGraph):
    """HCR-C2-048 — Medical Equipment & Pharma Procurement Compliance Agent."""

    @property
    def name(self) -> str:
        return "hcr-c2-048"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode

        llm = self.config.get("llm") if hasattr(self, "config") else None
        pmda_db_version = self.config.get("pmda_db_version", "") if hasattr(self, "config") else ""
        top_k = self.config.get("top_k", 5) if hasattr(self, "config") else 5
        auto_approve_threshold = self.config.get("auto_approve_threshold", 80.0) if hasattr(self, "config") else 80.0

        self._nodes["pre_process"] = ProcurementRequestParseNode()
        self._nodes["main"] = ProcurementWorkflowGraphNode(llm=llm, pmda_db_version=pmda_db_version, top_k=top_k)
        self._nodes["post_process"] = ApprovalRouteNode(auto_approve_threshold=auto_approve_threshold)

    # add_edges() is NOT overridden - backbone wiring belongs to the framework.

    def get_output(self, state: Any) -> dict[str, Any]:
        """Expose the machine-readable contract alongside the human reply.

        The framework default returns `output = formatted_output or result`, so
        with a prose formatted_output the JSON contract would never leave the
        agent — a parent Cat 2 agent composing this one would have nothing to
        parse. `output` stays the chat reply; `final_output` carries the
        pricing-redacted report.
        """
        return {
            "output": state.get("formatted_output") or state.get("result"),
            "final_output": state.get("result"),
            "approval_status": state.get("approval_status"),
            "hitl_flag": state.get("hitl_flag"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
