# Campus Customs Multi-Agent Operations (Homework 5)

A five-agent PydanticAI team (Boss, Inventory, Accounting, Facilities, Customer Service) handles the shop's tickets. Every shop read and write goes through a FastMCP server backed by SQLite. A FastAPI backend runs the team and exposes a human-approval flow, and a React dashboard lets a person start runs, watch the agents, and approve payments and purchases. All model calls use **gpt-6-luna through Portkey**.

This repository contains the **completed** run: tickets 101, 102, and 103 are `closed` in `data/campus_customs_new.db`, and checking went from $3,400.00 to $160.00. The evidence is in `output/`.

## Repository layout

| Path | What it is |
|---|---|
| `data/campus_customs.db` | Original database. It is never modified. |
| `data/campus_customs_new.db` | Working database, holding the completed run's final state |
| `mcp_server/server.py`, `mcp_server/README.md` | FastMCP server (19 tools) and its documentation |
| `backend/` | Agent team (`team.py`, `models.py`, `config.py`, `guardrails.py`, `audit.py`), FastAPI app (`main.py`), and one prompt per agent in `backend/prompts/` (`boss.md`, `inventory.md`, `accounting.md`, `facilities.md`, `customer_service.md`) |
| `frontend/` | React + Vite + TypeScript dashboard (`package-lock.json` included) |
| `tests/` | pytest suite (uses throwaway database copies) |
| `output/` | Deliverables: `harness.md`, `mcp_smoke.json`, `desk_tickets.html`, `design.md`, `resolved_tickets.json`, `resolved_board.html` with `screenshots/`, `audit_trail.json`, `github_url.txt` |
| `AI_prompts.md` | Every prompt used, problem by problem |
| `.mcp.json` | MCP connection for Claude Code (project scope) |
| `.env.example` | Environment variables, with placeholder values |

## 1. Setup

You need Python 3.11 or newer (developed on 3.14) and Node.js 20 or newer (developed on 24).

```bash
# from the repository root
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip install -r requirements.txt

cd frontend && npm ci && cd ..                # installs exactly what package-lock.json lists
```

## 2. Environment variables

```bash
cp .env.example .env
```

Then edit `.env` and set `PORTKEY_API_KEY` to your own Portkey key.

- **Where the key is read from:** `backend/config.py` loads the nearest `.env`: this folder first, then its parent folders. The key is never logged or written to the audit trail, and the MCP server process is started without it.
- **The model:** fixed to `gpt-6-luna` in `backend/config.py`.
- **Optional variables:** listed in `.env.example`. They point the app at other database or audit files (used by the tests), change the allowed dashboard origins, or label a run's audit entries.
- **The dashboard's backend URL:** defaults to `http://localhost:8000`. To change it, copy `frontend/.env.example` to `frontend/.env` and set `VITE_API_BASE_URL`.

## 3. MCP server

The server talks over stdio and opens `data/campus_customs_new.db` (resolved relative to `server.py`, so it works from any directory).

- **Run it by hand** (it waits for an MCP client on stdin/stdout):

  ```bash
  .venv/bin/python mcp_server/server.py
  ```

- **From the backend:** nothing to do. The backend and agent team start their own server process automatically.
- **From Claude Code:** `.mcp.json` registers it as `campus-customs` using the relative paths `.venv/bin/python` and `mcp_server/server.py`.
  1. Open Claude Code in this folder.
  2. Approve the project MCP server when prompted.
  3. Run `/mcp` to confirm it is connected.

  On Windows, change `command` to `.venv\\Scripts\\python.exe`.

See `mcp_server/README.md` for all 19 tools.

## 4. FastAPI backend

```bash
cd backend
../.venv/bin/uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs. The routes are listed in `output/harness.md`. Note that `uvicorn main` without `:app` is rejected by uvicorn 0.54.

## 5. React dashboard

```bash
cd frontend
npm run dev        # http://localhost:5173
```

The backend allows the `http://localhost:5173` origin. Nothing runs or gets approved on page load:
1. Select a ticket.
2. Optionally type decisions for the team (for example, an approved discount).
3. Press **Start agent team**.
4. Approve or reject prepared payments and purchases in the right-hand panel, signing with your name.

## 6. Starting a fresh three-ticket run

> **Warning:** both options below **replace the completed working state**: ticket statuses, payments, purchase orders, pending actions, and the $160 balance. The original database is never changed. `output/audit_trail.json` keeps all earlier entries either way. If you want to keep the completed state, back up `data/campus_customs_new.db` first.

**Option A: the reset route** (backend running, with no active runs or approvals):

```bash
curl -X POST http://localhost:8000/api/reset -H "Content-Type: application/json" -d '{"confirm":"RESET"}'
```

**Option B: copy the file** (backend stopped):

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

**Then run the tickets:** run 101, 102, and 103 from the dashboard. Each run that prepares a payment or purchase stops at `pending_approval` until a person approves it. Run the ticket again afterwards so Boss can see the executed action and close it. To label the new run's audit entries, start the backend with `CAMPUS_CUSTOMS_RUN_LABEL=<label>`.

## 7. Checks

```bash
.venv/bin/python -m pytest              # 42 tests; they use temporary database copies, never data/
cd frontend && npm run build            # TypeScript check and production build
```

To view the evidence pages, open them straight from disk. No server is needed.
- `output/desk_tickets.html`: Expected plans, Actual results, Cash reconciliation, and Reflection.
- `output/resolved_board.html`: real dashboard screenshots of the three resolved tickets.

## Safety rules (summary)

- Agents can only **prepare** payments and purchases. A person approves each one on the dashboard. The server then re-checks the amount and the related records and executes it once, in a transaction.
- Cash can never go negative.
- A ticket can't be closed while it still has a pending action.
- Each agent sees only its own MCP tools.
- Customer names are hidden from roles that don't need them and redacted in the audit trail.
- Model requests, tokens, tool calls, delegation depth, retries, and run time are all capped.

Details are in `output/harness.md`.
