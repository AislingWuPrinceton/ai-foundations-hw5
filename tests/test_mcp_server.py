"""MCP server tests: real stdio MCP sessions against a throwaway database copy."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from fastmcp.exceptions import ToolError

from conftest import PROJECT_DIR

SERVER = PROJECT_DIR / "mcp_server" / "server.py"
ORIGINAL_TOOLS = {"check_stock_and_pricing", "get_invoice_with_vendor", "get_rent_due_and_cash"}
NEW_TOOLS = {"list_open_tickets", "get_ticket", "list_vendors", "quote_bulk_discount",
             "pay_invoice", "pay_rent", "update_ticket_status",
             "list_tickets", "get_cash_balances", "prepare_payment", "prepare_purchase", "list_pending_actions",
             "get_pending_action", "approve_pending_action", "reject_pending_action", "reset_working_database"}


def client_for(db: Path, original: Path | None = None) -> Client:
    env = {**os.environ, "CAMPUS_CUSTOMS_DB": str(db)}
    if original is not None:
        env["CAMPUS_CUSTOMS_ORIGINAL_DB"] = str(original)
    env.pop("PORTKEY_API_KEY", None)
    return Client(PythonStdioTransport(SERVER, env=env, python_cmd=sys.executable))


async def call(c: Client, name: str, **args):
    return (await c.call_tool(name, args)).data


def rows(db: Path, sql: str, *params):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql, params).fetchall()


async def test_tools_listed_and_original_tools_preserved(db_copy):
    async with client_for(db_copy) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == ORIGINAL_TOOLS | NEW_TOOLS


async def test_read_tools_match_database(db_copy):
    async with client_for(db_copy) as c:
        board = await call(c, "list_open_tickets")
        t101 = await call(c, "get_ticket", ticket_id=101)
        vendors = await call(c, "list_vendors")
        quote = await call(c, "quote_bulk_discount", sku="CC-HOOD-NAVY", size="M", qty=20, discount_pct=10)
        stock = await call(c, "check_stock_and_pricing", sku="CC-TEE-WHITE", size="S", qty_needed=1)
    assert [t["id"] for t in board["tickets"]] == [101, 102, 103]
    assert "requester" not in board["tickets"][0]  # board leaves customer names out
    assert t101["ticket"]["invoice_id"] == 501 and t101["links"] == {"inventory_row_exists": True, "invoice_exists": True}
    v1 = vendors["vendors"][0]
    assert (v1["name"], v1["lead_days"], v1["blocked_from_shipping"]) == ("Bulldog Print Co", 5, True)
    assert [i["id"] for i in v1["open_invoices"]] == [501]
    # 58 * 0.9 = 52.20 per unit, 20 units = 1044.00, margin 52.20 - 22 = 30.20
    assert (quote["unit_price"], quote["order_total"], quote["margin_per_unit"]) == (52.2, 1044.0, 30.2)
    assert quote["shortfall"] == 12 and quote["below_cost"] is False and quote["break_even_discount_pct"] == 62.1
    assert stock["qty_on_hand"] == 0 and stock["shortfall"] == 1


async def test_missing_records_and_invalid_inputs(db_copy):
    async with client_for(db_copy) as c:
        assert (await call(c, "get_ticket", ticket_id=999))["found"] is False
        assert (await call(c, "quote_bulk_discount", sku="NOPE", size="M", qty=1, discount_pct=0))["found"] is False
        assert (await call(c, "pay_invoice", invoice_id=999, account="checking", approved_by="Pat Lee"))["ok"] is False
        bad_status = await call(c, "update_ticket_status", ticket_id=101, status="done", note="x")
        assert bad_status["ok"] is False and "status must be one of" in bad_status["error"]
        for name, args in [("get_ticket", {"ticket_id": 0}),
                           ("quote_bulk_discount", {"sku": "CC-HOOD-NAVY", "size": "M", "qty": 20, "discount_pct": 150}),
                           ("pay_rent", {"lease_id": 1, "due_date": "Sept 2", "account": "checking", "approved_by": "Pat"})]:
            with pytest.raises(ToolError):
                await c.call_tool(name, args)


async def test_pay_invoice_transaction_and_duplicate_guard(db_copy):
    async with client_for(db_copy) as c:
        no_human = await call(c, "pay_invoice", invoice_id=501, account="checking", approved_by="accounting")
        assert no_human["ok"] is False and "human" in no_human["error"]
        paid = await call(c, "pay_invoice", invoice_id=501, account="checking", approved_by="Pat Lee")
        again = await call(c, "pay_invoice", invoice_id=501, account="checking", approved_by="Pat Lee")
    assert paid["ok"] and paid["balance_after"] == 2560.0  # 3400 - 840
    assert again["ok"] is False and again["duplicate"] is True
    assert rows(db_copy, "SELECT status FROM invoices WHERE id=501") == [("paid",)]
    assert rows(db_copy, "SELECT kind, ref_id, amount, account, paid_at, approved_by FROM payments") == [
        ("invoice", 501, 840.0, "checking", "2026-08-31", "Pat Lee")]
    assert rows(db_copy, "SELECT balance FROM cash_accounts") == [(2560.0,)]


async def test_negative_cash_refused_and_rolled_back(db_copy):
    with sqlite3.connect(db_copy) as conn:
        conn.execute("UPDATE cash_accounts SET balance = 100")
    async with client_for(db_copy) as c:
        res = await call(c, "pay_rent", lease_id=1, due_date="2026-09-02", account="checking", approved_by="Pat Lee")
    assert res["ok"] is False and "negative" in res["error"]
    assert rows(db_copy, "SELECT COUNT(*) FROM payments") == [(0,)]
    assert rows(db_copy, "SELECT next_due FROM leases WHERE id=1") == [("2026-09-02",)]
    assert rows(db_copy, "SELECT balance FROM cash_accounts") == [(100.0,)]


async def test_pay_rent_advances_due_date_and_blocks_repeat(db_copy):
    async with client_for(db_copy) as c:
        paid = await call(c, "pay_rent", lease_id=1, due_date="2026-09-02", account="checking", approved_by="Pat Lee")
        again = await call(c, "pay_rent", lease_id=1, due_date="2026-09-02", account="checking", approved_by="Pat Lee")
    assert paid["ok"] and paid["next_due"] == "2026-10-02" and paid["balance_after"] == 1000.0
    assert again["ok"] is False and again["duplicate"] is True
    assert rows(db_copy, "SELECT COUNT(*) FROM payments WHERE kind='rent'") == [(1,)]


async def test_update_ticket_status_is_idempotent(db_copy):
    async with client_for(db_copy) as c:
        first = await call(c, "update_ticket_status", ticket_id=102, status="pending_approval", note="Rent awaiting approval")
        second = await call(c, "update_ticket_status", ticket_id=102, status="pending_approval", note="Rent awaiting approval")
    assert first["changed"] is True and second["changed"] is False
    status, notes = rows(db_copy, "SELECT status, notes FROM tickets WHERE id=102")[0]
    assert status == "pending_approval" and notes.count("Rent awaiting approval") == 1


async def test_note_date_prefix_not_doubled(db_copy):
    async with client_for(db_copy) as c:
        res = await call(c, "update_ticket_status", ticket_id=103, status="pending_approval",
                         note="[2026-08-31] Discount awaits a human decision.")
    assert res["notes"].endswith("\n[2026-08-31] Discount awaits a human decision.")


async def test_prepare_then_approve_invoice_executes_once(db_copy):
    async with client_for(db_copy) as c:
        prep = await call(c, "prepare_payment", kind="invoice_payment", ref_id=501, account="checking",
                          reason="Unblock vendor", ticket_id=101, prepared_by="accounting")
        aid = prep["action"]["id"]
        assert prep["action"]["amount"] == 840.0 and prep["cash_covers_now"] is True
        assert rows(db_copy, "SELECT COUNT(*) FROM payments") == [(0,)]  # preparing moves no money
        agent = await call(c, "approve_pending_action", action_id=aid, approved_by="Accounting", expected_amount=840)
        wrong = await call(c, "approve_pending_action", action_id=aid, approved_by="Pat Lee", expected_amount=800)
        ok = await call(c, "approve_pending_action", action_id=aid, approved_by="Pat Lee", expected_amount=840)
        again = await call(c, "approve_pending_action", action_id=aid, approved_by="Pat Lee", expected_amount=840)
        cash = await call(c, "get_cash_balances")
    assert agent["ok"] is False and "agent" in agent["error"]
    assert wrong["ok"] is False and "Amount changed" in wrong["error"]
    assert ok["ok"] and ok["result"]["balance_after"] == 2560.0
    assert again["ok"] is False and again["duplicate"] is True
    assert cash["accounts"] == [{"name": "checking", "balance": 2560.0, "date": "2026-08-31"}]
    assert rows(db_copy, "SELECT status, decided_by FROM pending_actions") == [("executed", "Pat Lee")]
    assert rows(db_copy, "SELECT COUNT(*) FROM payments") == [(1,)]


async def test_approval_revalidates_records_and_cash(db_copy):
    async with client_for(db_copy) as c:
        rent = (await call(c, "prepare_payment", kind="rent_payment", ref_id=1, account="checking", reason="r"))["action"]
        inv = (await call(c, "prepare_payment", kind="invoice_payment", ref_id=501, account="checking", reason="i"))["action"]
        with sqlite3.connect(db_copy) as conn:  # cash drops after the action was prepared
            conn.execute("UPDATE cash_accounts SET balance = 1000")
        low = await call(c, "approve_pending_action", action_id=rent["id"], approved_by="Pat Lee", expected_amount=2400)
        await call(c, "pay_invoice", invoice_id=501, account="checking", approved_by="Pat Lee")  # paid elsewhere
        stale = await call(c, "approve_pending_action", action_id=inv["id"], approved_by="Pat Lee", expected_amount=840)
    assert low["ok"] is False and "negative" in low["error"]
    assert stale["ok"] is False and "not open" in stale["error"]
    assert rows(db_copy, "SELECT status FROM pending_actions ORDER BY id") == [("pending",), ("pending",)]
    assert rows(db_copy, "SELECT next_due FROM leases") == [("2026-09-02",)]


async def test_purchase_blocked_until_vendor_invoice_paid(db_copy):
    async with client_for(db_copy) as c:
        prep = await call(c, "prepare_purchase", vendor_id=1, sku="CC-HOOD-NAVY", size="M", qty=12, reason="shortfall")
        dup = await call(c, "prepare_purchase", vendor_id=1, sku="CC-HOOD-NAVY", size="M", qty=12, reason="again")
        aid = prep["action"]["id"]
        blocked = await call(c, "approve_pending_action", action_id=aid, approved_by="Pat Lee", expected_amount=264)
        await call(c, "pay_invoice", invoice_id=501, account="checking", approved_by="Pat Lee")
        ok = await call(c, "approve_pending_action", action_id=aid, approved_by="Pat Lee", expected_amount=264)
    assert prep["action"]["amount"] == 264.0 and prep["vendor_blocked_by_open_invoices"] == [501]  # 12 x $22
    assert dup["already_pending"] is True and dup["action"]["id"] == aid
    assert blocked["ok"] is False and "will not ship" in blocked["error"]
    assert ok["ok"] and ok["result"]["purchase_order_id"] == 1
    assert rows(db_copy, "SELECT sku, size, qty, total, status FROM purchase_orders") == [
        ("CC-HOOD-NAVY", "M", 12, 264.0, "ordered")]
    assert rows(db_copy, "SELECT qty FROM inventory WHERE sku='CC-HOOD-NAVY' AND size='M'") == [(8,)]


async def test_reject_and_reset(db_copy, tmp_path):
    original = tmp_path / "original.db"
    original.write_bytes(db_copy.read_bytes())
    before = original.read_bytes()
    async with client_for(db_copy, original) as c:
        aid = (await call(c, "prepare_payment", kind="rent_payment", ref_id=1, account="checking", reason="r"))["action"]["id"]
        rej = await call(c, "reject_pending_action", action_id=aid, rejected_by="Pat Lee", note="not yet")
        after_rej = await call(c, "approve_pending_action", action_id=aid, approved_by="Pat Lee", expected_amount=2400)
        await call(c, "update_ticket_status", ticket_id=101, status="closed", note="test")
        bad = await call(c, "reset_working_database", confirm="yes")
        reset = await call(c, "reset_working_database", confirm="RESET")
        pending = await call(c, "list_pending_actions")
    assert rej["ok"] and after_rej["ok"] is False
    assert bad["ok"] is False
    assert reset["ok"] and reset["ticket_statuses"] == {"101": "open", "102": "open", "103": "open"}
    assert "pending_actions" not in reset["tables"] and pending == {"count": 0, "actions": []}
    assert original.read_bytes() == before  # the original is only read
