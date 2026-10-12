"""HTTP route tests for backend/main.py.

Each test builds the app on throwaway copies of the working database, the
original database, and the audit file, and drives agent runs with a scripted
model, so nothing in data/ or output/ is touched and no tokens are spent."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from backend.main import create_app
from conftest import PRISTINE_DB, ScriptedModel, call, report

RENT_PREP = {
    "boss": [[call("delegate", to_role="accounting", task="Prepare lease 1 rent")], report("needs_human")],
    "accounting": [[call("prepare_payment", kind="rent_payment", ref_id=1, account="checking", reason="Rent")],
                   report("needs_human", "Rent prepared for approval.")],
}


@pytest.fixture
def paths(tmp_path, db_copy, audit_path):
    original = tmp_path / "original.db"
    original.write_bytes(PRISTINE_DB.read_bytes())
    audit_path.write_text(json.dumps([{"event": "older_history", "keep": True}]))
    return {"db_path": db_copy, "original_db_path": original, "audit_path": audit_path}


def make_client(paths, model_factory=None) -> TestClient:
    return TestClient(create_app(**paths, model_factory=model_factory))


def wait_for_run(client: TestClient, run_id: str, timeout: float = 20) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def slow_model(seconds: float = 1.5) -> FunctionModel:
    async def respond(messages, info):
        await asyncio.sleep(seconds)
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=report("needs_human"))])
    return FunctionModel(respond)


def db_rows(db, sql):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def run_and_prepare_rent(client) -> dict:
    run = client.post("/api/tickets/102/run").json()
    wait_for_run(client, run["run_id"])
    return client.get("/api/pending-actions", params={"status": "pending"}).json()["actions"][0]


def test_health_tickets_and_cash(paths):
    with make_client(paths) as client:
        health = client.get("/api/health").json()
        tickets = client.get("/api/tickets").json()["tickets"]
        cash = client.get("/api/cash").json()
    assert health["ok"] and health["model"] == "gpt-6-luna" and health["mcp_tools"] == 19
    assert [(t["id"], t["status"], t["resolved"]) for t in tickets] == [
        (101, "open", False), (102, "open", False), (103, "open", False)]
    assert "requester" not in tickets[0]
    assert cash == {"account": "checking", "balance": 3400.0, "date": "2026-08-31"}


def test_run_in_background_and_block_overlap(paths):
    with make_client(paths, model_factory=lambda: slow_model()) as client:
        started = client.post("/api/tickets/102/run")
        assert started.status_code == 202 and started.json()["status"] == "running"
        run_id = started.json()["run_id"]
        overlap = client.post("/api/tickets/102/run")
        assert overlap.status_code == 409 and overlap.json()["detail"]["run_id"] == run_id
        assert client.get("/api/tickets").json()["tickets"][1]["active_run_id"] == run_id
        assert client.post("/api/reset", json={"confirm": "RESET"}).status_code == 409  # run in progress
        assert client.post("/api/tickets/999/run").status_code == 404
        done = wait_for_run(client, run_id)
    assert done["status"] == "needs_human" and done["result"]["run_id"] == run_id
    assert done["finished_at"] is not None


def test_events_support_incremental_cursor(paths):
    with make_client(paths, model_factory=lambda: ScriptedModel(RENT_PREP).model) as client:
        first = client.get("/api/events").json()
        assert first["events"] == [{"event_id": 0, "event": "older_history", "keep": True}]
        run_id = client.post("/api/tickets/102/run").json()["run_id"]
        wait_for_run(client, run_id)
        new = client.get("/api/events", params={"after": first["next_cursor"]}).json()
        nothing = client.get("/api/events", params={"after": new["next_cursor"]}).json()
        page = client.get("/api/events", params={"after": -1, "limit": 3, "run_id": run_id}).json()
    ids = [e["event_id"] for e in new["events"]]
    assert ids == list(range(1, new["total"])) and new["next_cursor"] == new["total"] - 1
    kinds = {e["event"] for e in new["events"]}
    assert {"run_start", "agent_step", "delegation_start", "mcp_tool_call", "mcp_tool_result",
            "pending_action_prepared", "run_end"} <= kinds
    assert any(e.get("kind") == "model_response" for e in new["events"])  # agent messages
    assert nothing["events"] == []
    assert len(page["events"]) == 3 and all(e["run_id"] == run_id for e in page["events"])


def test_approval_flow_and_financial_safeguards(paths):
    db = paths["db_path"]
    with make_client(paths, model_factory=lambda: ScriptedModel(RENT_PREP).model) as client:
        action = run_and_prepare_rent(client)
        assert (action["kind"], action["amount"], action["prepared_by"], action["ticket_id"]) == (
            "rent_payment", 2400.0, "accounting", 102)
        assert db_rows(db, "SELECT balance FROM cash_accounts") == [(3400.0,)]  # the agent changed no cash
        url = f"/api/pending-actions/{action['id']}/approve"

        assert client.post(url, json={"approved_by": "Pat Lee"}).status_code == 422
        mismatch = client.post(url, json={"approved_by": "Pat Lee", "confirm_amount": 240})
        agent = client.post(url, json={"approved_by": "accounting", "confirm_amount": 2400})
        assert mismatch.status_code == 409 and "does not match" in mismatch.json()["detail"]
        assert agent.status_code == 409 and "agent" in agent.json()["detail"]
        assert db_rows(db, "SELECT COUNT(*) FROM payments") == [(0,)]

        ok = client.post(url, json={"approved_by": "Pat Lee", "confirm_amount": 2400})
        assert ok.status_code == 200
        body = ok.json()
        assert body["action"]["status"] == "executed" and body["action"]["decided_by"] == "Pat Lee"
        assert body["checking_balance"] == 1000.0 and body["result"]["next_due"] == "2026-10-02"
        again = client.post(url, json={"approved_by": "Pat Lee", "confirm_amount": 2400})
        assert again.status_code == 409
        assert client.get("/api/cash").json()["balance"] == 1000.0
        assert client.post("/api/pending-actions/999/approve",
                           json={"approved_by": "Pat Lee", "confirm_amount": 1}).status_code == 404

    assert db_rows(db, "SELECT kind, amount, approved_by FROM payments") == [("rent", 2400.0, "Pat Lee")]
    audit = json.loads(paths["audit_path"].read_text())
    human = [e["event"] for e in audit if e.get("agent") == "human"]
    assert human == ["approval_requested", "approval_refused", "approval_requested", "approval_executed"]
    executed = next(e for e in audit if e["event"] == "approval_executed")
    assert executed["result"]["balance_before"] == 3400.0 and executed["checking_balance_after"] == 1000.0


def test_reject_blocks_later_approval(paths):
    with make_client(paths, model_factory=lambda: ScriptedModel(RENT_PREP).model) as client:
        action = run_and_prepare_rent(client)
        rej = client.post(f"/api/pending-actions/{action['id']}/reject", json={"rejected_by": "Pat Lee", "note": "wait"})
        late = client.post(f"/api/pending-actions/{action['id']}/approve",
                           json={"approved_by": "Pat Lee", "confirm_amount": 2400})
    assert rej.status_code == 200 and rej.json()["action"]["status"] == "rejected"
    assert late.status_code == 409
    assert db_rows(paths["db_path"], "SELECT COUNT(*) FROM payments") == [(0,)]


def test_reset_restores_data_and_keeps_history(paths):
    original_bytes = paths["original_db_path"].read_bytes()
    with make_client(paths, model_factory=lambda: ScriptedModel(RENT_PREP).model) as client:
        action = run_and_prepare_rent(client)
        client.post(f"/api/pending-actions/{action['id']}/approve", json={"approved_by": "Pat Lee", "confirm_amount": 2400})
        assert client.get("/api/cash").json()["balance"] == 1000.0
        history = json.loads(paths["audit_path"].read_text())

        assert client.post("/api/reset", json={"confirm": "yes"}).status_code == 422
        reset = client.post("/api/reset", json={"confirm": "RESET"})
        assert reset.status_code == 200
        assert reset.json() == {"ok": True, "cleared_pending_actions": 0, "cleared_runs": 1, "checking_balance": 3400.0,
                                "ticket_statuses": {"101": "open", "102": "open", "103": "open"}}
        assert client.get("/api/cash").json()["balance"] == 3400.0
        assert client.get("/api/pending-actions").json()["actions"] == []
        assert client.get("/api/runs").json()["runs"] == []

    after = json.loads(paths["audit_path"].read_text())
    assert after[: len(history)] == history and after[-1]["event"] == "database_reset"
    assert paths["original_db_path"].read_bytes() == original_bytes
    assert db_rows(paths["db_path"], "SELECT COUNT(*) FROM payments") == [(0,)]


def test_cors_allows_local_dashboard(paths):
    with make_client(paths) as client:
        ok = client.options("/api/tickets", headers={"Origin": "http://localhost:5173",
                                                     "Access-Control-Request-Method": "GET"})
        other = client.options("/api/tickets", headers={"Origin": "http://evil.example",
                                                        "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in other.headers
