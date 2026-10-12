# Campus Customs — Database Harness

Source of truth: `data/campus_customs.db` (original, unchanged). The agents work on the copy `data/campus_customs_new.db`.

**Contents:** the 9 original tables and the 2 tables the system adds · the open-ticket relationships · the 5 agents · all 19 MCP tools · safety rules and limits · backend routes · dashboard · the final run (Problem 9).

**Key notation:** **PK** = primary key. **FK** = foreign key declared in the schema. *Implicit link* = the column values match another table, but no foreign key is declared.

---

## desk

| Field | Type | Notes |
|---|---|---|
| date_today | TEXT, NOT NULL | Current value: `2026-08-31` |
| notes | TEXT | Empty |

- **Keys:** no primary key declared; the table holds one row.
- **Why useful:** It gives every agent the shop's "today" (2026-08-31), so they can work out what is overdue or coming due.

## tickets

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | **PK** |
| type | TEXT, NOT NULL | `customer_order`, `rent_notice`, `price_override` |
| requester | TEXT, NOT NULL | |
| subject | TEXT, NOT NULL | |
| sku | TEXT | *Implicit link* → `inventory.sku`, `pricing.sku` |
| size | TEXT | *Implicit link* → `inventory.size` (with `sku`) |
| qty | INTEGER | |
| lease_id | INTEGER | **FK** → `leases.id` |
| invoice_id | INTEGER | **FK** → `invoices.id` |
| status | TEXT, NOT NULL | All 3 rows are `open` |
| notes | TEXT | |
| created_at | TEXT, NOT NULL | ISO timestamp |

- **Why useful:** This is the work board. The Boss reads each ticket here and routes it to the right agent.

## inventory

| Field | Type | Notes |
|---|---|---|
| sku | TEXT, NOT NULL | **PK** (with size) |
| name | TEXT, NOT NULL | |
| size | TEXT, NOT NULL | **PK** (with sku) |
| qty | INTEGER, NOT NULL | Units on hand |
| location | TEXT, NOT NULL | Aisle |

- **Keys:** composite primary key `(sku, size)`.
- **Why useful:** The Inventory agent checks stock by SKU and size here to spot shortfalls.

## pricing

| Field | Type | Notes |
|---|---|---|
| sku | TEXT | **PK**; *implicit link* → `inventory.sku` |
| unit_cost | REAL, NOT NULL | |
| list_price | REAL, NOT NULL | |

- **Why useful:** Accounting compares cost with list price here to check margins, for example before approving a discount.

## vendors

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | **PK** |
| name | TEXT, NOT NULL | |
| specialty | TEXT, NOT NULL | What the vendor supplies |
| lead_days | INTEGER, NOT NULL | Days needed to deliver |

- **Why useful:** Inventory uses it to pick the vendor that can restock an item and to estimate how long restocking takes.

## leases

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | **PK** |
| space_name | TEXT, NOT NULL | |
| landlord | TEXT, NOT NULL | |
| monthly_rent | REAL, NOT NULL | |
| next_due | TEXT, NOT NULL | Date the next rent payment is due |
| notes | TEXT | |

- **Why useful:** Facilities looks up rent amounts and due dates here to handle rent tickets.

## cash_accounts

| Field | Type | Notes |
|---|---|---|
| name | TEXT | **PK** (e.g. `checking`) |
| balance | REAL, NOT NULL | |
| date | TEXT, NOT NULL | Date of the balance |

- **Why useful:** Accounting checks it before any payment, so the pay tool can refuse a payment that would make the balance negative.

## payments

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | **PK** |
| kind | TEXT, NOT NULL | What was paid |
| ref_id | INTEGER | ID of the paid record (no FK declared) |
| amount | REAL, NOT NULL | |
| account | TEXT, NOT NULL | *Implicit link* (by name) → `cash_accounts.name` |
| paid_at | TEXT, NOT NULL | |
| approved_by | TEXT, NOT NULL | Human approver |

- **Keys:** no foreign keys are declared, and the table is currently empty (0 rows). From the column names, `ref_id` + `kind` look meant to point at the paid record (such as an invoice or a lease), but the data cannot confirm this yet.
- **Why useful:** It is the audit log of money going out, recording who approved each payment.

## invoices

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | **PK** |
| vendor_id | INTEGER, NOT NULL | **FK** → `vendors.id` |
| amount | REAL, NOT NULL | |
| due_date | TEXT, NOT NULL | |
| status | TEXT, NOT NULL | `open` = unpaid |
| description | TEXT | |

- **Why useful:** It shows which vendor bills are unpaid or overdue. This matters because a vendor with an open invoice will not ship new product.

## pending_actions *(added by the system, not in the original database)*

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | **PK**: the action number shown on the dashboard |
| kind | TEXT, NOT NULL | `invoice_payment`, `rent_payment`, `restock_purchase` |
| ticket_id | INTEGER | Ticket it was prepared for (*implicit link* → `tickets.id`) |
| ref_id | INTEGER, NOT NULL | Invoice id, lease id, or vendor id, depending on `kind` |
| account | TEXT | Cash account for payments |
| amount | REAL, NOT NULL | Computed by the server from `invoices`, `leases`, or `pricing`, never from the agent |
| due_date | TEXT | Rent month being paid (`rent_payment`) |
| sku, size, qty | TEXT, TEXT, INTEGER | Items for `restock_purchase` |
| reason | TEXT, NOT NULL | The agent's stated purpose |
| prepared_by, prepared_at | TEXT | Agent role (set by the backend) and real time |
| status | TEXT, NOT NULL | `pending`, `executed`, `rejected` |
| decided_by, decided_at, decision_note, result | TEXT | The human's name, real time, note, and execution result (JSON) |

- **Why useful:** It is the hand-off between agents and a human. Agents can only add rows here; money moves or orders are placed only when a person approves a row on the dashboard. It is created on first use, so a reset (which copies the original database) clears it.
- **Known inconsistency:** `prepared_at` / `decided_at` use real time, while `payments.paid_at` uses `desk.date_today`. In the final run this led ticket 102's agents to call the timing a "chronology inconsistency".

## purchase_orders *(added by the system, not in the original database)*

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | **PK** (PO number) |
| pending_action_id | INTEGER, NOT NULL, UNIQUE | The approved `restock_purchase` action (one order per action) |
| vendor_id | INTEGER, NOT NULL | *Implicit link* → `vendors.id` |
| sku, size, qty | TEXT, TEXT, INTEGER | Items ordered |
| unit_cost, total | REAL | From `pricing.unit_cost` at approval time |
| status | TEXT | `ordered` |
| ordered_at, approved_by | TEXT | Shop date and the human approver |

- **Why useful:** It records restock orders a human approved. By the owner's decision for this system, an approved purchase records the order only: checking and inventory do not change (no payment terms or delivery tracking exist).

---

## Relationships found in the three open tickets

**Declared foreign keys:** `tickets.lease_id → leases.id`, `tickets.invoice_id → invoices.id`, and `invoices.vendor_id → vendors.id`.

**Implicit links:** `tickets.(sku, size) → inventory.(sku, size)` and `sku → pricing.sku`.

### Ticket 101 — customer_order: Tauhid Zaman, `CC-TEE-WHITE` size S, qty 1
- **Inventory:** `CC-TEE-WHITE / S` (Classic Bulldog Tee, Aisle B) has **qty 0**, so 1 unit is missing.
- **Invoice:** `invoice_id 501` → **invoice 501**: $840.00, "Rush reprint CC-TEE-WHITE S", due **2026-08-28**, status **open**. That is overdue as of `desk.date_today` = 2026-08-31.
- **Vendor:** invoice 501 has `vendor_id 1` → **vendor 1, Bulldog Print Co** (apparel reprint, lead 5 days). Because the invoice is still open, this vendor will not ship more until it is paid.
- **Pricing:** cost $8.00, list price $28.00.

### Ticket 102 — rent_notice: Elm City Properties, "Rent due"
- **Lease:** `lease_id 1` → **lease 1**: Chapel Street shop, landlord Elm City Properties, **$2,400.00** a month, `next_due` **2026-09-02**. That is 2 days after today, which matches the ticket note "rent due in 2 days".
- **Cash:** the only cash account, `checking`, holds **$3,400.00**. Any rent payment needs human approval, and the pay tool must refuse it if cash is too low.

### Ticket 103 — price_override: Yale AI Club, `CC-HOOD-NAVY` size M, qty 20, bulk discount
- **Inventory:** `CC-HOOD-NAVY / M` (Basic Hoodie Big Yale, Aisle A) has **qty 8**, so **12 units** are missing.
- **Pricing:** cost **$22.00**, list price **$58.00**. These are the numbers for judging how much discount the margin can absorb.
- **Vendor (indirect):** no vendor is linked on the ticket. The only apparel vendor is **vendor 1, Bulldog Print Co**, and it still has open invoice 501 (the same one from ticket 101). Restocking the hoodies is blocked until that invoice is paid.

### Cross-ticket dependency
All three tickets compete for the same **$3,400** in `checking`: invoice 501 ($840) plus rent ($2,400) comes to $3,240, which would leave $160. Paying invoice 501 also unblocks Bulldog Print Co, which matters for both ticket 101 and ticket 103.

---

## MCP tools (`mcp_server/server.py`)

All three tools open `data/campus_customs_new.db` in read-only mode and return `found: false` with an error message when a record is missing.

### `check_stock_and_pricing(sku, size, qty_needed=1)`
- **Reads:** `inventory`, `pricing`
- **Advances:** Ticket **103** (also used for ticket 101's stock check)
- **How it helps:** For `CC-HOOD-NAVY` size M with `qty_needed=20`, it shows 8 on hand, a shortfall of 12, and a $22 cost vs. $58 list price ($36 margin, 62.1%). That tells the team how much stock must be reordered and how much discount the Yale AI Club order can absorb without selling below cost.

### `get_invoice_with_vendor(invoice_id)`
- **Reads:** `invoices`, `vendors`, `desk`
- **Advances:** Ticket **101**
- **How it helps:** For invoice 501, it shows the $840 Bulldog Print Co bill is open and 3 days past due as of 2026-08-31, so the vendor is blocked from shipping. That explains why the size-S tee can't be restocked until the bill is paid, and it reports the vendor's 5-day lead time for estimating the customer's wait.

### `get_rent_due_and_cash(lease_id)`
- **Reads:** `leases`, `desk`, `cash_accounts`
- **Advances:** Ticket **102**
- **How it helps:** For lease 1, it shows the $2,400 Chapel Street rent is due 2026-09-02, in 2 days. `checking` holds $3,400 and can cover it, leaving $1,000. Accounting can then prepare an on-time rent payment for human approval, knowing it won't overdraw the account.

---

## Agent team (`backend/`)

Five PydanticAI agents run on **gpt-6-luna through Portkey** (`backend/config.py`; `PORTKEY_API_KEY` comes from the root `.env` and is never logged). Each agent's prompt lives in `backend/prompts/<role>.md`, the shared types are in `backend/models.py`, and the loop, delegation, and MCP wiring are in `backend/team.py`. Run a ticket with `.venv/bin/python -m backend.run_ticket 102`.

| Agent | Responsibilities | MCP tools it can call |
|---|---|---|
| **Boss** | Reads the ticket, decides who works on it, combines reports, sets the ticket status, and lists what humans must approve | `get_ticket`, `list_open_tickets`, `update_ticket_status` |
| **Inventory** | Stock on hand vs. requested, shortfall, shelf location, likely restock vendor, lead time, whether the vendor is blocked, and *preparing* a restock purchase for human approval | `check_stock_and_pricing`, `list_vendors`, `prepare_purchase` |
| **Accounting** | Invoices, overdue status, cash balances, margins, bulk-discount math, and *preparing* invoice/rent payments for human approval (never executes them) | `get_invoice_with_vendor`, `get_rent_due_and_cash`, `get_cash_balances`, `check_stock_and_pricing`, `quote_bulk_discount`, `list_vendors`, `prepare_payment` |
| **Facilities** | Lease, landlord, rent amount, due date, days until due, and whether cash covers rent | `get_rent_due_and_cash` |
| **Customer Service** | Drafts the reply to the requester from confirmed facts only. Never sends it, and never shares costs, margins, cash, invoices, or vendor problems | `get_ticket`, `check_stock_and_pricing` |

**Context every agent receives** (built by the runner through MCP, not by the model):
- the ticket row (`get_ticket`), with customer names redacted for roles that don't need them;
- **ACTIONS ALREADY ON THIS TICKET** (`list_pending_actions(ticket_id=…)`): every pending, executed, or rejected action, so a later run builds on approved work instead of repeating it;
- **HUMAN DECISIONS FOR THIS RUN**: optional text a person typed in the dashboard's "Decisions for the team" field (e.g. the owner's 10% discount for ticket 103).

### Delegation

- **Every agent has a `delegate(to_role, task, findings)` tool** and can delegate to any other role. The delegate starts with the ticket context (from the `get_ticket` MCP tool), the task, the caller's confirmed findings, and the chain so far. It returns a structured `AgentReport` (status, summary, findings with sources, actions taken, approvals needed, missing info, customer reply draft).
- **Cycles are refused:** an agent cannot delegate to itself or to any agent already in the current chain (e.g. `boss → facilities → boss` is refused).
- **Depth is capped at 2** (Boss → specialist → specialist), and a run allows **at most 8 delegations** in total. A refused delegation comes back to the caller as `{"status": "refused", "reason": ...}`, so the caller finishes with what it has.
- **Routes observed in the final run** (Problem 9; see the Actual sections in `desk_tickets.html`):
  - 101: Boss → Inventory, Accounting, Customer Service (run 1), then Boss → Inventory, Customer Service (runs 2–3)
  - 102: Boss → Facilities, Accounting (both runs)
  - 103: Boss → Inventory, Accounting, Customer Service (run 1), then Boss → Inventory, Customer Service (run 2)

  Specialist-to-specialist delegation (e.g. Facilities → Accounting) is available but did not happen in the final run; Boss made every hand-off.

## All MCP tools (final, `mcp_server/server.py`)

Every tool goes through `data/campus_customs_new.db`. Lookup tools open the database read-only. Write tools run in one `BEGIN IMMEDIATE` transaction and roll back on any refusal.

| Tool | Reads | Updates | Ticket |
|---|---|---|---|
| `check_stock_and_pricing(sku, size, qty_needed)` | inventory, pricing | — | 101, 103 |
| `get_invoice_with_vendor(invoice_id)` | invoices, vendors, desk | — | 101 |
| `get_rent_due_and_cash(lease_id)` | leases, desk, cash_accounts | — | 102 |
| `list_open_tickets()` | tickets | — | all |
| `get_ticket(ticket_id)` | tickets, inventory, leases, invoices | — | all |
| `list_vendors()` | vendors, invoices | — | 101, 103 |
| `quote_bulk_discount(sku, size, qty, discount_pct)` | inventory, pricing | — | 103 |
| `pay_invoice(invoice_id, account, approved_by)` *(human-only, no agent)* | desk, invoices, payments, cash_accounts | payments (insert), invoices.status, cash_accounts.balance/date | 101 |
| `pay_rent(lease_id, due_date, account, approved_by)` *(human-only, no agent)* | desk, leases, cash_accounts | payments (insert), cash_accounts.balance/date, leases.next_due | 102 |
| `update_ticket_status(ticket_id, status, note)` | desk, tickets | tickets.status, tickets.notes | all |
| `list_tickets()` | tickets | — | all (dashboard) |
| `get_cash_balances()` | cash_accounts | — | 101, 102 (dashboard) |
| `prepare_payment(kind, ref_id, account, reason)` | desk, invoices, leases, cash_accounts, pending_actions | pending_actions (insert) | 101, 102 |
| `prepare_purchase(vendor_id, sku, size, qty, reason)` | vendors, inventory, pricing, invoices, pending_actions | pending_actions (insert) | 101, 103 |
| `list_pending_actions(status, ticket_id)` / `get_pending_action(action_id)` | pending_actions | — | all (dashboard; the runner also uses it for each ticket's context) |
| `approve_pending_action(action_id, approved_by, expected_amount)` *(human-only)* | pending_actions, desk, invoices, payments, leases, cash_accounts, vendors, pricing | pending_actions (status/result), plus payments + invoices + cash_accounts (invoice), payments + cash_accounts + leases (rent), or purchase_orders (purchase) | 101, 102, 103 |
| `reject_pending_action(action_id, rejected_by, note)` *(human-only)* | pending_actions | pending_actions (status) | all |
| `reset_working_database(confirm="RESET")` *(human-only)* | campus_customs.db (read only) | every table in campus_customs_new.db | — |

How the new tools help each ticket:
- **`get_ticket`** reads ticket 101 and confirms its `CC-TEE-WHITE / S` inventory row and invoice 501 both exist. It is the context every agent starts from.
- **`list_open_tickets`** shows the board (101, 102, 103) without customer names, so the Boss can spot related tickets.
- **`list_vendors`** shows Bulldog Print Co (apparel reprint, 5 lead days) is blocked by open invoice 501. That explains why ticket 103's 12-hoodie shortfall and ticket 101's tee can't be restocked yet.
- **`quote_bulk_discount`** prices ticket 103's 20 hoodies at a proposed discount. For example, 10% off gives $52.20 each, $1,044 in total, and a $30.20 margin per unit, and anything above 62.1% off would sell below cost. It changes nothing; the discount decision stays with a human.
- **`prepare_payment`** stores a pending payment for invoice 501 ($840, ticket 101) or lease 1's rent ($2,400 due 2026-09-02, ticket 102). The amount comes from the database, and no money moves.
- **`prepare_purchase`** stores a pending restock order, e.g. 12 navy M hoodies × $22 = $264 for ticket 103. It reports that Bulldog Print Co is blocked by invoice 501.
- **`approve_pending_action`** executes a prepared action once a person approves it on the dashboard:
  - invoice payment: debits the invoice amount (501: −$840) and the vendor block clears
  - rent payment: debits the monthly rent (lease 1: −$2,400) and `next_due` moves forward a month
  - purchase: recorded in `purchase_orders`, and refused while the vendor still has an open invoice
- **`pay_invoice` / `pay_rent`** are the original single-step payment tools. No agent can call them; `approve_pending_action` reuses the same transaction code.
- **`list_tickets`** and **`get_cash_balances`** feed the dashboard's ticket list (open/closed) and checking balance.
- **`update_ticket_status`** sets a ticket to `pending_approval` or `closed` with a dated note.

**Duplicate guards:**
- `prepare_payment` / `prepare_purchase` return the existing pending action instead of creating a second one.
- `approve_pending_action` only executes a `pending` action and marks it `executed` in the same transaction. A second approval is refused, and so is a mismatched amount or a stale record (invoice already paid, lease month already paid).
- `pay_invoice` refuses an invoice that isn't `open` or already has a payment row.
- `pay_rent` requires `due_date` to equal the lease's current `next_due`, so the same month can't be paid twice.
- `update_ticket_status` won't append the same note twice.
- The backend also skips an identical write repeated within one run. It also skips a status update when the ticket already has that status and no new pending action was prepared in the run, so re-running a ticket doesn't stack notes.

## Safety, approvals, and limits

**Human approval required:**
1. **Any payment or restock purchase.** Agents can only *prepare* one (`prepare_payment`, `prepare_purchase`): a row in `pending_actions` with a server-computed amount, the preparing agent, and the ticket. It executes only through `POST /api/pending-actions/{id}/approve`, which a person sends from the dashboard with their name and the exact amount they saw. The server then re-checks status, amount, and the related records and executes once through MCP. No agent has `pay_invoice`, `pay_rent`, `approve_pending_action`, `reject_pending_action`, or `reset_working_database`: those tools are filtered out of every role and blocked in code. The server also rejects empty or agent-like approver names.
2. **Any discount or price override.** There is no tool to grant one, and no policy exists.
3. **Sending any message** to a customer, landlord, or vendor. Agents only draft.
4. **Placing a restock order.** Only by approving a prepared purchase. It is recorded in `purchase_orders`, but cash and stock don't change, because payment terms and delivery are not documented.
5. **Resetting the working database.** Only through `POST /api/reset` with `{"confirm": "RESET"}`.

**Business safeguards:**
- Cash can never go negative: the payment and its balance update are refused and rolled back together.
- **A ticket can't be closed while one of its actions is still pending.** The backend refuses `update_ticket_status(status="closed")` and the agent must use `pending_approval`.
- **Closing rule** (the owner's decision for this system on 2026-10-11, not a documented shop policy): Boss may close a ticket once every payment or purchase it needed has been approved and executed, any needed human decision is recorded, and only sending the drafted reply remains.
- **Human decisions are explicit.** Undocumented questions (such as a discount) are answered by a person in the dashboard's "Decisions for the team" field. The text is logged as `human_instructions` in the run's `run_start` audit entry.
- Each role is limited to the MCP tools listed above. Other tools are filtered out of its tool list, and a code-level check blocks any that slip through.
- Agents have no direct database access. The MCP server is the only path to data, and it runs without the API key in its environment.

**Customer information:**
- Customer names (on `customer_order` and `price_override` tickets) go only to Boss and Customer Service. The other roles see `[redacted]`.
- `list_open_tickets` omits names.
- The audit trail replaces customer names with `[customer]` and the API key with `[secret]`. For a private customer (`customer_order`), first or last names used alone ("Hi Tauhid") are also replaced. That rule was added after the final run, so the ticket 101 entries from that run still contain the customer's first name in reply drafts; existing audit entries are never rewritten.
- Customer Service drafts are rejected and rewritten if they mention cost, margin, cash, invoices, rent, or vendor problems.

**Audit trail:** `output/audit_trail.json` is one JSON array. Every agent-loop step is appended as it happens: run start, prompts, model requests and responses with token usage, MCP tool calls with arguments and results, delegation start/end/refusal, guardrail blocks, pending actions prepared, limit stops, and run end with total usage. Human actions from the dashboard are appended too (`approval_requested`, `approval_executed` with balances before and after, `approval_refused`, `action_rejected`, `database_reset`), and a reset never removes earlier entries. If the backend is started with `CAMPUS_CUSTOMS_RUN_LABEL`, every entry it writes gets that `run_label`. The final graded run uses `problem9-full-run-2026-10-11`. Each append rewrites the file atomically and keeps earlier entries. If the existing file isn't a valid JSON array, nothing is written.

**Token and run limits** (`RunLimits` in `backend/config.py`; shared by the whole team for one ticket, enforced in code):

| Limit | Value |
|---|---|
| Model requests | 30 |
| Total tokens (input + output) | 150,000 |
| Output tokens per response | 8,000 |
| Tool calls (MCP + delegate) | 40 |
| Delegation depth / total delegations | 2 / 8 |
| Tool and output-validation retries per agent | 2 (MCP tool errors: 1) |
| HTTP retries | 2 |
| Run duration | 300 s |
| Single tool call timeout | 30 s |

Hitting a request, token, tool-call, or time limit stops every agent and ends the run with `status: "limit_exceeded"`. For scale, each run in the final full run used 8–15 model requests and 27k–55k tokens (seven runs, all within limits; see `desk_tickets.html`).

**Shop rules that are not documented** (the agents flag these instead of inventing them):
- No discount policy (maximum %, minimum margin, or who approves)
- No purchase payment terms or delivery tracking (an approved purchase is only recorded as an order)
- No vendor-to-SKU table (vendor matches are inferred from `specialty`)
- No rule for which bill to pay first when cash is tight
- No partial-payment rule
- No rule on paying rent early, and no late fees or grace period
- No backorder or reservation rule
- No customer messaging channel
- No ticket status values beyond `open` (the backend adds `pending_approval` and `closed`), and no definition of "resolved" (the closing rule above is the owner's decision)
- No place to store an approved discount or price override (ticket 103's 10% exists only as the owner's decision, the quote, and the ticket note)
- Whether "a vendor with an open invoice will not ship" is an original shop rule: this harness has stated it since Problem 2, but no field in the database records it, and its original source could not be re-confirmed

## Backend routes (`backend/main.py`)

**Start the server** (from `Homework/5/backend/`, with the project venv):

```bash
cd backend
../.venv/bin/uvicorn main:app --reload --port 8000
```

The literal command `uvicorn main --reload --port 8000` doesn't start with the installed uvicorn 0.54, which requires the `module:attribute` form (`main:app`). Interactive API docs: http://localhost:8000/docs. CORS allows the Vite dashboard at `http://localhost:5173` and `http://127.0.0.1:5173`. Set `CAMPUS_CUSTOMS_FRONTEND_ORIGINS` (comma-separated) to allow other origins.

**Start the dashboard** (Problem 8): `cd frontend && npm run dev` opens http://localhost:5173. Its backend URL defaults to `http://localhost:8000`; set `VITE_API_BASE_URL` in `frontend/.env` to change it. Design notes are in `output/design.md`.

Every route reads or writes shop data through the MCP server, never SQLite directly.

- `GET /api/health`: backend up, model name, database file, MCP tool count, active runs.
- `GET /api/tickets`: tickets 101, 102, 103 with status (`open` / `pending_approval` / `closed`), `resolved`, and any active run ID.
- `POST /api/tickets/{ticket_id}/run`: start the agent team on one ticket in the background. Optional body `{"instructions": "..."}` carries the person's decisions to every agent. Returns `202` with a `run_id`, or `409` if that ticket already has a run or a reset is happening.
- `GET /api/runs`: runs started since the backend started (or since the last reset), with status.
- `GET /api/runs/{run_id}`: one run's status and, when finished, its full structured result (Boss report, delegations, MCP calls, pending actions, token usage).
- `GET /api/events?after={event_id}&limit=&run_id=&ticket_id=`: incremental audit events (agent messages, delegations, MCP tool names, arguments, and results). Each has a stable `event_id`; pass `next_cursor` back as `after`.
- `GET /api/pending-actions?status=pending`: payments and purchases the agents prepared, waiting for a person.
- `POST /api/pending-actions/{action_id}/approve`: a person approves one prepared action (`{"approved_by", "confirm_amount"}`). The server re-validates it and executes it once through MCP in one transaction. Returns `409` on an amount mismatch, an action already decided, cash that would go negative, or a blocked vendor.
- `POST /api/pending-actions/{action_id}/reject`: a person rejects one prepared action, so it can never execute.
- `GET /api/cash`: the checking account's current balance from `cash_accounts`.
- `POST /api/reset`: with `{"confirm": "RESET"}`, restores `campus_customs_new.db` from `campus_customs.db` and clears pending actions and finished run state. Refused (`409`) while runs or approvals are active. It appends a `database_reset` audit event and leaves the original database and audit history untouched.

## Dashboard (`frontend/`)

React + Vite + TypeScript. The full design rationale is in `output/design.md`.

- **Ticket spike** (left): tickets 101–103 with stamps: ● Open / ⏸ Awaiting approval / ✓ Resolved. "Resolved" appears only when the backend returns `resolved: true`.
- **Workspace** (center):
  - the selected ticket's facts and the **Start agent team** button, which never runs on page load and is disabled while a run is active;
  - the optional **Decisions for the team** field (sent as `instructions`);
  - a run picker, the five agent panels (each with its name, station, glyph, patterned strip, state, filed report, and evidence list from the audit trail), and the activity log fed by `GET /api/events` with a cursor.
- **Till** (right): the checking balance from `GET /api/cash`, updated only after the backend confirms. Below it, the pending payments and purchases, each with **Review & approve / reject**. The person must type their name, and the exact amount is sent as `confirm_amount`.
- `?ticket=103` preselects a ticket (used for the screenshots). Polling runs every 1.5 s only while a run is active (every 10 s in a background tab) and stops when nothing is running.

## Final run (Problem 9)

Run label `problem9-full-run-2026-10-11`: audit entries 84–484, starting with the `database_reset` at entry 84. Everything was run from the dashboard against the working database after a reset, and the human approved each action there.

| Ticket | Final status | Approved actions | Cash change |
|---|---|---|---|
| 101 | `closed` | #1 invoice 501 −$840.00 (payment 1); #2 1 tee $8.00 (PO 1, order only) | −$840.00 |
| 102 | `closed` | #3 lease 1 rent −$2,400.00 (payment 2) | −$2,400.00 |
| 103 | `closed` | #4 12 hoodies $264.00 (PO 2, order only); owner's 10% discount decision | $0.00 |

Checking went from $3,400.00 at the start to $160.00 at the end, which matches `cash_accounts`. Evidence: `desk_tickets.html` (Actual and Cash tabs), `resolved_tickets.json`, and `resolved_board.html` (real dashboard screenshots in `output/screenshots/`).
