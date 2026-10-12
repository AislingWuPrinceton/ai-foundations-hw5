"""The Campus Customs agent team: Boss, Inventory, Accounting, Facilities, and
Customer Service.

How a ticket run works
  1. run_ticket() opens one MCP session to mcp_server/server.py (stdio) and
     reads the ticket through the get_ticket MCP tool.
  2. The Boss agent runs first. Every agent is a PydanticAI agent loop
     (agent.iter), and every loop node is appended to the audit trail as it
     happens.
  3. Any agent can call delegate(to_role, task, findings) to run another agent.
     The delegate gets the ticket context, the caller's findings, and the chain
     so far, and returns a structured AgentReport. Cycles, depth, and the
     total number of delegations are capped.
  4. Agents get shop facts only from MCP tools. Each role sees a filtered
     subset of the server's tools, and every call passes through
     _guard_tool_call() (permissions, prepare-only money actions, duplicate
     writes, audit logging) before it reaches the server.
  5. Model requests, tokens, and tool calls are counted on one RunUsage shared
     by the whole team and checked against UsageLimits; the run also has a
     wall-clock timeout.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import CallToolFunc, MCPToolset
from pydantic_ai.messages import RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage, UsageLimits

from . import config
from .audit import AuditLog, Redactor, clip
from .guardrails import (
    CUSTOMER_TICKET_TYPES,
    PREPARE_TOOLS,
    ROLE_TOOLS,
    WRITE_TOOLS,
    check_customer_reply,
    check_delegation,
    check_tool_permission,
    ticket_context_for,
)
from .models import (
    ROLE_TITLES,
    ROLES,
    AgentReport,
    DelegationRecord,
    Role,
    TicketRunResult,
    ToolCallRecord,
    UsageSummary,
)


# --------------------------------------------------------------------------- run state


@dataclass
class TeamRun:
    """State shared by every agent working on one ticket."""

    run_id: str
    ticket_id: int
    audit: AuditLog
    redact: Redactor
    limits: config.RunLimits
    model: Model
    toolset: MCPToolset
    usage: RunUsage = field(default_factory=RunUsage)
    ticket: dict[str, Any] = field(default_factory=dict)
    ticket_actions: list[dict[str, Any]] = field(default_factory=list)  # actions on this ticket before the run
    instructions: str | None = None  # decisions a person typed on the dashboard for this run
    delegations: list[DelegationRecord] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    write_results: dict[str, Any] = field(default_factory=dict)
    started: float = field(default_factory=time.perf_counter)
    seq: int = 0

    @property
    def usage_limits(self) -> UsageLimits:
        return UsageLimits(
            request_limit=self.limits.max_model_requests,
            total_tokens_limit=self.limits.max_total_tokens,
            tool_calls_limit=self.limits.max_tool_calls,
        )

    def log(self, event: str, agent: str, **data: Any) -> None:
        """Append one redacted entry to the audit trail."""
        self.seq += 1
        self.audit.append(self.redact({
            **({"run_label": config.RUN_LABEL} if config.RUN_LABEL else {}),
            "run_id": self.run_id,
            "seq": self.seq,
            "t_ms": round((time.perf_counter() - self.started) * 1000),
            "ticket_id": self.ticket_id,
            "agent": agent,
            "event": event,
            **data,
        }))

    def usage_summary(self) -> UsageSummary:
        u = self.usage
        return UsageSummary(
            requests=u.requests,
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            total_tokens=(u.input_tokens or 0) + (u.output_tokens or 0),
            tool_calls=u.tool_calls or 0,
        )


@dataclass
class AgentDeps:
    team: TeamRun
    role: Role
    chain: list[Role]

    @property
    def depth(self) -> int:
        return len(self.chain) - 1


# --------------------------------------------------------------------------- MCP connection


def _server_env(db_path: Path | None, original_db_path: Path | None = None) -> dict[str, str]:
    """Environment for the MCP server process: no API key, and the database files to use."""
    env = {k: v for k, v in os.environ.items() if k != "PORTKEY_API_KEY"}
    env["CAMPUS_CUSTOMS_DB"] = str(Path(db_path or config.DB_PATH).resolve())
    env["CAMPUS_CUSTOMS_ORIGINAL_DB"] = str(Path(original_db_path or config.ORIGINAL_DB_PATH).resolve())
    return env


def mcp_client(db_path: Path | None = None, original_db_path: Path | None = None) -> Client:
    """A FastMCP client that starts mcp_server/server.py over stdio."""
    return Client(PythonStdioTransport(
        config.MCP_SERVER_SCRIPT,
        env=_server_env(db_path, original_db_path),
        cwd=str(config.PROJECT_DIR),
        python_cmd=sys.executable,
    ))


def build_toolset(db_path: Path | None = None, limits: config.RunLimits = config.DEFAULT_LIMITS) -> MCPToolset:
    return MCPToolset(
        mcp_client(db_path),
        process_tool_call=_guard_tool_call,
        max_retries=1,
        tool_error_behavior="retry",
    )


def _role_toolset(team: TeamRun, role: Role):
    allowed = ROLE_TOOLS[role]
    return team.toolset.filtered(lambda _ctx, tool_def: tool_def.name in allowed)


def _record(team: TeamRun, agent: str, tool: str, args: dict, outcome: str, result: Any) -> None:
    team.tool_calls.append(ToolCallRecord(agent=agent, tool=tool, args=args, outcome=outcome, result=result))


async def _guard_tool_call(ctx: RunContext[AgentDeps], call_tool: CallToolFunc, name: str, args: dict[str, Any]) -> Any:
    """Every agent MCP call passes through here before it reaches the server."""
    deps = ctx.deps
    team, role = deps.team, deps.role
    args = dict(args)
    log = lambda event, **d: team.log(event, role, depth=deps.depth, chain=deps.chain, tool=name, **d)  # noqa: E731

    if (err := check_tool_permission(role, name)):
        log("guardrail_block", args=args, reason=err)
        _record(team, role, name, args, "blocked", err)
        return {"ok": False, "blocked": True, "error": err}

    if name in PREPARE_TOOLS:
        # Who prepared it and for which ticket come from the run, never from the model.
        args["prepared_by"] = role
        args["ticket_id"] = team.ticket_id

    if name == "update_ticket_status" and args.get("status") == "closed":
        still_pending = sorted({a["id"] for a in [*team.ticket_actions, *team.pending_actions] if a["status"] == "pending"})
        if still_pending:
            err = (f"Ticket can't be closed: pending action(s) {still_pending} still wait for a human on the dashboard. "
                   "Use pending_approval instead.")
            log("guardrail_block", args=args, reason=err)
            _record(team, role, name, args, "blocked", err)
            return {"ok": False, "blocked": True, "error": err}

    if (name == "update_ticket_status" and args.get("status") == team.ticket.get("status")
            and not any(t.tool in PREPARE_TOOLS and t.outcome == "ok" for t in team.tool_calls)):
        result = {"ok": True, "changed": False,
                  "message": f"Ticket is already {args.get('status')!r} and nothing changed in this run "
                             "(no new pending action), so no status update or note was added."}
        log("duplicate_write_skipped", args=args, reason=result["message"])
        _record(team, role, name, args, "duplicate_in_run", result)
        return result

    key = f"{name}:{json.dumps(args, sort_keys=True)}"
    if name in WRITE_TOOLS and key in team.write_results:
        log("duplicate_write_skipped", args=args)
        result = {"duplicate_in_run": True, "previous_result": team.write_results[key],
                  "message": "This exact change was already made in this run; it was not repeated."}
        _record(team, role, name, args, "duplicate_in_run", result)
        return result

    log("mcp_tool_call", args=args)
    try:
        result = await call_tool(name, args)
    except Exception as exc:
        log("mcp_tool_error", args=args, error=clip(str(exc), 600))
        _record(team, role, name, args, "error", str(exc))
        raise
    ok = not (isinstance(result, dict) and (result.get("ok") is False or result.get("found") is False))
    log("mcp_tool_result", args=args, ok=ok, result=clip(result))
    _record(team, role, name, args, "ok" if ok else "error", result)
    if name in WRITE_TOOLS and isinstance(result, dict) and result.get("ok"):
        team.write_results[key] = result
    if name in PREPARE_TOOLS and isinstance(result, dict) and result.get("ok"):
        action = result["action"]
        if all(p["id"] != action["id"] for p in team.pending_actions):
            team.pending_actions.append(action)
        log("pending_action_prepared", action_id=action["id"], kind=action["kind"], amount=action["amount"],
            already_pending=result.get("already_pending", False))
    return result


async def _runner_call(team: TeamRun, name: str, args: dict[str, Any]) -> Any:
    """An MCP call made by the runner itself (not by an agent), still logged."""
    team.log("mcp_tool_call", "runner", tool=name, args=args)
    result = await team.toolset.direct_call_tool(name, args)
    ticket = result.get("ticket") if isinstance(result, dict) else None
    if ticket and ticket.get("type") in CUSTOMER_TICKET_TYPES:  # register before anything is logged
        team.redact.add_customer(ticket.get("requester"), person=ticket.get("type") == "customer_order")
    team.log("mcp_tool_result", "runner", tool=name, args=args, result=clip(result))
    _record(team, "runner", name, args, "ok", result)
    return result


# --------------------------------------------------------------------------- agents


def _load_prompt(role: Role) -> str:
    return (config.PROMPTS_DIR / f"{role}.md").read_text(encoding="utf-8")


def _make_agent(role: Role) -> Agent[AgentDeps, AgentReport]:
    agent: Agent[AgentDeps, AgentReport] = Agent(
        deps_type=AgentDeps,
        output_type=AgentReport,
        instructions=_load_prompt(role),
        name=role,
        retries=config.DEFAULT_LIMITS.max_retries,
        tool_timeout=config.DEFAULT_LIMITS.tool_timeout_seconds,
    )
    agent.tool(retries=0)(delegate)

    @agent.output_validator
    def _validate(ctx: RunContext[AgentDeps], report: AgentReport) -> AgentReport:
        team = ctx.deps.team
        report = report.model_copy(update={"role": ctx.deps.role, "ticket_id": team.ticket_id})
        if team.ticket.get("type") in CUSTOMER_TICKET_TYPES and (err := check_customer_reply(report.customer_reply_draft)):
            team.log("guardrail_block", ctx.deps.role, depth=ctx.deps.depth, reason=err)
            raise ModelRetry(err)
        # A completed report cannot claim payments that never ran.
        if report.status == "completed" and team.pending_actions and ctx.deps.role in ("boss", "accounting", "inventory"):
            raise ModelRetry("Pending actions you prepared are still waiting for human approval; use status "
                             "needs_human and list them under approvals_needed with their action_id.")
        return report

    return agent


async def delegate(ctx: RunContext[AgentDeps], to_role: Role, task: str, findings: list[str] | None = None) -> dict:
    """Hand part of this ticket to another agent and wait for its structured report.

    Args:
        to_role: One of boss, inventory, accounting, facilities, customer_service (not yourself,
            and not an agent already in the delegation chain).
        task: A specific instruction: what to look up, decide, or draft, with the IDs involved.
        findings: Facts you already confirmed from tools (with numbers) that the other agent needs,
            so it does not repeat your lookups.
    """
    deps = ctx.deps
    team, limits = deps.team, deps.team.limits
    findings = list(findings or [])
    index = len(team.delegations)
    record = DelegationRecord(
        index=index, from_role=deps.role, to_role=to_role if to_role in ROLES else deps.role,
        depth=deps.depth + 1, chain=[*deps.chain, to_role] if to_role in ROLES else list(deps.chain),
        task=task, findings_passed=findings,
    )
    used = sum(1 for d in team.delegations if d.status != "refused")
    if (reason := check_delegation(deps.role, to_role, deps.chain, limits.max_delegation_depth,
                                   used, limits.max_delegations)):
        record.status, record.refused_reason = "refused", reason
        team.delegations.append(record)
        team.log("delegation_refused", deps.role, depth=deps.depth, chain=deps.chain, to_agent=to_role, reason=reason)
        return {"status": "refused", "reason": reason}

    team.delegations.append(record)
    team.log("delegation_start", deps.role, depth=deps.depth, chain=record.chain, to_agent=to_role,
             delegation_index=index, task=task, findings=findings)
    prompt = _build_prompt(team, to_role, record.chain, task=task, from_role=deps.role, findings=findings)
    try:
        report = await run_agent(team, to_role, prompt, record.chain)
    except UsageLimitExceeded:  # a team-wide limit stops everyone, not just this delegate
        record.status = "error"
        raise
    except Exception as exc:  # the delegate failed; tell the caller instead of crashing the run
        record.status = "error"
        error = f"{type(exc).__name__}: {clip(str(exc), 400)}"
        team.log("delegation_end", deps.role, depth=deps.depth, chain=record.chain, to_agent=to_role,
                 delegation_index=index, status="error", error=error)
        return {"status": "failed", "role": to_role, "error": error}
    record.status, record.report = "done", report
    team.log("delegation_end", deps.role, depth=deps.depth, chain=record.chain, to_agent=to_role,
             delegation_index=index, status=report.status, summary=report.summary)
    return report.model_dump()


AGENTS: dict[str, Agent[AgentDeps, AgentReport]] = {role: _make_agent(role) for role in ROLES}


def _build_prompt(
    team: TeamRun, role: Role, chain: list[Role], *, task: str, from_role: Role | None = None,
    findings: list[str] | None = None,
) -> str:
    """The user message an agent starts with: ticket, task, findings, and delegation options."""
    limits = team.limits
    can_delegate = len(chain) <= limits.max_delegation_depth
    others = [r for r in ROLES if r not in chain] if can_delegate else []
    lines = [
        f"ROLE: {role}",
        f"TICKET {team.ticket_id} CONTEXT (from the get_ticket MCP tool):",
        json.dumps(ticket_context_for(role, team.ticket), indent=2),
        "",
        f"TASK{' from ' + ROLE_TITLES[from_role] if from_role else ''}: {task}",
    ]
    lines += ["", "ACTIONS ALREADY ON THIS TICKET (from list_pending_actions; do not prepare these again):"]
    lines += [f"- {_action_line(a)}" for a in team.ticket_actions] or ["- none"]
    if team.instructions:
        lines += ["", "HUMAN DECISIONS FOR THIS RUN (typed by a person on the dashboard; treat as the human's decision):",
                  team.instructions]
    if findings:
        lines += ["", "FINDINGS ALREADY CONFIRMED BY OTHER AGENTS:", *[f"- {f}" for f in findings]]
    lines += [
        "",
        f"DELEGATION CHAIN: {' -> '.join(chain)}",
        f"YOU MAY DELEGATE TO: {', '.join(others) if others else 'nobody (depth limit reached)'}",
        f"YOUR MCP TOOLS: {', '.join(sorted(ROLE_TOOLS[role]))}",
    ]
    return "\n".join(lines)


def _action_line(a: dict[str, Any]) -> str:
    what = {"invoice_payment": f"pay invoice {a['ref_id']}", "rent_payment": f"pay lease {a['ref_id']} rent due {a.get('due_date')}",
            "restock_purchase": f"buy {a.get('qty')} x {a.get('sku')} size {a.get('size')} from vendor {a['ref_id']}"}.get(a["kind"], a["kind"])
    line = f"#{a['id']} {a['kind']}: {what}, ${a['amount']:.2f}, status {a['status']}"
    if a["status"] in ("executed", "rejected"):
        line += f" (decided by a human on {a.get('decided_at')})"
    return line


def _describe_node(node: Any) -> tuple[str, dict] | None:
    """Turn one agent-loop node into an audit entry body (None for nodes we skip)."""
    if Agent.is_user_prompt_node(node):
        return "user_prompt", {"prompt": clip(node.user_prompt, 2500)}
    if Agent.is_model_request_node(node):
        parts = node.request.parts
        return "model_request", {
            "tool_returns": [{"tool": p.tool_name, "content": clip(p.model_response_str(), 500)}
                             for p in parts if isinstance(p, ToolReturnPart)],
            "retries": [clip(p.model_response(), 400) for p in parts if isinstance(p, RetryPromptPart)],
        }
    if Agent.is_call_tools_node(node):
        resp = node.model_response
        u = resp.usage
        return "model_response", {
            "model": resp.model_name,
            "text": clip("".join(p.content for p in resp.parts if isinstance(p, TextPart)), 800),
            "tool_calls": [{"tool": p.tool_name, "args": p.args_as_dict()}
                           for p in resp.parts if isinstance(p, ToolCallPart)],
            "usage": {"input_tokens": u.input_tokens or 0, "output_tokens": u.output_tokens or 0},
        }
    if Agent.is_end_node(node):
        out = node.data.output
        return "agent_output", {"output": out.model_dump() if hasattr(out, "model_dump") else clip(out)}
    return None


async def run_agent(team: TeamRun, role: Role, prompt: str, chain: list[Role]) -> AgentReport:
    """Run one agent's loop to completion, logging every node to the audit trail."""
    deps = AgentDeps(team=team, role=role, chain=chain)
    team.log("agent_start", role, depth=deps.depth, chain=chain)
    async with AGENTS[role].iter(
        prompt,
        deps=deps,
        model=team.model,
        usage=team.usage,
        usage_limits=team.usage_limits,
        toolsets=[_role_toolset(team, role)],
        model_settings=ModelSettings(max_tokens=team.limits.max_output_tokens_per_response),
    ) as run:
        async for node in run:
            if (described := _describe_node(node)) is not None:
                kind, data = described
                team.log("agent_step", role, depth=deps.depth, chain=chain, kind=kind, **data)
        report = run.result.output
    team.log("agent_end", role, depth=deps.depth, chain=chain, status=report.status,
             usage_so_far=team.usage_summary().model_dump())
    return report


# --------------------------------------------------------------------------- entry point


async def run_ticket(
    ticket_id: int,
    *,
    run_id: str | None = None,
    instructions: str | None = None,
    db_path: Path | None = None,
    audit_path: Path | None = None,
    limits: config.RunLimits = config.DEFAULT_LIMITS,
    model: Model | None = None,
) -> TicketRunResult:
    """Run the team on one ticket and return a structured result.

    run_id: use this run ID (the backend creates it before starting the run in the background).
    instructions: decisions a person typed on the dashboard; shown to every agent and logged.
    db_path / audit_path: override the assignment database and audit file (tests).
    model: override the model (tests use a scripted FunctionModel). Defaults to
        gpt-6-luna through Portkey.
    """
    toolset = build_toolset(db_path, limits)
    team = TeamRun(
        run_id=run_id or uuid.uuid4().hex[:12],
        ticket_id=ticket_id,
        audit=AuditLog(audit_path or config.AUDIT_PATH),
        redact=Redactor(),
        limits=limits,
        model=model or config.build_model(limits),
        toolset=toolset,
        instructions=(instructions or "").strip() or None,
    )
    model_name = getattr(team.model, "model_name", config.MODEL_NAME)
    team.log("run_start", "runner", model=model_name, limits=limits.__dict__, human_instructions=team.instructions)

    status, error, boss_report = "failed", None, None
    try:
        async with asyncio.timeout(limits.max_run_seconds), toolset:
            got = await _runner_call(team, "get_ticket", {"ticket_id": ticket_id})
            if not got.get("found"):
                raise LookupError(got.get("error", f"Ticket {ticket_id} not found."))
            team.ticket = got["ticket"]
            team.ticket_actions = (await _runner_call(team, "list_pending_actions", {"ticket_id": ticket_id}))["actions"]
            prompt = _build_prompt(team, "boss", ["boss"], task=(
                "Handle this ticket end to end: gather the facts through your tools and delegates, take only "
                "the actions the shop rules allow, and report the outcome."))
            boss_report = await run_agent(team, "boss", prompt, ["boss"])
            status = boss_report.status
    except UsageLimitExceeded as exc:
        status, error = "limit_exceeded", str(exc)
    except TimeoutError:
        status, error = "limit_exceeded", f"Run stopped after the {limits.max_run_seconds:.0f}s time limit."
    except Exception as exc:  # report, don't crash the caller
        status, error = "failed", f"{type(exc).__name__}: {exc}"

    if status == "limit_exceeded":
        team.log("limit_exceeded", "runner", reason=error, usage=team.usage_summary().model_dump())
    elif error:
        team.log("run_error", "runner", error=clip(error, 800))

    result = TicketRunResult(
        run_id=team.run_id,
        ticket_id=ticket_id,
        model=model_name,
        status=status,
        boss_report=boss_report,
        delegations=team.delegations,
        tool_calls=team.tool_calls,
        pending_actions=team.pending_actions,
        usage=team.usage_summary(),
        seconds=round(time.perf_counter() - team.started, 2),
        error=error,
    )
    team.log("run_end", "runner", status=status, error=error, usage=result.usage.model_dump(),
             seconds=result.seconds, delegations=len(team.delegations),
             pending_actions=[{k: a[k] for k in ('id', 'kind', 'amount', 'status')} for a in team.pending_actions],
             summary=boss_report.summary if boss_report else None)
    return result
