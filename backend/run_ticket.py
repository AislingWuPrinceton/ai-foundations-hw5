"""Run the agent team on one ticket from the command line.

    .venv/bin/python -m backend.run_ticket 102

Agents can only prepare payments and purchases; approve them on the dashboard
(POST /api/pending-actions/{id}/approve).
"""

from __future__ import annotations

import argparse
import asyncio

from .team import run_ticket


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ticket_id", type=int)
    args = parser.parse_args()
    result = asyncio.run(run_ticket(args.ticket_id))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
