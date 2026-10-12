"""Campus Customs MCP server.

Exposes tools over data/campus_customs_new.db so the agent team can look up the
facts behind the open tickets (101, 102, 103) and carry out the few approved
actions they need. Lookup tools open the database read-only; the three write
tools (pay_invoice, pay_rent, update_ticket_status) each run in one SQLite
transaction and refuse duplicate actions.
"""

import calendar
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

# Resolve the DB relative to this file, so the server works from any launch directory.
# CAMPUS_CUSTOMS_DB lets tests point the server at a throwaway copy instead.
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db"
DB_PATH = Path(os.environ.get("CAMPUS_CUSTOMS_DB") or DEFAULT_DB_PATH).resolve()
# The untouched original that reset_working_database copies from (CAMPUS_CUSTOMS_ORIGINAL_DB for tests).
DEFAULT_ORIGINAL_DB_PATH = DEFAULT_DB_PATH.with_name("campus_customs.db")
ORIGINAL_DB_PATH = Path(os.environ.get("CAMPUS_CUSTOMS_ORIGINAL_DB") or DEFAULT_ORIGINAL_DB_PATH).resolve()

# Ticket statuses this server will write. The data only shows "open"; the other two
# are the minimum the agents need to park a ticket on a human or close it.
TICKET_STATUSES = ("open", "pending_approval", "closed")

# Names an approver may not have: a payment's approved_by must be a human, not an agent.
AGENT_NAMES = {"boss", "inventory", "accounting", "facilities", "customer service",
               "customer_service", "agent", "ai", "assistant", "system"}

mcp = FastMCP("Campus Customs")


def _connect(write: bool = False) -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Working database not found at {DB_PATH}")
    # Lookups open read-only so they can never change records.
    mode = "rw" if write else "ro"
    conn = sqlite3.connect(f"file:{DB_PATH}?mode={mode}", uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _today(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    return row["date_today"]


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


@mcp.tool
def check_stock_and_pricing(sku: str, size: str, qty_needed: int = 1) -> dict:
    """Check on-hand stock for one SKU and size, compare it with the quantity a
    ticket needs, and return the item's unit cost, list price, and margin.

    Reads tables: inventory, pricing.
    Use for customer orders (ticket 101) and bulk/discount requests (ticket 103).
    """
    with _connect() as conn:
        item = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            (sku, size),
        ).fetchone()
        if item is None:
            sizes = [r["size"] for r in conn.execute(
                "SELECT size FROM inventory WHERE sku = ? ORDER BY size", (sku,))]
            return {
                "found": False,
                "error": f"No inventory row for sku={sku!r}, size={size!r}.",
                "sizes_on_record_for_sku": sizes,
            }
        price = conn.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()

    shortfall = max(qty_needed - item["qty"], 0)
    result = {
        "found": True,
        "sku": item["sku"],
        "name": item["name"],
        "size": item["size"],
        "location": item["location"],
        "qty_on_hand": item["qty"],
        "qty_needed": qty_needed,
        "shortfall": shortfall,
        "can_fill_from_stock": shortfall == 0,
    }
    if price is None:
        result["pricing"] = None
        result["pricing_note"] = f"No pricing row for sku={sku!r}."
    else:
        margin = price["list_price"] - price["unit_cost"]
        result["pricing"] = {
            "unit_cost": price["unit_cost"],
            "list_price": price["list_price"],
            "margin_per_unit": round(margin, 2),
            "margin_pct_of_list": round(margin / price["list_price"] * 100, 1),
        }
    return result


@mcp.tool
def get_invoice_with_vendor(invoice_id: int) -> dict:
    """Look up one vendor invoice, whether it is overdue as of the shop's
    desk.date_today, and the vendor it belongs to (specialty, lead days, and
    all of that vendor's open invoices, which block new shipments).

    Reads tables: invoices, vendors, desk.
    Use for ticket 101, whose restock is tied to invoice 501.
    """
    with _connect() as conn:
        today = _today(conn)
        inv = conn.execute(
            "SELECT id, vendor_id, amount, due_date, status, description FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
        if inv is None:
            return {"found": False, "error": f"No invoice with id={invoice_id}."}
        vendor = conn.execute(
            "SELECT id, name, specialty, lead_days FROM vendors WHERE id = ?",
            (inv["vendor_id"],),
        ).fetchone()
        open_invoices = [dict(r) for r in conn.execute(
            "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY due_date",
            (inv["vendor_id"],),
        )]

    days_past_due = _days_between(inv["due_date"], today)
    return {
        "found": True,
        "today": today,
        "invoice": {
            **dict(inv),
            "is_open": inv["status"] == "open",
            "is_overdue": inv["status"] == "open" and days_past_due > 0,
            "days_past_due": max(days_past_due, 0),
        },
        "vendor": dict(vendor) if vendor else None,
        "vendor_open_invoices": open_invoices,
        "vendor_blocked_from_shipping": len(open_invoices) > 0,
    }


@mcp.tool
def get_rent_due_and_cash(lease_id: int) -> dict:
    """Look up a lease's monthly rent and next due date, how many days remain
    until it is due as of desk.date_today, and the current cash account
    balances, including whether each account can cover the rent.

    Reads tables: leases, desk, cash_accounts.
    Use for ticket 102 (rent notice for lease 1).
    """
    with _connect() as conn:
        today = _today(conn)
        lease = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
        if lease is None:
            return {"found": False, "error": f"No lease with id={lease_id}."}
        accounts = conn.execute(
            "SELECT name, balance, date FROM cash_accounts ORDER BY name"
        ).fetchall()

    days_until_due = _days_between(today, lease["next_due"])
    return {
        "found": True,
        "today": today,
        "lease": dict(lease),
        "days_until_due": days_until_due,
        "is_overdue": days_until_due < 0,
        "cash_accounts": [
            {
                **dict(a),
                "can_cover_rent": a["balance"] >= lease["monthly_rent"],
                "balance_after_rent": round(a["balance"] - lease["monthly_rent"], 2),
            }
            for a in accounts
        ],
    }



def _add_one_month(day: str) -> str:
    d = date.fromisoformat(day)
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return d.replace(year=year, month=month,
                     day=min(d.day, calendar.monthrange(year, month)[1])).isoformat()


def _check_approver(approved_by: str) -> str | None:
    name = approved_by.strip()
    if not name:
        return "approved_by is required: payments need a named human approver."
    if name.lower() in AGENT_NAMES:
        return f"approved_by={approved_by!r} is an agent/system name; a human must approve payments."
    return None


def _debit(conn: sqlite3.Connection, account: str, amount: float, today: str) -> dict:
    """Take amount out of a cash account inside the caller's transaction.

    Returns {"error": ...} (and changes nothing) if the account is missing or the
    balance would go negative.
    """
    row = conn.execute("SELECT name, balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()
    if row is None:
        names = [r["name"] for r in conn.execute("SELECT name FROM cash_accounts ORDER BY name")]
        return {"error": f"No cash account named {account!r}.", "accounts_on_record": names}
    after = round(row["balance"] - amount, 2)
    if after < 0:
        return {"error": f"Refused: paying {amount:.2f} from {account!r} (balance {row['balance']:.2f}) "
                         f"would leave a negative balance ({after:.2f})."}
    conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?", (after, today, account))
    return {"balance_before": row["balance"], "balance_after": after}


@mcp.tool
def list_open_tickets() -> dict:
    """List every ticket whose status is not 'closed', oldest first, with its type,
    subject, and linked record IDs. Requester names and notes are left out; call
    get_ticket for one ticket's full details.

    Reads tables: tickets.
    Use to see the work board (tickets 101, 102, 103) before routing work.
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, type, subject, sku, size, qty, lease_id, invoice_id, status, created_at "
            "FROM tickets WHERE status != 'closed' ORDER BY created_at")]
    return {"count": len(rows), "tickets": rows}


@mcp.tool
def get_ticket(ticket_id: Annotated[int, Field(ge=1)]) -> dict:
    """Return one ticket's full row plus whether each record it points to exists:
    the inventory row for its (sku, size), the lease, and the invoice.

    Reads tables: tickets, inventory, leases, invoices.
    Use first on any ticket (101, 102, 103) to get the request and its links.
    """
    with _connect() as conn:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"found": False, "error": f"No ticket with id={ticket_id}."}
        links = {}
        if t["sku"]:
            links["inventory_row_exists"] = conn.execute(
                "SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (t["sku"], t["size"])).fetchone() is not None
        if t["lease_id"] is not None:
            links["lease_exists"] = conn.execute(
                "SELECT 1 FROM leases WHERE id = ?", (t["lease_id"],)).fetchone() is not None
        if t["invoice_id"] is not None:
            links["invoice_exists"] = conn.execute(
                "SELECT 1 FROM invoices WHERE id = ?", (t["invoice_id"],)).fetchone() is not None
    return {"found": True, "ticket": dict(t), "links": links}


@mcp.tool
def list_vendors() -> dict:
    """List every vendor with its specialty, lead days, and open invoices, and
    whether open invoices block it from shipping new product.

    Reads tables: vendors, invoices.
    Use for restocking questions: which vendor supplies an item type and how long it
    takes (ticket 103's hoodie shortfall, ticket 101's tee reprint).
    """
    with _connect() as conn:
        vendors = [dict(r) for r in conn.execute(
            "SELECT id, name, specialty, lead_days FROM vendors ORDER BY id")]
        for v in vendors:
            v["open_invoices"] = [dict(r) for r in conn.execute(
                "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status = 'open' "
                "ORDER BY due_date", (v["id"],))]
            v["blocked_from_shipping"] = len(v["open_invoices"]) > 0
    return {"count": len(vendors), "vendors": vendors}


@mcp.tool
def quote_bulk_discount(
    sku: str,
    size: str,
    qty: Annotated[int, Field(ge=1, le=10000)],
    discount_pct: Annotated[float, Field(ge=0, lt=100)],
) -> dict:
    """Price a bulk order at a proposed percentage off list: unit price, order
    total, margin left per unit and in total, whether the price would fall below
    unit cost, and whether stock covers the quantity. Changes nothing; the shop has
    no documented discount policy, so any discount still needs a human decision.

    Reads tables: inventory, pricing.
    Use for ticket 103 (Yale AI Club wants 20 navy hoodies, size M, at a discount).
    """
    with _connect() as conn:
        item = conn.execute(
            "SELECT name, qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone()
        price = conn.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)).fetchone()
    if item is None:
        return {"found": False, "error": f"No inventory row for sku={sku!r}, size={size!r}."}
    if price is None:
        return {"found": False, "error": f"No pricing row for sku={sku!r}."}

    unit_price = round(price["list_price"] * (1 - discount_pct / 100), 2)
    margin = round(unit_price - price["unit_cost"], 2)
    # Highest discount that still covers unit cost.
    break_even_pct = round((1 - price["unit_cost"] / price["list_price"]) * 100, 1)
    return {
        "found": True,
        "sku": sku,
        "name": item["name"],
        "size": size,
        "qty": qty,
        "discount_pct": discount_pct,
        "unit_cost": price["unit_cost"],
        "list_price": price["list_price"],
        "unit_price": unit_price,
        "order_total": round(unit_price * qty, 2),
        "order_total_at_list": round(price["list_price"] * qty, 2),
        "margin_per_unit": margin,
        "margin_total": round(margin * qty, 2),
        "below_cost": margin < 0,
        "break_even_discount_pct": break_even_pct,
        "qty_on_hand": item["qty"],
        "shortfall": max(qty - item["qty"], 0),
        "requires_human_approval": True,
    }


class _Refused(Exception):
    """Raised inside a transaction to roll it back and return a refusal to the caller."""

    def __init__(self, **result):
        super().__init__(result.get("error", "refused"))
        self.result = {"ok": False, **result}


@contextmanager
def _transaction():
    """One BEGIN IMMEDIATE transaction: commit on success, roll back on _Refused or any error."""
    conn = _connect(write=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _check_amount(expected: float | None, actual: float, what: str) -> None:
    if expected is not None and abs(expected - actual) > 0.005:
        raise _Refused(error=f"Amount changed: the approval was for {expected:.2f} but {what} is now {actual:.2f}.")


def _pay_invoice_tx(conn, invoice_id: int, account: str, approved_by: str, today: str,
                    expected_amount: float | None = None) -> dict:
    inv = conn.execute("SELECT id, amount, status FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if inv is None:
        raise _Refused(error=f"No invoice with id={invoice_id}.")
    prior = conn.execute(
        "SELECT id, paid_at FROM payments WHERE kind = 'invoice' AND ref_id = ?", (invoice_id,)).fetchone()
    if inv["status"] != "open" or prior is not None:
        raise _Refused(duplicate=True,
                       error=f"Invoice {invoice_id} is not open (status {inv['status']!r})"
                             + (f"; payment {prior['id']} already recorded on {prior['paid_at']}." if prior else "."))
    _check_amount(expected_amount, inv["amount"], f"invoice {invoice_id}")
    debit = _debit(conn, account, inv["amount"], today)
    if "error" in debit:
        raise _Refused(**debit)
    cur = conn.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
        "VALUES ('invoice', ?, ?, ?, ?, ?)",
        (invoice_id, inv["amount"], account, today, approved_by.strip()))
    conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (invoice_id,))
    return {"ok": True, "payment_id": cur.lastrowid, "invoice_id": invoice_id, "amount": inv["amount"],
            "account": account, "paid_at": today, "approved_by": approved_by.strip(),
            "invoice_status": "paid", **debit}


def _pay_rent_tx(conn, lease_id: int, due_date: str, account: str, approved_by: str, today: str,
                 expected_amount: float | None = None) -> dict:
    lease = conn.execute(
        "SELECT id, monthly_rent, next_due FROM leases WHERE id = ?", (lease_id,)).fetchone()
    if lease is None:
        raise _Refused(error=f"No lease with id={lease_id}.")
    if due_date != lease["next_due"]:
        raise _Refused(duplicate=due_date < lease["next_due"],
                       error=f"Lease {lease_id}'s next rent is due {lease['next_due']}, not {due_date}"
                             + (" (that month looks already paid)." if due_date < lease["next_due"] else "."))
    _check_amount(expected_amount, lease["monthly_rent"], f"lease {lease_id}'s rent")
    debit = _debit(conn, account, lease["monthly_rent"], today)
    if "error" in debit:
        raise _Refused(**debit)
    cur = conn.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
        "VALUES ('rent', ?, ?, ?, ?, ?)",
        (lease_id, lease["monthly_rent"], account, today, approved_by.strip()))
    new_due = _add_one_month(lease["next_due"])
    conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (new_due, lease_id))
    return {"ok": True, "payment_id": cur.lastrowid, "lease_id": lease_id, "amount": lease["monthly_rent"],
            "account": account, "paid_at": today, "approved_by": approved_by.strip(),
            "paid_due_date": due_date, "next_due": new_due, **debit}


@mcp.tool
def pay_invoice(
    invoice_id: Annotated[int, Field(ge=1)],
    account: str,
    approved_by: str,
) -> dict:
    """Pay one open vendor invoice in full from a cash account, in one transaction:
    insert a payments row (kind 'invoice', ref_id = invoice id), mark the invoice
    'paid', and debit the account. Refuses if the invoice is missing or not open
    (already paid), if a payment for it already exists, if approved_by is not a
    named human, or if the balance would go negative. Not given to any agent: the
    agents prepare a pending action and a human approves it instead.

    Reads tables: desk, invoices, payments, cash_accounts.
    Updates tables: payments (insert), invoices (status), cash_accounts (balance, date).
    Use for ticket 101: paying invoice 501 unblocks Bulldog Print Co's reprint.
    """
    if (err := _check_approver(approved_by)):
        return {"ok": False, "error": err}
    try:
        with _transaction() as conn:
            return _pay_invoice_tx(conn, invoice_id, account, approved_by, _today(conn))
    except _Refused as r:
        return r.result


@mcp.tool
def pay_rent(
    lease_id: Annotated[int, Field(ge=1)],
    due_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")],
    account: str,
    approved_by: str,
) -> dict:
    """Pay one month's rent on a lease from a cash account, in one transaction:
    insert a payments row (kind 'rent', ref_id = lease id), debit the account, and
    move the lease's next_due forward one month. due_date must equal the lease's
    current next_due; that guards against paying the same month twice. Refuses if
    the lease is missing, approved_by is not a named human, or the balance would go
    negative. Not given to any agent (see pay_invoice).

    Reads tables: desk, leases, cash_accounts.
    Updates tables: payments (insert), cash_accounts (balance, date), leases (next_due).
    Use for ticket 102 (lease 1 rent, due 2026-09-02).
    """
    if (err := _check_approver(approved_by)):
        return {"ok": False, "error": err}
    try:
        date.fromisoformat(due_date)
    except ValueError:
        return {"ok": False, "error": f"due_date={due_date!r} is not a valid date."}
    try:
        with _transaction() as conn:
            return _pay_rent_tx(conn, lease_id, due_date, account, approved_by, _today(conn))
    except _Refused as r:
        return r.result


@mcp.tool
def update_ticket_status(
    ticket_id: Annotated[int, Field(ge=1)],
    status: str,
    note: Annotated[str, Field(min_length=1, max_length=500)],
) -> dict:
    """Set a ticket's status to 'open', 'pending_approval', or 'closed' and append
    a dated note, in one transaction. Does nothing (and says so) if the ticket
    already has that status and the same note, so a repeated call can't stack
    duplicate notes.

    Reads tables: desk, tickets.
    Updates tables: tickets (status, notes).
    Use when a ticket (101, 102, 103) is finished or is waiting on a human decision.
    """
    if status not in TICKET_STATUSES:
        return {"ok": False, "error": f"status must be one of {list(TICKET_STATUSES)}, got {status!r}."}
    conn = _connect(write=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        today = _today(conn)
        t = conn.execute("SELECT id, status, notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            conn.execute("ROLLBACK")
            return {"ok": False, "error": f"No ticket with id={ticket_id}."}
        # The date is added here; drop any date prefix the caller already wrote.
        line = f"[{today}] {re.sub(r'^(\[\d{4}-\d{2}-\d{2}\]\s*)+', '', note.strip())}"
        notes = t["notes"] or ""
        if t["status"] == status and line in notes:
            conn.execute("ROLLBACK")
            return {"ok": True, "changed": False, "ticket_id": ticket_id, "status": status,
                    "message": "Ticket already has this status and note; nothing changed."}
        new_notes = f"{notes}\n{line}" if notes else line
        conn.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, new_notes, ticket_id))
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return {"ok": True, "changed": True, "ticket_id": ticket_id,
            "previous_status": t["status"], "status": status, "notes": new_notes}


# --------------------------------------------------------------------------- pending actions
#
# Agents never move money or place orders. They call prepare_payment /
# prepare_purchase, which store a row in pending_actions with an amount the server
# computes from the database. Only approve_pending_action executes it, and the
# backend calls that only from the dashboard's explicit human-approval route.
# These two tables are created on first use; the original database doesn't have them,
# so resetting the working copy also clears every pending action and purchase order.

PENDING_KINDS = ("invoice_payment", "rent_payment", "restock_purchase")

_ACTION_TABLES = """
CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    ticket_id INTEGER,
    ref_id INTEGER NOT NULL,
    account TEXT,
    amount REAL NOT NULL,
    due_date TEXT,
    sku TEXT,
    size TEXT,
    qty INTEGER,
    reason TEXT NOT NULL,
    prepared_by TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT,
    result TEXT
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY,
    pending_action_id INTEGER NOT NULL UNIQUE,
    vendor_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    approved_by TEXT NOT NULL
);
"""


def _ensure_action_tables(conn: sqlite3.Connection) -> None:
    for stmt in filter(str.strip, _ACTION_TABLES.split(";")):
        conn.execute(stmt)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _action_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    return d


def _open_invoice_ids(conn: sqlite3.Connection, vendor_id: int) -> list[int]:
    return [r["id"] for r in conn.execute(
        "SELECT id FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY id", (vendor_id,))]


def _store_pending(conn: sqlite3.Connection, kind: str, ref_id: int, amount: float, **fields) -> dict:
    """Insert a pending action, or return the one already pending for the same thing."""
    match = "kind = ? AND ref_id = ? AND status = 'pending'"
    params: list = [kind, ref_id]
    if kind == "restock_purchase":
        match += " AND sku = ? AND size = ? AND qty = ?"
        params += [fields["sku"], fields["size"], fields["qty"]]
    existing = conn.execute(f"SELECT * FROM pending_actions WHERE {match}", params).fetchone()
    if existing is not None:
        return {"ok": True, "already_pending": True, "action": _action_dict(existing),
                "message": f"Pending action {existing['id']} already covers this; no duplicate was created."}
    cols = {"kind": kind, "ref_id": ref_id, "amount": round(amount, 2), "prepared_at": _now(), **fields}
    cur = conn.execute(
        f"INSERT INTO pending_actions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        list(cols.values()))
    row = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"ok": True, "already_pending": False, "action": _action_dict(row),
            "message": f"Pending action {cur.lastrowid} is waiting for a human to approve it on the dashboard."}


@mcp.tool
def list_tickets() -> dict:
    """List every ticket (open, pending_approval, or closed) with its type,
    subject, linked IDs, and status, plus resolved = (status is 'closed').
    Requester names and notes are left out.

    Reads tables: tickets.
    Use for the dashboard's ticket list (101, 102, 103).
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, type, subject, sku, size, qty, lease_id, invoice_id, status, created_at "
            "FROM tickets ORDER BY id")]
    for r in rows:
        r["resolved"] = r["status"] == "closed"
    return {"count": len(rows), "tickets": rows}


@mcp.tool
def get_cash_balances() -> dict:
    """Return every cash account's balance and the date of that balance.

    Reads tables: cash_accounts.
    Use to check what the shop can afford (the dashboard shows 'checking').
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT name, balance, date FROM cash_accounts ORDER BY name")]
    return {"count": len(rows), "accounts": rows}


@mcp.tool
def prepare_payment(
    kind: str,
    ref_id: Annotated[int, Field(ge=1)],
    account: str,
    reason: Annotated[str, Field(min_length=1, max_length=500)],
    ticket_id: Annotated[int | None, Field(ge=1)] = None,
    prepared_by: str = "agent",
) -> dict:
    """Prepare (do NOT execute) a payment for a human to approve on the dashboard.
    kind is 'invoice_payment' (ref_id = invoice id, pays it in full) or
    'rent_payment' (ref_id = lease id, pays its current next_due month). The
    amount is taken from the database, never from the caller. Returns the
    existing pending action instead of creating a duplicate. Moves no money.

    Reads tables: desk, invoices, payments, leases, cash_accounts, pending_actions.
    Updates tables: pending_actions (insert).
    Use for ticket 101 (invoice 501) and ticket 102 (lease 1 rent).
    """
    if kind not in ("invoice_payment", "rent_payment"):
        return {"ok": False, "error": f"kind must be 'invoice_payment' or 'rent_payment', got {kind!r}."}
    try:
        with _transaction() as conn:
            _ensure_action_tables(conn)
            acct = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()
            if acct is None:
                raise _Refused(error=f"No cash account named {account!r}.")
            extra: dict = {}
            if kind == "invoice_payment":
                inv = conn.execute("SELECT amount, status FROM invoices WHERE id = ?", (ref_id,)).fetchone()
                if inv is None:
                    raise _Refused(error=f"No invoice with id={ref_id}.")
                if inv["status"] != "open":
                    raise _Refused(duplicate=True, error=f"Invoice {ref_id} is not open (status {inv['status']!r}).")
                amount = inv["amount"]
            else:
                lease = conn.execute("SELECT monthly_rent, next_due FROM leases WHERE id = ?", (ref_id,)).fetchone()
                if lease is None:
                    raise _Refused(error=f"No lease with id={ref_id}.")
                amount, extra["due_date"] = lease["monthly_rent"], lease["next_due"]
            out = _store_pending(conn, kind, ref_id, amount, account=account, ticket_id=ticket_id,
                                 reason=reason.strip(), prepared_by=prepared_by.strip() or "agent", **extra)
            out["cash_covers_now"] = acct["balance"] >= amount
            out["balance_now"] = acct["balance"]
            return out
    except _Refused as r:
        return r.result


@mcp.tool
def prepare_purchase(
    vendor_id: Annotated[int, Field(ge=1)],
    sku: str,
    size: str,
    qty: Annotated[int, Field(ge=1, le=10000)],
    reason: Annotated[str, Field(min_length=1, max_length=500)],
    ticket_id: Annotated[int | None, Field(ge=1)] = None,
    prepared_by: str = "agent",
) -> dict:
    """Prepare (do NOT place) a restock purchase order for a human to approve on
    the dashboard. The amount is qty x pricing.unit_cost, computed by the server.
    Reports whether the vendor is currently blocked by open invoices (a vendor
    with an open invoice will not ship, so approval is refused until they are
    paid). Returns the existing pending action instead of creating a duplicate.

    Reads tables: vendors, inventory, pricing, invoices, pending_actions.
    Updates tables: pending_actions (insert).
    Use for ticket 101 (1 tee, size S) and ticket 103 (the 12-hoodie shortfall).
    """
    try:
        with _transaction() as conn:
            _ensure_action_tables(conn)
            vendor = conn.execute("SELECT id, name FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
            if vendor is None:
                raise _Refused(error=f"No vendor with id={vendor_id}.")
            if conn.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
                raise _Refused(error=f"No inventory row for sku={sku!r}, size={size!r}.")
            price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
            if price is None:
                raise _Refused(error=f"No pricing row for sku={sku!r}.")
            out = _store_pending(conn, "restock_purchase", vendor_id, price["unit_cost"] * qty, sku=sku, size=size,
                                 qty=qty, ticket_id=ticket_id, reason=reason.strip(),
                                 prepared_by=prepared_by.strip() or "agent")
            blocking = _open_invoice_ids(conn, vendor_id)
            out["vendor"] = vendor["name"]
            out["vendor_blocked_by_open_invoices"] = blocking
            return out
    except _Refused as r:
        return r.result


@mcp.tool
def list_pending_actions(status: str | None = None, ticket_id: int | None = None) -> dict:
    """List prepared actions, newest first, optionally filtered by status
    ('pending', 'executed', 'rejected') and/or ticket_id.

    Reads tables: pending_actions.
    Use to see which payments or purchases are waiting for human approval, or what
    has already been prepared, approved, or rejected for one ticket.
    """
    with _connect() as conn:
        if not _has_table(conn, "pending_actions"):
            return {"count": 0, "actions": []}
        where, params = [], []
        if status:
            where.append("status = ?"); params.append(status)
        if ticket_id is not None:
            where.append("ticket_id = ?"); params.append(ticket_id)
        sql = "SELECT * FROM pending_actions" + (" WHERE " + " AND ".join(where) if where else "")
        rows = [_action_dict(r) for r in conn.execute(sql + " ORDER BY id DESC", params)]
    return {"count": len(rows), "actions": rows}


@mcp.tool
def get_pending_action(action_id: Annotated[int, Field(ge=1)]) -> dict:
    """Return one prepared action with its current status and, once decided, who
    decided it and the result.

    Reads tables: pending_actions.
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (action_id,)).fetchone() \
            if _has_table(conn, "pending_actions") else None
    if row is None:
        return {"found": False, "error": f"No pending action with id={action_id}."}
    return {"found": True, "action": _action_dict(row)}


@mcp.tool
def approve_pending_action(
    action_id: Annotated[int, Field(ge=1)],
    approved_by: str,
    expected_amount: Annotated[float, Field(gt=0)],
) -> dict:
    """Execute one pending action after a HUMAN approved it, in one transaction.
    Re-checks everything first: the action must still be 'pending', its amount
    must equal expected_amount and the amount the database gives now, and the
    related records must still be payable (invoice still open, lease next_due
    unchanged, vendor not blocked by open invoices, cash stays >= 0). On success
    the action becomes 'executed' with the result stored; on any refusal nothing
    changes. Never given to agents; the backend calls it only from the dashboard's
    approval route.

    Reads tables: desk, pending_actions, invoices, payments, leases, cash_accounts, vendors, pricing.
    Updates tables: pending_actions (status, decided_by, decided_at, result), and
    for invoice_payment: payments, invoices, cash_accounts; rent_payment: payments,
    cash_accounts, leases; restock_purchase: purchase_orders (insert).
    """
    if (err := _check_approver(approved_by)):
        return {"ok": False, "error": err}
    try:
        with _transaction() as conn:
            _ensure_action_tables(conn)
            today = _today(conn)
            a = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (action_id,)).fetchone()
            if a is None:
                raise _Refused(error=f"No pending action with id={action_id}.")
            if a["status"] != "pending":
                raise _Refused(duplicate=a["status"] == "executed",
                               error=f"Action {action_id} is already {a['status']!r}; it can only be approved once.")
            _check_amount(expected_amount, a["amount"], f"pending action {action_id}")
            if a["kind"] == "invoice_payment":
                result = _pay_invoice_tx(conn, a["ref_id"], a["account"], approved_by, today, a["amount"])
            elif a["kind"] == "rent_payment":
                result = _pay_rent_tx(conn, a["ref_id"], a["due_date"], a["account"], approved_by, today, a["amount"])
            elif a["kind"] == "restock_purchase":
                if (blocking := _open_invoice_ids(conn, a["ref_id"])):
                    raise _Refused(error=f"Vendor {a['ref_id']} still has open invoices {blocking}; a vendor with an "
                                         "open invoice will not ship. Pay those first.")
                price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (a["sku"],)).fetchone()
                if price is None:
                    raise _Refused(error=f"No pricing row for sku={a['sku']!r}.")
                _check_amount(a["amount"], round(price["unit_cost"] * a["qty"], 2), "the purchase cost")
                cur = conn.execute(
                    "INSERT INTO purchase_orders (pending_action_id, vendor_id, sku, size, qty, unit_cost, total, "
                    "status, ordered_at, approved_by) VALUES (?, ?, ?, ?, ?, ?, ?, 'ordered', ?, ?)",
                    (action_id, a["ref_id"], a["sku"], a["size"], a["qty"], price["unit_cost"], a["amount"],
                     today, approved_by.strip()))
                result = {"ok": True, "purchase_order_id": cur.lastrowid, "vendor_id": a["ref_id"], "sku": a["sku"],
                          "size": a["size"], "qty": a["qty"], "total": a["amount"], "ordered_at": today,
                          "note": "Order recorded; cash and stock are unchanged (payment terms and delivery are "
                                  "not documented, so the vendor's bill and the received stock are separate steps)."}
            else:
                raise _Refused(error=f"Unknown action kind {a['kind']!r}.")
            conn.execute(
                "UPDATE pending_actions SET status = 'executed', decided_by = ?, decided_at = ?, result = ? "
                "WHERE id = ? AND status = 'pending'",
                (approved_by.strip(), _now(), json.dumps(result), action_id))
            return {"ok": True, "action_id": action_id, "kind": a["kind"], "status": "executed", "result": result}
    except _Refused as r:
        return {**r.result, "action_id": action_id}


@mcp.tool
def reject_pending_action(
    action_id: Annotated[int, Field(ge=1)],
    rejected_by: str,
    note: Annotated[str, Field(max_length=500)] = "",
) -> dict:
    """Mark one pending action 'rejected' so it can never be executed. Changes no
    money or stock.

    Reads tables: pending_actions.
    Updates tables: pending_actions (status, decided_by, decided_at, decision_note).
    """
    if (err := _check_approver(rejected_by)):
        return {"ok": False, "error": err.replace("approve payments", "reject actions")}
    try:
        with _transaction() as conn:
            _ensure_action_tables(conn)
            a = conn.execute("SELECT status FROM pending_actions WHERE id = ?", (action_id,)).fetchone()
            if a is None:
                raise _Refused(error=f"No pending action with id={action_id}.")
            if a["status"] != "pending":
                raise _Refused(error=f"Action {action_id} is already {a['status']!r}.")
            conn.execute(
                "UPDATE pending_actions SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? "
                "WHERE id = ?", (rejected_by.strip(), _now(), note.strip() or None, action_id))
            return {"ok": True, "action_id": action_id, "status": "rejected"}
    except _Refused as r:
        return {**r.result, "action_id": action_id}


@mcp.tool
def reset_working_database(confirm: str) -> dict:
    """Overwrite the working database (campus_customs_new.db) with the original
    campus_customs.db, for a fresh run. The original is only read. This also
    clears every pending action and purchase order, because those tables exist
    only in the working copy. confirm must be exactly 'RESET'. Never given to agents.

    Reads: the original database file. Updates: every table in the working database.
    """
    if confirm != "RESET":
        return {"ok": False, "error": "confirm must be exactly 'RESET'."}
    if not ORIGINAL_DB_PATH.exists():
        return {"ok": False, "error": f"Original database not found at {ORIGINAL_DB_PATH}."}
    if ORIGINAL_DB_PATH == DB_PATH:
        return {"ok": False, "error": "The working and original database paths are the same; refusing."}
    src = sqlite3.connect(f"file:{ORIGINAL_DB_PATH}?mode=ro", uri=True)
    dst = sqlite3.connect(DB_PATH)
    try:
        dst.execute("PRAGMA busy_timeout = 5000")
        src.backup(dst)  # exact page-level copy under SQLite's own locking
    finally:
        src.close()
        dst.close()
    with _connect() as conn:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        cash = [dict(r) for r in conn.execute("SELECT name, balance FROM cash_accounts")]
        statuses = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM tickets")}
    return {"ok": True, "reset_from": ORIGINAL_DB_PATH.name, "reset_to": DB_PATH.name,
            "tables": tables, "cash_accounts": cash, "ticket_statuses": statuses}


if __name__ == "__main__":
    mcp.run(show_banner=False)
