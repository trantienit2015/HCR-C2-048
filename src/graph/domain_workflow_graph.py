"""AgentCore Platform v1.0 — HCR-C2-048 inner procurement workflow (Cat 2).

Instantiated by ProcurementWorkflowGraphNode.get_subgraph(). Receives only the
JSON string user_input (seeded from the outer validated_input); the first
inner node (PMDAComplianceCheckNode) reconstructs the payload.

Pipeline: pmda_compliance_check -> formulary_check -> supplier_score -> procurement_report_gen
"""

from typing import Any
from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.formulary_check_node import FormularyCheckNode
from src.nodes.pmda_compliance_check_node import PMDAComplianceCheckNode
from src.nodes.procurement_report_gen_node import ProcurementReportGenNode
from src.nodes.supplier_score_node import SupplierScoreNode
from src.schemas.state import State


class ProcurementWorkflowGraph(BaseGraph):
    """Inner PMDA-compliance / formulary / supplier-scoring workflow."""

    @property
    def name(self) -> str:
        return "hcr_c2_048_procurement_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        pass

    def register_nodes(self) -> None:
        # No super() - BaseGraph.register_nodes() is abstract.
        llm = self.config.get("llm") if hasattr(self, "config") else None
        self._nodes["pmda_compliance_check"] = PMDAComplianceCheckNode()
        self._nodes["formulary_check"] = FormularyCheckNode()
        self._nodes["supplier_score"] = SupplierScoreNode(llm=llm)
        self._nodes["procurement_report_gen"] = ProcurementReportGenNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "pmda_compliance_check")
        self._sg.add_conditional_edges(
            "pmda_compliance_check",
            lambda s: END if self._is_error(s) else "formulary_check",
            {"formulary_check": "formulary_check", END: END},
        )
        self._sg.add_conditional_edges(
            "formulary_check",
            lambda s: END if self._is_error(s) else "supplier_score",
            {"supplier_score": "supplier_score", END: END},
        )
        self._sg.add_conditional_edges(
            "supplier_score",
            lambda s: END if self._is_error(s) else "procurement_report_gen",
            {"procurement_report_gen": "procurement_report_gen", END: END},
        )
        self._sg.add_edge("procurement_report_gen", END)

    @staticmethod
    def _is_error(state: AgentState) -> bool:
        return state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value)

    def route(self, state: AgentState) -> str:
        return END if self._is_error(state) else "procurement_report_gen"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "device_or_drug": state.get("device_or_drug"),
            "quantity": state.get("quantity"),
            "pmda_status": state.get("pmda_status"),
            "pmda_rationale": state.get("pmda_rationale"),
            "formulary_eligible": state.get("formulary_eligible"),
            "formulary_notes": state.get("formulary_notes"),
            "supplier_scores": state.get("supplier_scores"),
            "selected_supplier": state.get("selected_supplier"),
            "procurement_report": state.get("procurement_report"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
