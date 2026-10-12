# Campus Customs MCP Server

A [FastMCP](https://gofastmcp.com) server that is the Campus Customs agent team's only path to shop data. It has 19 tools: 11 lookups, 3 direct writes, and 5 tools for pending actions and resets. Agents can only *prepare* payments and purchases; a person approves them through the backend.

## Database

The server uses the working copy `data/campus_customs_new.db`, never the original `data/campus_customs.db`. The path is resolved relative to `server.py`, so the server works from any launch directory. Tests set `CAMPUS_CUSTOMS_DB` (and `CAMPUS_CUSTOMS_ORIGINAL_DB`, the reset source) to point it at throwaway copies instead.

The first prepare call creates two extra tables in the working copy, `pending_actions` and `purchase_orders`. The original database never has them.

Lookup tools open the database in SQLite read-only mode. Each write tool runs in one `BEGIN IMMEDIATE` transaction, refuses duplicate actions, and rolls back completely when it refuses.

## Tools

### Lookups (read-only)

| Tool | Parameters | Reads | Returns |
|---|---|---|---|
| `check_stock_and_pricing` | `sku`, `size`, `qty_needed` (default 1) | `inventory`, `pricing` | Units on hand, shortfall against the quantity needed, unit cost, list price, margin |
| `get_invoice_with_vendor` | `invoice_id` | `invoices`, `vendors`, `desk` | Invoice status, days overdue vs. `desk.date_today`, the vendor's specialty and lead days, and whether open invoices block the vendor from shipping |
| `get_rent_due_and_cash` | `lease_id` | `leases`, `desk`, `cash_accounts` | Monthly rent, next due date, days until due, and whether each cash account can cover the rent |
| `list_open_tickets` | none | `tickets` | Tickets not `closed`, oldest first, with type, subject, and linked IDs. Requester names and notes are left out |
| `get_ticket` | `ticket_id` (≥ 1) | `tickets`, `inventory`, `leases`, `invoices` | The full ticket row, plus whether its inventory row, lease, and invoice exist |
| `list_vendors` | none | `vendors`, `invoices` | Each vendor's specialty, lead days, open invoices, and `blocked_from_shipping` |
| `quote_bulk_discount` | `sku`, `size`, `qty` (1–10000), `discount_pct` (0 to <100) | `inventory`, `pricing` | Discounted unit price, order total, margin per unit and in total, `below_cost`, break-even discount %, and stock shortfall. Changes nothing |
| `list_tickets` | none | `tickets` | Every ticket (including closed) with status and `resolved`, without requester names |
| `get_cash_balances` | none | `cash_accounts` | Each account's balance and date |
| `list_pending_actions` | `status`, `ticket_id` (both optional) | `pending_actions` | Prepared actions, newest first; the agent runner uses `ticket_id` to show each ticket's earlier actions to the agents |
| `get_pending_action` | `action_id` | `pending_actions` | One prepared action with its status and result |

### Writes (transactional)

| Tool | Parameters | Updates | Guards |
|---|---|---|---|
| `pay_invoice` | `invoice_id`, `account`, `approved_by` | inserts `payments` (kind `invoice`), sets `invoices.status = 'paid'`, debits `cash_accounts` | Invoice must exist and be `open` with no prior payment. `approved_by` must be a human name, not empty and not an agent name. The balance may not go negative |
| `pay_rent` | `lease_id`, `due_date` (YYYY-MM-DD), `account`, `approved_by` | inserts `payments` (kind `rent`), debits `cash_accounts`, moves `leases.next_due` forward one month | `due_date` must equal the lease's current `next_due`, so a month can't be paid twice. Human approver required. The balance may not go negative |
| `update_ticket_status` | `ticket_id`, `status` (`open` / `pending_approval` / `closed`), `note` (1–500 chars) | `tickets.status`, appends a dated line to `tickets.notes` | Rejects other statuses. A repeat with the same status and note changes nothing |

### Pending actions and reset (transactional)

| Tool | Parameters | Updates | Guards |
|---|---|---|---|
| `prepare_payment` | `kind` (`invoice_payment` / `rent_payment`), `ref_id`, `account`, `reason`, `ticket_id`, `prepared_by` | inserts `pending_actions` | Amount comes from the invoice or lease, never the caller. Returns the existing pending action instead of a duplicate. Moves no money |
| `prepare_purchase` | `vendor_id`, `sku`, `size`, `qty`, `reason`, `ticket_id`, `prepared_by` | inserts `pending_actions` | Amount = qty × `pricing.unit_cost`. Reports whether the vendor is blocked by open invoices. No duplicate pending purchase |
| `approve_pending_action` | `action_id`, `approved_by`, `expected_amount` | the action's status/result, plus the payment tables (as `pay_invoice` / `pay_rent`) or a `purchase_orders` row | Action must be `pending`. `expected_amount` must match. Records are re-checked (invoice still open, lease `next_due` unchanged, vendor not blocked, cash ≥ 0). Executes once |
| `reject_pending_action` | `action_id`, `rejected_by`, `note` | the action's status | Only `pending` actions. A rejected action can never execute |
| `reset_working_database` | `confirm` (must be `"RESET"`) | overwrites `campus_customs_new.db` from `campus_customs.db` | Refuses if the paths are the same. The original is only read. Clears pending actions and purchase orders |

Payments use `desk.date_today` as `paid_at`.

When a record doesn't exist, a tool returns `{"found": false, "error": "..."}` (lookups) or `{"ok": false, "error": "..."}` (writes) instead of made-up data. Invalid parameter values are rejected by input validation before the tool runs.

**Human approval:** in the agent backend (`backend/`), no agent can call `pay_invoice`, `pay_rent`, `approve_pending_action`, `reject_pending_action`, or `reset_working_database`. Agents only prepare actions. The backend calls the approval and reset tools only from the dashboard's explicit routes (`POST /api/pending-actions/{id}/approve`, `POST /api/reset`). If you call these tools directly from an MCP client (such as Claude Code), you are acting as the human.

## Setup

```bash
python3 -m venv .venv            # from Homework/5
.venv/bin/pip install -r mcp_server/requirements.txt
.venv/bin/python mcp_server/server.py   # runs over stdio
```

Dependencies: `fastmcp` (installs `mcp` and `pydantic`). `sqlite3` is in the Python standard library.
