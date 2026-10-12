# Campus Customs Dashboard: Design

The dashboard (`frontend/`, React + Vite + TypeScript) is an **operations desk** for a small campus shop. It is styled like the back office behind the counter: paper tickets on a spike, staff with name badges, a cash drawer, and slips waiting for a signature. Every number and message on screen comes from the Problem 7 backend (`http://localhost:8000` by default, set with `VITE_API_BASE_URL`). Nothing is filled in on the client.

## Layout

Three columns on a wide screen, read left to right in the order the work flows:

| Column | Name on screen | What it shows |
|---|---|---|
| Left | **Ticket spike** | Tickets 101, 102, and 103 as paper stubs, each with its number, type, subject, item line, and a status stamp. The selected stub has a navy edge. An "agents working…" tag marks tickets with an active run. |
| Center (widest) | **Selected-ticket workspace** | <ul><li>A ticket card: facts from `GET /api/tickets`, the status stamp, and the large **Start agent team** button.</li><li>A run bar: run picker, run status badge, token count.</li><li>**The team on this run**: five agent panels.</li><li>The **Activity log**.</li></ul> |
| Right | **Till** | <ul><li>The **Cash drawer**: checking balance on a register-style display.</li><li>**Awaiting your signature**: pending payments and purchases, each with an approve button.</li><li>A short log of who signed what on the selected ticket.</li></ul> |

On narrower screens:
- **Below 1,240 px:** the till drops under the workspace as a two-part row (drawer, then slips). A compact "$X checking · N to sign" link appears in the top bar and jumps to it, so cash and approvals stay one tap away.
- **Below 820 px:** everything stacks in one column, and the stubs flow into a grid.

## How the agents are distinguished

Each of the five agents is identified **four ways**, so no one depends on color:

1. **Name and station label:**
   - Boss (*Desk lead*)
   - Inventory (*Stockroom*)
   - Accounting (*Ledger*)
   - Facilities (*Premises*)
   - Customer Service (*Front counter*)

   Each also has a one-line duty taken from its prompt file.
2. **A unique glyph shape:** star (Boss), box (Inventory), ledger book (Accounting), house (Facilities), speech bubble (Customer Service). The same glyph labels the agent everywhere: its panel, every activity-log entry, and the log filter chips. The desk runner (an arrow) and the human approver (a pen nib) get glyphs too.
3. **A patterned "lanyard" strip** on the left edge of each panel: solid (Boss), horizontal bars (Inventory), dots (Accounting), diagonal stripes (Facilities), vertical stripes (Customer Service). The patterns stay distinct in grayscale.
4. **A color**, used for the name, badge, and strip. It is reinforcement only.

Each panel shows a **state chip** in words and with a border:
- *Standing by*: no run is shown yet
- *Not involved*: the agent didn't take part in this run, and the panel is dimmed
- *Working*: shown with a pulsing dot and a highlighted outline
- *Done*

When an agent finishes, its panel shows its filed report summary and report status. Below that is an **evidence list** built only from audit events: the MCP tools it called (with counts and refusals), whom it delegated to, who asked it, and any pending action it prepared. That is the "short, evidence-based summary".

## Activity log

The log has one line per meaningful audit event, newest at the bottom, each tagged with the agent's glyph and name:

- agent messages, shown as quoted text
- decisions to use tools
- MCP tool calls with their arguments, and results with a **Show raw** expander for the full JSON
- delegations: who → whom, with the task and the findings passed along
- reports back, refused delegations, and guardrail blocks
- prepared pending actions
- the run's end, with token usage

Low-level loop plumbing (raw prompts, model-request frames) is hidden to keep it readable. Chips filter the log to one agent. Updates are announced politely to screen readers while a run is live.

**How events are fetched:** events come from `GET /api/events` using its cursor. The dashboard loads a ticket's history once, then polls every 1.5 s only while a run is active. In a background tab it polls every 10 s instead, and it refreshes right away when the tab becomes visible again. Polling stops completely when no run is active.

Events are de-duplicated by `event_id` and grouped by `run_id`, so each run's activity stays with its own ticket and run. Earlier runs stay available from the run picker, and human approval events are kept out of agent runs.

## How resolved tickets are presented

Status is shown as a **rubber stamp**, with a symbol and text as well as color:
- **● Open**: blue
- **⏸ Awaiting approval**: amber, dashed border
- **✓ Resolved**: green, thick border, tilted further

"Resolved" appears **only when the backend returns `resolved: true`** (status `closed`). A finished, failed, or limit-stopped run never marks a ticket resolved. After a run ends, the dashboard re-reads the tickets. If the run has ended but the backend still lists the ticket as open or awaiting approval, a note says so explicitly. Run outcome has its own badge (Running / Finished · needs a human / Failed / Stopped · limit reached), kept separate from the ticket stamp.

## How cash and approvals are presented

**Cash drawer:**
- The checking balance from `GET /api/cash` sits in a dark-green drawer, in a large monospaced, register-style readout, labeled "checking · as of {date} · from the backend".
- The balance **changes only after the backend confirms**. After a successful approval the dashboard re-reads `/api/cash`, and the readout flashes once so the change is noticed.
- A **Recount** button re-reads it on demand.

**Approval slips:** each pending action (`GET /api/pending-actions?status=pending`) is a paper slip with a double rule on top, showing:
- the kind (invoice payment / rent payment / restock purchase) and action number
- the amount
- the **purpose** (the agent's stated reason)
- the target (invoice, lease and due date, or vendor and items) and the account
- the related ticket and which agent prepared it

The hint above the slips says plainly that agents can only prepare these.

**Approving:**
1. **Review & approve** opens a native modal dialog. It traps focus and Esc cancels.
2. The dialog repeats the amount, warns that money will leave checking (or that a purchase order will be recorded), and asks the person to **sign with their name**. The input is styled in italic serif, like a signature.
3. Only then does the dialog's **Approve $X** button send `POST /api/pending-actions/{id}/approve` with the exact amount shown.

The button is disabled while a request is in flight, and a ref guard blocks double submissions. Backend refusals (wrong amount, an agent name used as approver, an action already approved, a blocked vendor, cash that would go negative) are shown in the dialog and on the slip. Nothing is approved automatically, and no run starts on page load.

## Why these design choices

- **The shop's own metaphors.** Ticket stubs, rubber stamps, a till, and signed slips are what a shop desk actually uses, so each control's meaning is obvious: stamps are status, a drawer is money, a signature is human approval. It also gives the app one coherent identity instead of generic cards.
- **The approval path feels deliberate.** Payments are the one irreversible thing on screen, so they look different (paper slips beside the green drawer) and need two steps plus a typed name. That matches the backend rule that only a person, never an agent, approves.
- **Status and run outcome are separate on purpose.** The workspace never lets "the run finished" read as "the ticket is solved". The stamp follows the backend's ticket status, and the run badge follows the run.
- **Evidence over narration.** Agent panels show the report the agent actually filed plus a mechanical evidence list from the audit trail, so a reviewer can trust the summary and trace it in the log.
- **Accessible by construction.**
  - Agents and statuses use shape, pattern, and text, not color alone.
  - Every control is a native button, select, input, or dialog, with visible focus rings.
  - Arrow keys move through the ticket list.
  - Live regions announce new activity and balance changes.
  - Reduced-motion preferences turn off the pulse and flash animations.
- **Quiet when idle.** Nothing polls when no run is active. That keeps the backend and the audit trail free of pointless requests and makes the "live" state meaningful when it appears.
