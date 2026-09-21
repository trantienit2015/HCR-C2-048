# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: Graph (`src/graph/graph.py`)
- **L1 Base**: AgentBaseGraph (outer) — L1 direct, no L2 inheritance
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

Cat 2 composition: outer `AgentBaseGraph` (fixed 5-node backbone) with the
`main` slot filled by `ProcurementWorkflowGraphNode` (a `GraphNode`) wrapping an
inner `BaseGraph` (`ProcurementWorkflowGraph`) that runs the 4 core business
steps. See `../reference/cat2-pattern.md` (workspace skill reference) for the
3-layer Cat 2 contract this follows.

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version/session_id/trust_level setup | — | — | InitializeNode (default) |
| pre_process (outer) | `ProcurementRequestParseNode` — parse + validate the JSON procurement request; S-2 domain scan rejects institution-confidential patient identifiers | `user_input` | `device_or_drug`, `quantity`, `supplier_candidates`, `clinical_justification`, `validated_input` | FunctionNode |
| main (outer) | `ProcurementWorkflowGraphNode` (`GraphNode`) — dispatches the inner 4-step workflow | `validated_input` | `pmda_status`, `formulary_eligible`, `supplier_scores`, `procurement_report`, `kb_version` | GraphNode wrapping inner BaseGraph |
| ↳ inner: pmda_compliance_check | `PMDAComplianceCheckNode` — PMD Act approval-status check | inner `user_input` (JSON) | `pmda_status`, `pmda_rationale` | FunctionNode |
| ↳ inner: formulary_check | `FormularyCheckNode` — hospital formulary eligibility check | `device_or_drug` | `formulary_eligible`, `formulary_notes` | FunctionNode |
| ↳ inner: supplier_score | `SupplierScoreNode` — deterministic weighted-rubric supplier scoring (LLM optional, summary-note only) | `supplier_candidates`, `pmda_status` | `supplier_scores`, `selected_supplier` | FunctionNode |
| ↳ inner: procurement_report_gen | `ProcurementReportGenNode` — assemble the structured recommendation report | all of the above | `procurement_report` | FunctionNode |
| post_process (outer) | `ApprovalRouteNode` — decide auto-approve/HITL/reject; S-3 pricing redaction for the external copy | `procurement_report`, `pmda_status`, `formulary_eligible`, `supplier_scores` | `approval_status`, `hitl_flag`, `formatted_output` | FunctionNode |
| finalize | response_metadata / total_time_ms | — | — | FinalizeNode (default) |

### Data Flow

```
START → initialize → pre_process(ProcurementRequestParseNode)
       → main(ProcurementWorkflowGraphNode)
             │ extract_input(): validated_input (JSON) → inner user_input
             ▼
         INNER: pmda_compliance_check → formulary_check → supplier_score → procurement_report_gen
             │ merge_output(): inner fields → outer state
       → post_process(ApprovalRouteNode) → finalize → END
```

No HITL `interrupt()` is used: `ApprovalRouteNode` signals routing via an
`approval_status`/`hitl_flag` output field (an async approval-queue signal
consumed downstream), not a live LangGraph pause/resume — the Engineer Review
describes routing as a decision/flag, not a synchronous human-in-the-loop pause,
so the simpler non-interrupt design is used per the framework contract guidance
(D6 `interrupt()` is only required when a live pause is actually needed).

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `device_or_drug` | `NotRequired[str]` | requested device/drug identifier | No |
| `quantity` | `NotRequired[int]` | requested unit quantity | No |
| `supplier_candidates` | `NotRequired[str]` (JSON list) | candidate suppliers {name, price, delivery_days, quality_score, is_new_supplier} | No |
| `clinical_justification` | `NotRequired[str]` | free-text clinical justification | No |
| `pmda_status` | `NotRequired[str]` | "approved" \| "not_approved" \| "unknown" | No |
| `pmda_rationale` | `NotRequired[str]` | PMD Act verdict rationale | No |
| `formulary_eligible` | `NotRequired[bool]` | hospital formulary eligibility | No |
| `formulary_notes` | `NotRequired[str]` | formulary verdict rationale | No |
| `supplier_scores` | `NotRequired[str]` (JSON list) | ranked supplier scores + breakdown | No |
| `selected_supplier` | `NotRequired[str]` | top-scoring supplier name | No |
| `procurement_report` | `NotRequired[str]` (JSON dict) | structured recommendation report | No |
| `approval_status` | `NotRequired[str]` | "auto_approved" \| "hitl_required" \| "rejected" | No |
| `hitl_flag` | `NotRequired[bool]` | routed to human-review queue | No |
| `kb_version` | `NotRequired[str]` | PMDA/formulary corpus version tag | No |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle)
- [x] ConnectionPolicy (retry/timeout strategy) — `max_retry`/`timeout_seconds` in `agent.yaml`
- [x] SecurityViolationError (fail-closed ERROR paths, no raise)
- [x] S-2: `_extra_security_gate_input()` is NOT used in this template — the domain-specific
      institution-confidential (patient-identifier) scan is implemented directly in
      `ProcurementRequestParseNode.execute()` as a fail-closed ERROR return (not a raise),
      because it is business validation gating pipeline entry, per the S-2/S-3 hook contract
      (`security-5layer-checklist.md`) — raise-able validation belongs in `execute()`, not the hook.
- [x] S-3: `ApprovalRouteNode._extra_security_gate_output()` — preservation-variant re-check that
      the redacted external report still carries the `pmda_status`/`formulary_eligible` verdicts
      (never strips safety-critical compliance verdicts, only strips internal pricing breakdown)
- [x] S-4: `emit_trace_event()` — at least one domain-specific event inside every `execute()`
      (`procurement_request_parsed`, `pmda_compliance_checked`, `formulary_eligibility_checked`,
      `suppliers_scored`, `procurement_report_generated`, `procurement_approval_routed`, plus
      `GraphNode` dispatch/completion events emitted inside `extract_input()`/`merge_output()`)

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

### Composition Pattern

- **Pattern**: GraphNode (subgraph) — `ProcurementWorkflowGraphNode` wraps the inner
  `ProcurementWorkflowGraph` (`BaseGraph`), which runs the 4 core business steps.
- **Composition target**: `src/graph/domain_workflow_graph.py::ProcurementWorkflowGraph`
- **Error propagation strategy**: `propagate` (fail-fast — inner errors surface as `SubgraphError`,
  no HITL propagation needed since this template does not use `interrupt()`)

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Fixed multi-step workflow, no autonomous think-act loop needed |
| Composition pattern | Flat (Cat 1 style) | GraphNode + inner BaseGraph | GraphNode + inner BaseGraph | Cat 2 requires 3-layer composition (`gate-composition`); 4 business steps map to inner nodes |
| HITL | D6 `interrupt()` | `approval_status`/`hitl_flag` output field | output field | Engineer Review describes routing as a decision/flag, not a synchronous pause — simpler, avoids unneeded HITL compliance surface (memory/checkpointer, PB-7 real test) |
| Supplier scoring | LLM-driven | Deterministic weighted rubric (LLM optional for free-text note only) | Deterministic rubric | Auditable, reproducible compliance decisions — not delegated to a non-deterministic LLM |
