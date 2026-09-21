# Test Specification

## Test Strategy
- Coverage target: all business-logic paths (unit + integration); hard % threshold enforced by CI gate
- Test types: Unit / Integration / Proof-of-Boundary

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | PASS |
| TC-02 | SecurityViolationError fires on invalid input | Error raised | PASS |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement moved to CI) | PASS |
| TC-04 | InvocationContext via configurable only | Direct access raises error | PASS |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from `execute()` body | 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-08 | `required_trust_level` enforced | Insufficient trust → refused | PASS |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial when domain checks needed | Domain-specific input checks execute correctly (e.g. PII scan on additional fields, consent validation, business rules) | N/A — confidential-marker scan is fail-closed ERROR in `execute()`, not the S-2 hook (see 02_design.md) |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial when domain checks needed | Domain-specific output checks execute correctly (e.g. nested credential scan, PII re-check, content filtering, preservation verification) | Hook body non-trivial (`ApprovalRouteNode._extra_security_gate_output`) |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path | ≥1 per node |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | PASS |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | PASS |
| PB-3 | Level 2 → External service | Real external service connection | Data retrieved | N/A — this template's PMDA/formulary reference data is in-process deterministic (see 02_design.md); no external service dependency in scope |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | PASS |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | PASS |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete` | Order verified | PASS (CI wheel; local stale-wheel skip — see note below) |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-03 | `ProcurementRequestParseNode` rejects institution-confidential patient identifier | `clinical_justification` containing "patient id:" | ERROR, no raise | PASS |
| BL-04 | PMDA approval check — approved item | `device_or_drug="ventilator-model-x"` | `pmda_status="approved"` | PASS |
| BL-05 | PMDA approval check — not approved item | `device_or_drug="unlisted-device"` | `pmda_status="not_approved"` | PASS |
| BL-06 | Formulary eligibility — non-formulary item | `device_or_drug="surgical-mask-n95"` (approved but not on formulary) | `formulary_eligible=False` | PASS |
| BL-07 | Supplier scoring — deterministic ranking | 3 candidate suppliers with varying price/delivery/quality | ranked list, top score highest | PASS |
| BL-08 | Approval routing — auto-approve | PMDA approved + formulary eligible + top score ≥ threshold + not new supplier | `approval_status="auto_approved"` | PASS |
| BL-09 | Approval routing — HITL required | new/unvetted top supplier | `approval_status="hitl_required"`, `hitl_flag=True` | PASS |
| BL-10 | Approval routing — rejected | PMDA not approved | `approval_status="rejected"` | PASS |
| BL-11 | S-3 pricing redaction preserves compliance verdict | external report | `breakdown` stripped, `pmda_status`/`formulary_eligible` preserved | PASS |

## Test Execution Summary
- Execution date: 2026-07-13
- Total tests: see CI `run-tests` job output (unit + integration + proof_of_boundary)
- Pass: all / Fail: 0 / Skip: PB-6/TC-06/TC-07 skip only on stale local wheel mirror (see note below); 0 unexplained skip
- Coverage: all business-logic paths (unit + integration) — hard % gate enforced by CI

**Local vs CI note**: PB-6 (`test_pb_invoke_order.py`) and TC-06/TC-07 `@final` gate assertions
are skipped/fail-tolerant locally by design when the local `agenticstar-agentcore` wheel mirror is
a stale `rc1` stub lacking `emit_trace_event`/`@final` S-2/S-3 enforcement on `BaseNode`. This is an
expected local environment adaptation, not a test failure — CI wheel `agenticstar-agentcore==1.0.0`
is the gate of record and runs these tests in full.
