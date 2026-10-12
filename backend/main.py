"""FastAPI backend for the Campus Customs dashboard.

Start it from the backend/ directory (with the project's .venv):

    ../.venv/bin/uvicorn main:app --reload --port 8000

Every shop read and write goes through the campus-customs MCP server
(mcp_server/server.py), over one long-lived stdio session for the routes and a
separate session per agent run. Money only moves in POST
/api/pending-actions/{id}/approve, which a person triggers from the dashboard.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Started from backend/, so make the project folder importable as the `backend` package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException, Query, status  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic_ai.models import Model  # noqa: E402

from backend import config  # noqa: E402
from backend.audit import AuditLog, AuditLogError, Redactor, clip  # noqa: E402
from backend.models import (  # noqa: E402
    ApprovalResponse,
    ApproveRequest,
    CashResponse,
    EventsResponse,
    PendingActionOut,
    PendingActionsResponse,
    RejectRequest,
    ResetRequest,
    ResetResponse,
    RunInfo,
    RunRequest,
    RunsResponse,
    TicketOut,
    TicketsResponse,
)
from backend.team import mcp_client, run_ticket  # noqa: E402

# The Vite dashboard's origin. CAMPUS_CUSTOMS_FRONTEND_ORIGINS (comma-separated) overrides it,
# e.g. for a second dashboard on another port pointed at an isolated test backend.
FRONTEND_ORIGINS = [o.strip() for o in os.getenv(
    "CAMPUS_CUSTOMS_FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
MAX_EVENTS_PER_PAGE = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class BackendState:
    db_path: Path
    original_db_path: Path
    audit: AuditLog
    model_factory: Callable[[], Model] | None
    limits: config.RunLimits
    mcp: Any = None
    runs: dict[str, RunInfo] = field(default_factory=dict)
    active_by_ticket: dict[int, str] = field(default_factory=dict)
    tasks: set[asyncio.Task] = field(default_factory=set)
    financial_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    resetting: bool = False

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> dict:
        """Call one MCP tool on the shared session; MCP failures become 502s."""
        try:
            result = await self.mcp.call_tool(tool, args or {})
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"MCP tool {tool} failed: {clip(str(exc), 300)}") from exc
        return result.data if result.data is not None else (result.structured_content or {})

    def log(self, event: str, *, ticket_id: int | None, **data: Any) -> None:
        """Append a human/dashboard action to the audit trail."""
        self.audit.append(Redactor()({
            **({"run_label": config.RUN_LABEL} if config.RUN_LABEL else {}),
            "run_id": data.pop("run_id", f"human-{uuid.uuid4().hex[:8]}"),
            "ticket_id": ticket_id,
            "agent": "human",
            "event": event,
            **data,
        }))


def create_app(
    *,
    db_path: Path | None = None,
    original_db_path: Path | None = None,
    audit_path: Path | None = None,
    model_factory: Callable[[], Model] | None = None,
    limits: config.RunLimits = config.DEFAULT_LIMITS,
) -> FastAPI:
    """Build the app. Tests pass isolated database/audit paths and a scripted model."""
    state = BackendState(
        db_path=Path(db_path or config.DB_PATH).resolve(),
        original_db_path=Path(original_db_path or config.ORIGINAL_DB_PATH).resolve(),
        audit=AuditLog(audit_path or config.AUDIT_PATH),
        model_factory=model_factory,
        limits=limits,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        state.mcp = mcp_client(state.db_path, state.original_db_path)
        async with state.mcp:
            yield
            for task in list(state.tasks):  # server shutting down: stop agent runs
                task.cancel()

    app = FastAPI(title="Campus Customs backend", version="1.0", lifespan=lifespan)
    app.state.backend = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    # ------------------------------------------------------------------ helpers

    def ensure_not_resetting() -> None:
        if state.resetting:
            raise HTTPException(status.HTTP_409_CONFLICT, "A database reset is in progress; try again shortly.")

    async def get_action(action_id: int) -> dict:
        got = await state.call("get_pending_action", {"action_id": action_id})
        if not got.get("found"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, got.get("error", f"No pending action {action_id}."))
        return got["action"]

    async def checking_balance() -> float | None:
        accounts = (await state.call("get_cash_balances"))["accounts"]
        return next((a["balance"] for a in accounts if a["name"] == "checking"), None)

    async def execute_run(run: RunInfo) -> None:
        try:
            result = await run_ticket(
                run.ticket_id,
                run_id=run.run_id,
                instructions=run.instructions,
                db_path=state.db_path,
                audit_path=state.audit.path,
                limits=state.limits,
                model=state.model_factory() if state.model_factory else None,
            )
            run.result, run.status, run.error = result, result.status, result.error
        except Exception as exc:  # run_ticket reports its own errors; this catches setup failures
            run.status, run.error = "failed", f"{type(exc).__name__}: {clip(str(exc), 500)}"
        finally:
            run.finished_at = _now()
            state.active_by_ticket.pop(run.ticket_id, None)

    # ------------------------------------------------------------------ routes

    @app.get("/api/health")
    async def health() -> dict:
        """Backend and MCP server are up."""
        tools = await state.mcp.list_tools()
        return {"ok": True, "model": config.MODEL_NAME, "database": state.db_path.name, "mcp_tools": len(tools),
                "active_runs": len(state.active_by_ticket)}

    @app.get("/api/tickets", response_model=TicketsResponse)
    async def list_tickets() -> TicketsResponse:
        """Tickets 101, 102, 103 with their current status (open / pending_approval / closed = resolved)."""
        rows = (await state.call("list_tickets"))["tickets"]
        return TicketsResponse(tickets=[
            TicketOut(**r, active_run_id=state.active_by_ticket.get(r["id"])) for r in rows])

    @app.post("/api/tickets/{ticket_id}/run", response_model=RunInfo, status_code=status.HTTP_202_ACCEPTED)
    async def start_run(ticket_id: int, body: RunRequest | None = None) -> RunInfo:
        """Run the agent team on one ticket in the background; poll GET /api/runs/{run_id}."""
        ensure_not_resetting()
        if (active := state.active_by_ticket.get(ticket_id)):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                {"message": f"Ticket {ticket_id} already has a run in progress.", "run_id": active})
        ids = {t["id"] for t in (await state.call("list_tickets"))["tickets"]}
        if ticket_id not in ids:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No ticket with id={ticket_id}.")
        if state.active_by_ticket.get(ticket_id) or state.resetting:  # re-check after the await
            raise HTTPException(status.HTTP_409_CONFLICT, f"Ticket {ticket_id} is busy; try again.")
        instructions = ((body.instructions if body else None) or "").strip() or None
        run = RunInfo(run_id=uuid.uuid4().hex[:12], ticket_id=ticket_id, status="running",
                      instructions=instructions, started_at=_now())
        state.runs[run.run_id] = run
        state.active_by_ticket[ticket_id] = run.run_id
        task = asyncio.create_task(execute_run(run))
        state.tasks.add(task)
        task.add_done_callback(state.tasks.discard)
        return run

    @app.get("/api/runs", response_model=RunsResponse)
    async def list_runs(ticket_id: int | None = None) -> RunsResponse:
        """Runs started since the backend started (or since the last reset), newest first."""
        runs = [r for r in reversed(state.runs.values()) if ticket_id is None or r.ticket_id == ticket_id]
        return RunsResponse(runs=runs)

    @app.get("/api/runs/{run_id}", response_model=RunInfo)
    async def get_run(run_id: str) -> RunInfo:
        """One run's status, and its full structured result once it finishes."""
        if run_id not in state.runs:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No run with id={run_id!r}.")
        return state.runs[run_id]

    @app.get("/api/events", response_model=EventsResponse)
    async def list_events(
        after: int = Query(-1, ge=-1, description="Return events with event_id greater than this."),
        limit: int = Query(200, ge=1, le=MAX_EVENTS_PER_PAGE),
        run_id: str | None = None,
        ticket_id: int | None = None,
    ) -> EventsResponse:
        """Recent agent events from output/audit_trail.json (messages, delegations, MCP tool calls/results)."""
        try:
            entries = state.audit.read()
        except AuditLogError as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
        events, cursor = [], after
        for event_id in range(after + 1, len(entries)):
            cursor = event_id
            e = entries[event_id]
            if (run_id is None or e.get("run_id") == run_id) and (ticket_id is None or e.get("ticket_id") == ticket_id):
                events.append({"event_id": event_id, **e})
                if len(events) >= limit:
                    break
        return EventsResponse(events=events, next_cursor=cursor, total=len(entries))

    @app.get("/api/pending-actions", response_model=PendingActionsResponse)
    async def list_pending_actions(
        status_filter: str | None = Query(None, alias="status", pattern="^(pending|executed|rejected)$"),
    ) -> PendingActionsResponse:
        """Payments and purchases agents prepared, newest first (filter with ?status=pending)."""
        got = await state.call("list_pending_actions", {"status": status_filter})
        return PendingActionsResponse(actions=[PendingActionOut(**a) for a in got["actions"]])

    @app.post("/api/pending-actions/{action_id}/approve", response_model=ApprovalResponse)
    async def approve_action(action_id: int, body: ApproveRequest) -> ApprovalResponse:
        """A person approves one prepared action; the server re-validates it and executes it once, via MCP."""
        ensure_not_resetting()
        if state.financial_lock.locked():
            raise HTTPException(status.HTTP_409_CONFLICT, "Another financial operation is in progress; try again.")
        async with state.financial_lock:
            ensure_not_resetting()
            action = await get_action(action_id)
            if action["status"] != "pending":
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"Action {action_id} is already {action['status']!r}; it can only be approved once.")
            if abs(action["amount"] - body.confirm_amount) > 0.005:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"confirm_amount {body.confirm_amount:.2f} does not match the prepared amount "
                                    f"{action['amount']:.2f}; reload the action before approving.")
            audit_id = f"approval-{action_id}-{uuid.uuid4().hex[:6]}"
            state.log("approval_requested", ticket_id=action.get("ticket_id"), run_id=audit_id,
                      action_id=action_id, kind=action["kind"], amount=action["amount"], ref_id=action["ref_id"],
                      approved_by=body.approved_by, prepared_by=action["prepared_by"])
            out = await state.call("approve_pending_action", {
                "action_id": action_id, "approved_by": body.approved_by, "expected_amount": body.confirm_amount})
            if not out.get("ok"):
                state.log("approval_refused", ticket_id=action.get("ticket_id"), run_id=audit_id,
                          action_id=action_id, error=out.get("error"))
                raise HTTPException(status.HTTP_409_CONFLICT, out.get("error", "Approval refused."))
            balance = await checking_balance()
            state.log("approval_executed", ticket_id=action.get("ticket_id"), run_id=audit_id,
                      action_id=action_id, kind=action["kind"], approved_by=body.approved_by,
                      result=out["result"], checking_balance_after=balance)
            return ApprovalResponse(action=PendingActionOut(**await get_action(action_id)),
                                    result=out["result"], checking_balance=balance)

    @app.post("/api/pending-actions/{action_id}/reject", response_model=ApprovalResponse)
    async def reject_action(action_id: int, body: RejectRequest) -> ApprovalResponse:
        """A person rejects one prepared action so it can never execute."""
        ensure_not_resetting()
        async with state.financial_lock:
            action = await get_action(action_id)
            out = await state.call("reject_pending_action", {
                "action_id": action_id, "rejected_by": body.rejected_by, "note": body.note})
            if not out.get("ok"):
                raise HTTPException(status.HTTP_409_CONFLICT, out.get("error", "Reject refused."))
            state.log("action_rejected", ticket_id=action.get("ticket_id"), action_id=action_id,
                      kind=action["kind"], amount=action["amount"], rejected_by=body.rejected_by, note=body.note)
            return ApprovalResponse(action=PendingActionOut(**await get_action(action_id)))

    @app.get("/api/cash", response_model=CashResponse)
    async def cash() -> CashResponse:
        """The checking account's current balance from cash_accounts."""
        accounts = (await state.call("get_cash_balances"))["accounts"]
        checking = next((a for a in accounts if a["name"] == "checking"), None)
        if checking is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No 'checking' row in cash_accounts.")
        return CashResponse(account="checking", balance=checking["balance"], date=checking["date"])

    @app.post("/api/reset", response_model=ResetResponse)
    async def reset(body: ResetRequest) -> ResetResponse:
        """Restore campus_customs_new.db from campus_customs.db. Refused while runs or approvals are active."""
        if state.active_by_ticket:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                {"message": "Agent runs are in progress; wait for them to finish.",
                                 "active_runs": dict(state.active_by_ticket)})
        if state.resetting or state.financial_lock.locked():
            raise HTTPException(status.HTTP_409_CONFLICT, "A financial operation or reset is in progress.")
        state.resetting = True
        try:
            async with state.financial_lock:
                pending = (await state.call("list_pending_actions", {"status": "pending"}))["count"]
                out = await state.call("reset_working_database", {"confirm": body.confirm})
                if not out.get("ok"):
                    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, out.get("error", "Reset failed."))
                cleared_runs = len(state.runs)
                state.runs.clear()
                balance = next((a["balance"] for a in out["cash_accounts"] if a["name"] == "checking"), None)
                statuses = {str(k): v for k, v in out["ticket_statuses"].items()}
                state.log("database_reset", ticket_id=None, reset_from=out["reset_from"], reset_to=out["reset_to"],
                          cleared_pending_actions=pending, cleared_runs=cleared_runs,
                          checking_balance=balance, ticket_statuses=statuses)
        finally:
            state.resetting = False
        return ResetResponse(ok=True, cleared_pending_actions=pending, cleared_runs=cleared_runs,
                             checking_balance=balance, ticket_statuses=statuses)

    return app


app = create_app()
