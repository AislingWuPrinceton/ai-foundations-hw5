"""Shared data types for the Campus Customs agent team."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
ROLES: tuple[Role, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")

ROLE_TITLES: dict[str, str] = {
    "boss": "Boss",
    "inventory": "Inventory",
    "accounting": "Accounting",
    "facilities": "Facilities",
    "customer_service": "Customer Service",
}

ReportStatus = Literal["completed", "needs_human", "blocked", "failed"]
RunStatus = Literal["completed", "needs_human", "blocked", "failed", "limit_exceeded"]
PendingKind = Literal["invoice_payment", "rent_payment", "restock_purchase"]


class Finding(BaseModel):
    """One fact an agent relies on, with where it came from."""

    fact: str = Field(description="A specific fact, with real numbers/IDs from a tool result.")
    source: str = Field(description="The MCP tool that returned it, or 'delegation:<role>'.")


class ApprovalRequest(BaseModel):
    """An action that must wait for a named human."""

    action: str = Field(description="What a human must approve, in one sentence.")
    action_id: int | None = Field(
        default=None, description="ID of the pending action you prepared for it (prepare_payment/prepare_purchase)."
    )
    tool: str | None = Field(default=None, description="The MCP tool that would carry it out, if any.")
    ref_id: int | None = Field(default=None, description="invoice_id / lease_id / ticket id it applies to.")
    amount: float | None = Field(default=None, description="Dollar amount involved, if any.")
    reason: str = Field(description="Why it needs a human.")


class AgentReport(BaseModel):
    """Structured result every agent returns (to the runner or to the agent that delegated)."""

    role: Role
    ticket_id: int
    status: ReportStatus = Field(
        description="completed = your part is done; needs_human = waiting on a human approval or decision; "
        "blocked = cannot proceed (e.g. missing record or rule); failed = an error stopped you."
    )
    summary: str = Field(description="Two to four sentences on what you found and did.")
    findings: list[Finding] = Field(default_factory=list)
    actions_taken: list[str] = Field(
        default_factory=list, description="Data changes actually made through MCP tools (empty if none)."
    )
    approvals_needed: list[ApprovalRequest] = Field(default_factory=list)
    missing_info: list[str] = Field(
        default_factory=list, description="Facts or shop rules you needed but could not find."
    )
    customer_reply_draft: str | None = Field(
        default=None, description="Draft reply to the requester (Customer Service and Boss only). Never sent."
    )


class DelegationRecord(BaseModel):
    """One hand-off between agents, kept for the run result and the audit trail."""

    index: int
    from_role: Role
    to_role: Role
    depth: int
    chain: list[Role]
    task: str
    findings_passed: list[str] = Field(default_factory=list)
    status: Literal["running", "done", "refused", "error"] = "running"
    refused_reason: str | None = None
    report: AgentReport | None = None


class ToolCallRecord(BaseModel):
    """One MCP tool call (or a call the guardrails stopped before it reached MCP)."""

    agent: Role | Literal["runner"]
    tool: str
    args: dict[str, Any]
    outcome: Literal["ok", "error", "blocked", "duplicate_in_run"]
    result: Any = None


class UsageSummary(BaseModel):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0


class TicketRunResult(BaseModel):
    """What run_ticket() returns for one ticket."""

    run_id: str
    ticket_id: int
    model: str
    status: RunStatus
    boss_report: AgentReport | None = None
    delegations: list[DelegationRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    pending_actions: list[dict[str, Any]] = Field(
        default_factory=list, description="Pending actions prepared in this run, waiting for a human on the dashboard."
    )
    usage: UsageSummary = Field(default_factory=UsageSummary)
    seconds: float = 0.0
    error: str | None = None


# --------------------------------------------------------------------------- HTTP API (backend/main.py)

RunState = Literal["running", "completed", "needs_human", "blocked", "failed", "limit_exceeded"]
ActionStatus = Literal["pending", "executed", "rejected"]


class TicketOut(BaseModel):
    id: int
    type: str
    subject: str
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    status: str = Field(description="open, pending_approval, or closed")
    resolved: bool = Field(description="True when status is 'closed'.")
    created_at: str
    active_run_id: str | None = Field(default=None, description="Run currently working on this ticket, if any.")


class TicketsResponse(BaseModel):
    tickets: list[TicketOut]


class RunRequest(BaseModel):
    """Optional body for POST /api/tickets/{id}/run."""

    instructions: str | None = Field(
        default=None, max_length=1000,
        description="Decisions a person typed on the dashboard (e.g. an approved discount); shown to every agent.")


class RunInfo(BaseModel):
    run_id: str
    ticket_id: int
    status: RunState
    instructions: str | None = None
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    result: TicketRunResult | None = None


class RunsResponse(BaseModel):
    runs: list[RunInfo]


class EventsResponse(BaseModel):
    events: list[dict[str, Any]] = Field(description="Audit entries, each with a stable integer event_id.")
    next_cursor: int = Field(description="Pass as ?after= next time to get only newer events.")
    total: int = Field(description="Number of entries in the audit trail.")


class PendingActionOut(BaseModel):
    id: int
    kind: PendingKind
    ticket_id: int | None = None
    ref_id: int
    account: str | None = None
    amount: float
    due_date: str | None = None
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    reason: str
    prepared_by: str
    prepared_at: str
    status: ActionStatus
    decided_by: str | None = None
    decided_at: str | None = None
    decision_note: str | None = None
    result: dict[str, Any] | None = None


class PendingActionsResponse(BaseModel):
    actions: list[PendingActionOut]


class ApproveRequest(BaseModel):
    """Sent only by the dashboard when a person clicks Approve."""

    approved_by: str = Field(min_length=1, max_length=80, description="The approving person's name.")
    confirm_amount: float = Field(gt=0, description="The amount the person saw and approved; must match exactly.")


class RejectRequest(BaseModel):
    rejected_by: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


class ApprovalResponse(BaseModel):
    action: PendingActionOut
    result: dict[str, Any] | None = None
    checking_balance: float | None = None


class CashResponse(BaseModel):
    account: str
    balance: float
    date: str


class ResetRequest(BaseModel):
    confirm: Literal["RESET"] = Field(description="Must be exactly 'RESET'.")


class ResetResponse(BaseModel):
    ok: bool
    cleared_pending_actions: int
    cleared_runs: int
    checking_balance: float | None = None
    ticket_statuses: dict[str, str]
