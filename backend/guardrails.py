"""Business guardrails: which agent may call which MCP tool, which actions need a
human, how customer information is limited, and when delegation is refused.

These checks run in code, outside the model, so a prompt cannot talk its way
past them. The MCP server repeats the money checks (human approver, no negative
cash, no double payment) as a second line of defence.
"""

from __future__ import annotations

import re
from typing import Any

from .models import ROLES, Role

# Least privilege: each role sees only these MCP tools (the rest are filtered out).
# No agent can move money, place an order, approve, or reset: they can only *prepare*
# a pending action, which a human approves on the dashboard.
ROLE_TOOLS: dict[str, frozenset[str]] = {
    "boss": frozenset({"list_open_tickets", "get_ticket", "update_ticket_status"}),
    "inventory": frozenset({"check_stock_and_pricing", "list_vendors", "prepare_purchase"}),
    "accounting": frozenset({
        "check_stock_and_pricing", "get_invoice_with_vendor", "get_rent_due_and_cash",
        "get_cash_balances", "list_vendors", "quote_bulk_discount", "prepare_payment",
    }),
    "facilities": frozenset({"get_rent_due_and_cash"}),
    "customer_service": frozenset({"get_ticket", "check_stock_and_pricing"}),
}

# Tools that change the database when an agent calls them.
WRITE_TOOLS = frozenset({"prepare_payment", "prepare_purchase", "update_ticket_status"})
PREPARE_TOOLS = frozenset({"prepare_payment", "prepare_purchase"})

# Tools no agent ever gets. Only the backend's human-triggered routes call them.
HUMAN_ONLY_TOOLS = frozenset({
    "pay_invoice", "pay_rent", "approve_pending_action", "reject_pending_action", "reset_working_database",
})

# Actions that stay with a human by design.
HUMAN_ONLY_ACTIONS = (
    "Approving (executing) any prepared payment or restock purchase, on the dashboard, with the approver's name.",
    "Granting any discount or price override (no discount policy is documented).",
    "Sending any message to a customer, landlord, or vendor (agents only draft).",
    "Resetting the working database.",
)

# Ticket types whose requester is a customer (private person or student group).
CUSTOMER_TICKET_TYPES = frozenset({"customer_order", "price_override"})
# Roles that may see a customer's name. Everyone else gets it redacted.
CUSTOMER_NAME_ROLES = frozenset({"boss", "customer_service"})

# Internal figures that must not appear in a customer-facing reply.
_INTERNAL_TERMS = re.compile(
    r"\b(unit cost|our cost|margin|break[- ]even|cash|balance|checking|invoice|rent|landlord|lease|"
    r"bulldog print|vendor (?:is )?blocked|overdue)\b",
    re.IGNORECASE,
)


def ticket_context_for(role: Role, ticket: dict[str, Any]) -> dict[str, Any]:
    """The ticket fields a role needs. Customer names go only to Boss and Customer Service."""
    ctx = dict(ticket)
    if ticket.get("type") in CUSTOMER_TICKET_TYPES and role not in CUSTOMER_NAME_ROLES:
        ctx["requester"] = "[redacted: customer name not needed for this role]"
    return ctx


def check_tool_permission(role: Role, tool: str) -> str | None:
    if tool in HUMAN_ONLY_TOOLS:
        return f"{tool} can only be triggered by a human from the dashboard, never by an agent."
    if tool not in ROLE_TOOLS.get(role, frozenset()):
        return f"The {role} agent is not allowed to call {tool}."
    return None


def check_customer_reply(reply: str | None) -> str | None:
    """Reject customer drafts that leak internal finance or vendor details."""
    if not reply:
        return None
    hits = sorted({m.group(0).lower() for m in _INTERNAL_TERMS.finditer(reply)})
    if hits:
        return ("customer_reply_draft mentions internal shop details "
                f"({', '.join(hits)}). Rewrite it without costs, margins, cash, invoices, rent, or vendor problems.")
    return None


def check_delegation(
    from_role: Role, to_role: str, chain: list[Role], max_depth: int, used: int, max_delegations: int
) -> str | None:
    """Why a delegation must be refused, or None if it may go ahead."""
    if to_role not in ROLES:
        return f"Unknown role {to_role!r}; choose one of {list(ROLES)}."
    if to_role == from_role:
        return "An agent cannot delegate to itself."
    if to_role in chain:
        return f"{to_role} is already working on this ticket in the chain {' -> '.join(chain)}; that would be a cycle."
    if len(chain) > max_depth:
        return f"Delegation depth limit ({max_depth}) reached; finish with the information you have."
    if used >= max_delegations:
        return f"This ticket run already used its {max_delegations} delegations; finish with what you have."
    return None
