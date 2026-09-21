# HCR-C2-048 — Framework compliance tests TC-01..TC-08.
# Reference shape: tests/unit/test_framework_compliance.py,
# adapted to this template's real architecture (Cat 2: outer pre/post + GraphNode-wrapped inner nodes).

import json
import os
import re
import typing

import pytest
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.nodes import formulary_check_node, post_process_node, pre_process_node
from src.schemas.state import State

_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
TRUST = TrustLevel.INTERNAL.value


def _src_files():
    for root, _d, files in os.walk(_SRC):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def _unwrap(annotation):
    """Strip NotRequired[...] (and Annotated[...]) to the underlying type."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is not None and args:
        return _unwrap(args[0])
    return annotation


# TC-01 - State is a flat TypedDict extending AgentState; agent-specific fields
# are primitives or JSON-serializable str (json-encoded list/dict holders).
class TestTC01StateContract:
    def test_state_is_typeddict_extending_agent_state(self):
        assert hasattr(State, "__annotations__")
        assert "user_input" in State.__annotations__
        assert set(AgentState.__annotations__).issubset(set(State.__annotations__))

    def test_added_fields_are_json_safe(self):
        added = [k for k in State.__annotations__ if k not in AgentState.__annotations__]
        assert added, "State must declare agent-specific fields"
        allowed = {"str", "bool", "int", "float"}
        for name in added:
            base = _unwrap(State.__annotations__[name])
            base_name = getattr(base, "_name", None) or getattr(base, "__name__", str(base))
            assert base_name in allowed, f"{name}: {base_name} — not a JSON-safe primitive type"

    def test_added_fields_wrapped_not_required(self):
        #  every agent-specific field must be NotRequired[...] so a
        # checkpoint that pre-dates the field, or a node reading before the
        # writer ran, never KeyErrors.
        added = [k for k in State.__annotations__ if k not in AgentState.__annotations__]
        for name in added:
            raw = State.__annotations__[name]
            assert typing.get_origin(raw) is not None, f"{name} must be wrapped in NotRequired[...]"


# TC-02 - Empty/missing input yields a fail-closed ERROR outcome, no raise.
class TestTC02Validation:
    def test_empty_input_no_raise(self):
        node = pre_process_node.ProcurementRequestParseNode()
        out = node.execute({"user_input": ""})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_missing_inner_field_no_raise(self):
        node = formulary_check_node.FormularyCheckNode()
        out = node.execute({})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]


# TC-03 - No JWT / API keys / secrets in src/; no direct os.environ reads.
class TestTC03NoCredentials:
    def test_no_credential_literals(self):
        pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []

    def test_no_os_environ_secret_reads(self):
        # S-3: secrets are read via ctx.secrets.require(), never os.environ.
        # Sole exception (a documented entry-point exception): the
        # caller-auth token in src/api/server.py, which authenticates the caller
        # BEFORE any InvocationContext exists, so ctx.secrets cannot apply. It is
        # a deployment-level caller credential, not an agent secret.
        entry_point = os.path.join("src", "api", "server.py")
        offenders = []
        for fp in _src_files():
            if os.path.normpath(fp).endswith(entry_point):
                continue
            with open(fp, encoding="utf-8") as f:
                if "os.environ" in f.read():
                    offenders.append(fp)
        assert offenders == []

    def test_entry_point_env_read_is_limited_to_the_caller_auth_token(self):
        """The entry-point exception is narrow: only INVOKE_AUTH_TOKEN may be read."""
        server = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "src",
            "api",
            "server.py",
        )
        if not os.path.exists(server):
            return
        with open(server, encoding="utf-8") as f:
            content = f.read()
        reads = re.findall(r"os\.environ(?:\.get)?[(\[]\s*[\"']([A-Z_]+)[\"']", content)
        assert set(reads) <= {"INVOKE_AUTH_TOKEN"}, f"unexpected env reads: {reads}"


# TC-04 - InvocationContext is never stored in State after invoke.
class TestTC04ContextIsolation:
    def test_no_invocationcontext_in_state_after_invoke(self):
        from src.graph.graph import Graph

        class FakeLLM:
            def complete(self, *a, **k):
                return "smoke-ok"

        agent = Graph(config={"max_retry": 1, "llm": FakeLLM()})
        agent.compile()
        ctx = InvocationContext(session_id="tc04", caller_trust_level=TrustLevel.INTERNAL, caller_id="staff-tc04")
        payload = json.dumps(
            {
                "device_or_drug": "ventilator-model-x",
                "quantity": 1,
                "supplier_candidates": [{"name": "Acme", "price": 100, "delivery_days": 5, "quality_score": 80}],
                "clinical_justification": "routine replacement",
            }
        )
        result = agent.invoke(payload, ctx=ctx)
        for v in result.values():
            assert not isinstance(v, InvocationContext)

    def test_from_state_available(self):
        assert hasattr(InvocationContext, "from_state")


# TC-05 - Domain events: every node emits >=1 domain event; no node under
# src/nodes/ ever re-emits a framework backbone lifecycle event.
class TestTC05Audit:
    def test_pre_process_emits_domain_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(pre_process_node, "emit_trace_event", lambda e, p, s: events.append(e))
        payload = json.dumps(
            {
                "device_or_drug": "ventilator-model-x",
                "quantity": 1,
                "supplier_candidates": [{"name": "Acme"}],
                "clinical_justification": "",
            }
        )
        out = pre_process_node.ProcurementRequestParseNode().execute({"user_input": payload})
        assert out["status"] == AgentStatus.SUCCESS
        assert "procurement_request_parsed" in events

    def test_post_process_emits_domain_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(post_process_node, "emit_trace_event", lambda e, p, s: events.append(e))
        report = {
            "device_or_drug": "ventilator-model-x",
            "pmda_status": "approved",
            "formulary_eligible": True,
            "supplier_ranking": [{"supplier": "Acme", "score": 90, "is_new_supplier": False, "breakdown": {}}],
        }
        out = post_process_node.ApprovalRouteNode().execute(
            {
                "procurement_report": json.dumps(report),
                "supplier_scores": json.dumps(report["supplier_ranking"]),
                "pmda_status": "approved",
                "formulary_eligible": True,
            }
        )
        assert out["status"] == AgentStatus.SUCCESS
        assert "procurement_approval_routed" in events

    def test_source_has_no_backbone_events(self):
        pat = re.compile(r'emit_trace_event\(\s*["\'](node_start|node_complete|node_error|node_skip)["\']')
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []


# TC-06 / TC-07 - S-2/S-3 gates are @final on FunctionNode (overriding raises TypeError at class def).
class TestTC0607FinalGates:
    def test_input_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadIn(FunctionNode):  # noqa: N801
                def _security_gate_input(self, state):
                    return state

    def test_output_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadOut(FunctionNode):  # noqa: N801
                def _security_gate_output(self, result):
                    return result

    def test_extra_hook_is_overridable(self):
        assert (
            post_process_node.ApprovalRouteNode._extra_security_gate_output
            is not FunctionNode._extra_security_gate_output
        )

    def test_output_gate_blocks_credentials(self):
        # The @final S-3 credential scan actually fires (not vacuous).
        node = post_process_node.ApprovalRouteNode()
        with pytest.raises(Exception):
            node._security_gate_output({"formatted_output": "token AKIAIOSFODNN7EXAMPLE leaked"})


# TC-08 - required_trust_level enforced: insufficient trust -> ERROR state, no raise.
class TestTC08TrustGate:
    def test_declared_trust_levels_valid(self):
        for cls in (
            pre_process_node.ProcurementRequestParseNode,
            formulary_check_node.FormularyCheckNode,
            post_process_node.ApprovalRouteNode,
        ):
            assert cls.required_trust_level in (TrustLevel.ANONYMOUS, TrustLevel.VERIFIED_EXTERNAL, TrustLevel.INTERNAL)

    def test_insufficient_trust_returns_error(self):
        node = pre_process_node.ProcurementRequestParseNode()
        out = node({"caller_trust_level": TrustLevel.ANONYMOUS.value, "user_input": "{}"})
        assert str(out.get("status")).lower().endswith("error")

    def test_sufficient_trust_succeeds(self):
        node = pre_process_node.ProcurementRequestParseNode()
        payload = json.dumps(
            {
                "device_or_drug": "ventilator-model-x",
                "quantity": 1,
                "supplier_candidates": [{"name": "Acme"}],
                "clinical_justification": "",
            }
        )
        out = node({"caller_trust_level": TRUST, "user_input": payload})
        assert out["status"] == AgentStatus.SUCCESS.value
