"""Paths, model, and run limits for the Campus Customs agent team.

Every agent uses gpt-6-luna through Portkey. PORTKEY_API_KEY is read from the
environment (loaded from the nearest .env: this project first, then parents).
The key is passed to the client only; it is never logged or written anywhere.

gpt-6-luna needs the Responses API for function tools, so the model is an
OpenAIResponsesModel.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

PROJECT_DIR = Path(__file__).resolve().parents[1]  # Homework/5
for folder in (PROJECT_DIR, *PROJECT_DIR.parents):
    if (folder / ".env").exists():
        load_dotenv(folder / ".env", override=False)

# Homework 5 allows only this model; it is deliberately not configurable.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

MCP_SERVER_SCRIPT = PROJECT_DIR / "mcp_server" / "server.py"
# CAMPUS_CUSTOMS_DB / CAMPUS_CUSTOMS_ORIGINAL_DB / CAMPUS_CUSTOMS_AUDIT point a backend at
# isolated copies (tests); by default it uses the assignment files.
DB_PATH = Path(os.getenv("CAMPUS_CUSTOMS_DB") or PROJECT_DIR / "data" / "campus_customs_new.db").resolve()
ORIGINAL_DB_PATH = Path(os.getenv("CAMPUS_CUSTOMS_ORIGINAL_DB") or PROJECT_DIR / "data" / "campus_customs.db").resolve()
AUDIT_PATH = Path(os.getenv("CAMPUS_CUSTOMS_AUDIT") or PROJECT_DIR / "output" / "audit_trail.json").resolve()
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
# Optional label stamped on every audit entry this process writes (e.g. the final graded run),
# so its evidence can be told apart from earlier tests.
RUN_LABEL = os.getenv("CAMPUS_CUSTOMS_RUN_LABEL", "").strip() or None


@dataclass(frozen=True)
class RunLimits:
    """Hard limits for one ticket run, shared by every agent in the team."""

    max_model_requests: int = 30      # model calls, all agents together
    max_total_tokens: int = 150_000   # input + output tokens, all agents together
    max_output_tokens_per_response: int = 8_000
    max_tool_calls: int = 40          # MCP + delegation tool calls, all agents together
    max_delegation_depth: int = 2     # boss (0) -> specialist (1) -> specialist (2)
    max_delegations: int = 8          # delegations per ticket run
    max_retries: int = 2              # tool / output-validation retries per agent
    max_http_retries: int = 2         # client retries on transient API errors
    max_run_seconds: float = 300.0    # wall clock for the whole ticket run
    tool_timeout_seconds: float = 30.0


DEFAULT_LIMITS = RunLimits()


def require_api_key() -> str:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is missing. Put it in the root .env file.")
    return key


def build_model(limits: RunLimits = DEFAULT_LIMITS) -> OpenAIResponsesModel:
    key = require_api_key()
    client = AsyncOpenAI(
        api_key=key,
        base_url=PORTKEY_BASE_URL,
        default_headers={"x-portkey-api-key": key},
        max_retries=limits.max_http_retries,
    )
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
