"""Agent-team tests: real agent loops and a real MCP server process (on a
throwaway database copy), driven by a scripted model instead of gpt-6-luna so
they cost nothing and are deterministic."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace

import pytest
from pydantic_ai.messages import ModelResponse, ToolReturnPart

from backend import config
from backend.audit import AuditLog, AuditLogError
from backend.guardrails import ROLE_TOOLS, check_customer_reply
from backend.team import run_ticket
from conftest import ScriptedModel, call, report

RENT_FLOW = {
    "boss": [
        [call("delegate", to_role="facilities", task="Confirm lease 1 rent and get it paid if approved.")],
        [call("update_ticket_status", ticket_id=102, status="pending_approval", note="Rent awaiting approval")],
        report("needs_human", "Rent of 2400 due 2026-09-02 is waiting for approval."),
    ],
    "facilities": [
        [call("get_rent_due_and_cash", lease_id=1)],
        [call("delegate", to_role="accounting", task="Pay lease 1 rent due 2026-09-02.",
              findings=["Lease 1 rent 2400 due 2026-09-02; checking 3400"])],
        report("needs_human", "Rent confirmed; payment waits on approval."),
    ],
    "accounting": [
        [call("prepare_payment", kind="rent_payment", ref_id=1, account="checking", reason="September rent",
              prepared_by="Pat Lee", ticket_id=999)],
        report("needs_human", "Rent payment prepared for human approval."),
    ],
}


def entries(path):
    return json.loads(path.read_text())


def db_rows(db, sql):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


async def test_delegation_chain_passes_context_and_uses_mcp(db_copy, audit_path):
    sm = ScriptedModel(RENT_FLOW)
    result = await run_ticket(102, db_path=db_copy, audit_path=audit_path, model=sm.model)

    assert result.status == "needs_human"
    assert [(d.from_role, d.to_role, d.chain, d.status) for d in result.delegations] == [
        ("boss", "facilities", ["boss", "facilities"], "done"),
        ("facilities", "accounting", ["boss", "facilities", "accounting"], "done"),
    ]
    assert result.delegations[1].report.role == "accounting"  # structured report came back
    # Every shop fact came from an MCP tool, through the server process.
    assert [(t.agent, t.tool, t.outcome) for t in result.tool_calls] == [
        ("runner", "get_ticket", "ok"),
        ("runner", "list_pending_actions", "ok"),
        ("facilities", "get_rent_due_and_cash", "ok"),
        ("accounting", "prepare_payment", "ok"),
        ("boss", "update_ticket_status", "ok"),
    ]
    assert db_rows(db_copy, "SELECT status FROM tickets WHERE id=102") == [("pending_approval",)]
    assert db_rows(db_copy, "SELECT COUNT(*) FROM payments") == [(0,)]  # agents only prepare: no money moved
    assert db_rows(db_copy, "SELECT balance FROM cash_accounts") == [(3400.0,)]
    # Amount comes from the lease, preparer and ticket from the run, not from the model's arguments.
    assert db_rows(db_copy, "SELECT kind, ref_id, amount, due_date, prepared_by, ticket_id, status FROM pending_actions") == [
        ("rent_payment", 1, 2400.0, "2026-09-02", "accounting", 102, "pending")]
    assert [(a["id"], a["amount"]) for a in result.pending_actions] == [(1, 2400.0)]
    # The delegate received the ticket context and the caller's findings.
    log = entries(audit_path)
    acct_prompt = next(e["prompt"] for e in log if e["agent"] == "accounting" and e.get("kind") == "user_prompt")
    assert '"lease_id": 1' in acct_prompt and "checking 3400" in acct_prompt
    assert "DELEGATION CHAIN: boss -> facilities -> accounting" in acct_prompt


async def test_each_role_sees_only_its_tools(db_copy, audit_path):
    sm = ScriptedModel({"boss": [[call("delegate", to_role=r, task="check")] for r in
                                 ("inventory", "accounting", "facilities", "customer_service")] + [report()]})
    await run_ticket(103, db_path=db_copy, audit_path=audit_path, model=sm.model)
    seen = sm.tools_seen
    for role, tools in ROLE_TOOLS.items():
        assert seen[role] == set(tools) | {"delegate"}, role


@pytest.mark.parametrize("tool,args", [
    ("pay_rent", {"lease_id": 1, "due_date": "2026-09-02", "account": "checking", "approved_by": "Pat Lee"}),
    ("pay_invoice", {"invoice_id": 501, "account": "checking", "approved_by": "Pat Lee"}),
    ("approve_pending_action", {"action_id": 1, "approved_by": "Pat Lee", "expected_amount": 2400}),
    ("reset_working_database", {"confirm": "RESET"}),
])
async def test_agents_cannot_execute_money_actions(db_copy, audit_path, tool, args):
    """Even if a model names a human-only tool, the call never reaches the server."""
    from types import SimpleNamespace

    from backend.team import AgentDeps, TeamRun, _guard_tool_call

    team = SimpleNamespace(tool_calls=[], ticket={"status": "open"}, log=lambda *a, **k: None)
    ctx = SimpleNamespace(deps=AgentDeps(team=team, role="accounting", chain=["boss", "accounting"]))

    async def must_not_be_called(*_a, **_k):
        raise AssertionError("reached the MCP server")

    out = await _guard_tool_call(ctx, must_not_be_called, tool, args)
    assert out["blocked"] is True and "human" in out["error"]


async def test_duplicate_prepare_reuses_pending_action(db_copy, audit_path):
    twice = {"boss": [[call("delegate", to_role="accounting", task="Prepare invoice 501")], report("needs_human")],
             "accounting": [[call("prepare_payment", kind="invoice_payment", ref_id=501, account="checking", reason="a")],
                            [call("prepare_payment", kind="invoice_payment", ref_id=501, account="checking", reason="b")],
                            report("needs_human")]}
    result = await run_ticket(101, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(twice).model)
    assert db_rows(db_copy, "SELECT COUNT(*), MAX(amount) FROM pending_actions") == [(1, 840.0)]
    assert len(result.pending_actions) == 1
    assert db_rows(db_copy, "SELECT status FROM invoices WHERE id=501") == [("open",)]


async def test_completed_report_with_pending_action_is_rejected(db_copy, audit_path):
    script = {"boss": [[call("delegate", to_role="accounting", task="Prepare invoice 501")], report("needs_human")],
              "accounting": [[call("prepare_payment", kind="invoice_payment", ref_id=501, account="checking", reason="a")],
                             report("completed", "Invoice paid!"), report("needs_human", "Prepared, awaiting approval.")]}
    result = await run_ticket(101, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(script).model)
    assert result.delegations[0].report.status == "needs_human"


async def test_cycles_and_depth_are_refused(db_copy, audit_path):
    script = {
        "boss": [[call("delegate", to_role="inventory", task="a")], report()],
        "inventory": [[call("delegate", to_role="boss", task="cycle back")],          # cycle
                      [call("delegate", to_role="inventory", task="self")],           # self
                      [call("delegate", to_role="accounting", task="b")], report()],
        "accounting": [[call("delegate", to_role="facilities", task="too deep")],     # depth 3
                       report()],
    }
    result = await run_ticket(103, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(script).model)
    got = [(d.from_role, d.to_role, d.status) for d in result.delegations]
    assert got == [("boss", "inventory", "done"), ("inventory", "boss", "refused"),
                   ("inventory", "inventory", "refused"), ("inventory", "accounting", "done"),
                   ("accounting", "facilities", "refused")]
    reasons = [d.refused_reason for d in result.delegations if d.status == "refused"]
    assert "cycle" in reasons[0] and "itself" in reasons[1] and "depth limit" in reasons[2]
    assert result.status == "completed"


async def test_total_delegations_capped(db_copy, audit_path):
    limits = replace(config.DEFAULT_LIMITS, max_delegations=2)
    script = {"boss": [[call("delegate", to_role=r, task="x")] for r in ("inventory", "facilities", "accounting")]
              + [report()]}
    result = await run_ticket(103, db_path=db_copy, audit_path=audit_path, limits=limits,
                              model=ScriptedModel(script).model)
    assert [d.status for d in result.delegations] == ["done", "done", "refused"]
    assert "delegations" in result.delegations[2].refused_reason


@pytest.mark.parametrize("field,value,expect", [
    ("max_model_requests", 2, "request_limit"),
    ("max_tool_calls", 1, "tool_calls_limit"),
    ("max_total_tokens", 200, "total_tokens_limit"),
])
async def test_usage_limits_stop_the_whole_team(db_copy, audit_path, field, value, expect):
    limits = replace(config.DEFAULT_LIMITS, **{field: value})
    sm = ScriptedModel(RENT_FLOW)
    result = await run_ticket(102, db_path=db_copy, audit_path=audit_path, limits=limits, model=sm.model)
    assert result.status == "limit_exceeded" and expect in result.error
    assert entries(audit_path)[-2]["event"] == "limit_exceeded"
    assert entries(audit_path)[-1]["event"] == "run_end"


async def test_run_duration_limit(db_copy, audit_path):
    from pydantic_ai.models.function import FunctionModel

    async def slow(messages, info):
        await asyncio.sleep(5)
        return ModelResponse(parts=[])

    limits = replace(config.DEFAULT_LIMITS, max_run_seconds=1.0)
    result = await run_ticket(102, db_path=db_copy, audit_path=audit_path, limits=limits, model=FunctionModel(slow))
    assert result.status == "limit_exceeded" and "time limit" in result.error
    assert result.seconds < 4


async def test_retries_are_capped(db_copy, audit_path):
    """A model that keeps calling a tool its role doesn't have runs out of retries."""
    script = {"boss": [[call("quote_bulk_discount", sku="CC-HOOD-NAVY", size="M", qty=20, discount_pct=5)]] * 10}
    sm = ScriptedModel(script)
    result = await run_ticket(101, db_path=db_copy, audit_path=audit_path, model=sm.model)
    assert result.status == "failed" and "retries" in result.error
    assert sm.calls.count("boss") == config.DEFAULT_LIMITS.max_retries + 1
    assert db_rows(db_copy, "SELECT status FROM invoices WHERE id=501") == [("open",)]


async def test_customer_reply_guard_forces_rewrite(db_copy, audit_path):
    leaky = report(customer_reply_draft="Hi! Our unit cost is $8 so the margin is great.")
    clean = report(customer_reply_draft="Hi! Size S is out of stock right now; we'll follow up with timing.")
    script = {"boss": [[call("delegate", to_role="customer_service", task="draft reply")], report()],
              "customer_service": [leaky, clean]}
    result = await run_ticket(101, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(script).model)
    assert result.delegations[0].report.customer_reply_draft == clean["customer_reply_draft"]
    assert any(e["event"] == "guardrail_block" for e in entries(audit_path))
    assert check_customer_reply("Your hoodie order is confirmed.") is None


async def test_audit_preserves_entries_and_redacts(db_copy, audit_path, monkeypatch):
    monkeypatch.setenv("PORTKEY_API_KEY", "pk-test-secret-123")
    existing = [{"event": "from_an_earlier_run", "keep": True}]
    audit_path.write_text(json.dumps(existing))
    script = {"boss": [[call("get_ticket", ticket_id=101)],
                       [call("delegate", to_role="customer_service", task="draft")], report()],
              "customer_service": [[call("get_ticket", ticket_id=101)],
                                   report(customer_reply_draft="Hi Tauhid Zaman, size S is restocking.")]}
    r1 = await run_ticket(101, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(script).model)
    after_one = entries(audit_path)
    r2 = await run_ticket(101, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(script).model)
    after_two = entries(audit_path)

    assert after_one[0] == existing[0] and after_two[: len(after_one)] == after_one
    assert {e.get("run_id") for e in after_two[1:]} == {r1.run_id, r2.run_id}
    events = {e["event"] for e in after_two}
    assert {"run_start", "agent_step", "mcp_tool_call", "mcp_tool_result", "delegation_start",
            "delegation_end", "agent_end", "run_end"} <= events
    usage_entries = [e for e in after_two if e.get("kind") == "model_response"]
    assert usage_entries and all("input_tokens" in e["usage"] for e in usage_entries)
    raw = audit_path.read_text()
    assert "Tauhid Zaman" not in raw and "[customer]" in raw
    assert "pk-test-secret-123" not in raw
    # The customer's name still reached Customer Service itself.
    assert r1.delegations[0].report.customer_reply_draft.startswith("Hi Tauhid Zaman")


def test_corrupt_audit_file_is_not_overwritten(audit_path):
    audit_path.write_text("{not json")
    with pytest.raises(AuditLogError):
        AuditLog(audit_path).append({"event": "x"})
    assert audit_path.read_text() == "{not json"


def test_model_is_gpt_6_luna_via_portkey(monkeypatch):
    monkeypatch.setenv("PORTKEY_API_KEY", "pk-test-secret-123")
    model = config.build_model()
    assert model.model_name == "gpt-6-luna" == config.MODEL_NAME
    assert str(model.client.base_url).rstrip("/") == "https://api.portkey.ai/v1"
    assert "pk-test-secret-123" not in repr(model)


async def test_rerun_does_not_stack_status_notes(db_copy, audit_path):
    """Running a ticket twice with nothing new must not add a second note."""
    script = {"boss": [[call("update_ticket_status", ticket_id=102, status="pending_approval",
                             note="Rent awaits approval")], report("needs_human")]}
    await run_ticket(102, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(script).model)
    reworded = {"boss": [[call("update_ticket_status", ticket_id=102, status="pending_approval",
                               note="Rent still awaits a named approver")], report("needs_human")]}
    second = await run_ticket(102, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(reworded).model)
    assert [t.outcome for t in second.tool_calls if t.tool == "update_ticket_status"] == ["duplicate_in_run"]
    notes = db_rows(db_copy, "SELECT notes FROM tickets WHERE id=102")[0][0]
    assert notes.count("[2026-08-31]") == 1


async def test_close_refused_while_action_pending_and_context_lists_actions(db_copy, audit_path):
    """A second run sees the first run's pending action, and Boss can't close until a human decides it."""
    first = {"boss": [[call("delegate", to_role="accounting", task="Prepare invoice 501")], report("needs_human")],
             "accounting": [[call("prepare_payment", kind="invoice_payment", ref_id=501, account="checking", reason="a")],
                            report("needs_human")]}
    await run_ticket(101, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(first).model)
    second = {"boss": [[call("update_ticket_status", ticket_id=101, status="closed", note="done")], report("needs_human")]}
    result = await run_ticket(101, db_path=db_copy, audit_path=audit_path, model=ScriptedModel(second).model,
                              instructions="Owner decision: test note")
    assert [t.outcome for t in result.tool_calls if t.tool == "update_ticket_status"] == ["blocked"]
    assert db_rows(db_copy, "SELECT status FROM tickets WHERE id=101") == [("open",)]
    log = entries(audit_path)
    prompt = [e["prompt"] for e in log if e.get("run_id") == result.run_id and e.get("kind") == "user_prompt"][0]
    assert "#1 invoice_payment: pay invoice 501, $840.00, status pending" in prompt
    assert "HUMAN DECISIONS FOR THIS RUN" in prompt and "Owner decision: test note" in prompt
    assert next(e for e in log if e.get("run_id") == result.run_id and e["event"] == "run_start")["human_instructions"] == \
        "Owner decision: test note"


async def test_run_label_is_stamped_on_audit_entries(db_copy, audit_path, monkeypatch):
    monkeypatch.setattr(config, "RUN_LABEL", "graded-run")
    result = await run_ticket(102, db_path=db_copy, audit_path=audit_path, model=ScriptedModel({}).model)
    mine = [e for e in entries(audit_path) if e.get("run_id") == result.run_id]
    assert mine and all(e["run_label"] == "graded-run" for e in mine)


def test_redactor_catches_first_name_of_private_customer_only():
    from backend.audit import Redactor
    r = Redactor()
    r.add_customer("Tauhid Zaman", person=True)
    r.add_customer("Yale AI Club")
    assert r("Hi Tauhid, re: Basic Hoodie Big Yale for Yale AI Club") == \
        "Hi [customer], re: Basic Hoodie Big Yale for [customer]"
