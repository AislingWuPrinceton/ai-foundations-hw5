"""Shared fixtures. Every test works on a throwaway copy of the database and a
throwaway audit file, so data/campus_customs_new.db and output/audit_trail.json
are never touched."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

ASSIGNMENT_DB = PROJECT_DIR / "data" / "campus_customs_new.db"
ASSIGNMENT_AUDIT = PROJECT_DIR / "output" / "audit_trail.json"
# Tests copy the untouched original, so they don't depend on what real runs changed in the working DB.
PRISTINE_DB = PROJECT_DIR / "data" / "campus_customs.db"


def _sha(path: Path) -> str | None:
    return hashlib.sha1(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(autouse=True, scope="session")
def assignment_files_untouched():
    """Fail the session if any test changed the assignment database or audit file."""
    before = (_sha(ASSIGNMENT_DB), _sha(PRISTINE_DB), _sha(ASSIGNMENT_AUDIT))
    yield
    assert (_sha(ASSIGNMENT_DB), _sha(PRISTINE_DB), _sha(ASSIGNMENT_AUDIT)) == before, "a test modified the assignment files"


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    path = tmp_path / "campus_customs_test.db"
    shutil.copy(PRISTINE_DB, path)
    return path


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "audit_trail.json"


# ---------------------------------------------------------------- scripted model

Step = Callable[[list[ModelMessage], AgentInfo], ModelResponse] | dict | list


def role_of(messages: list[ModelMessage]) -> str:
    """Each agent's first user message starts with 'ROLE: <role>'."""
    for m in messages:
        for p in getattr(m, "parts", []):
            if isinstance(p, UserPromptPart) and isinstance(p.content, str) and p.content.startswith("ROLE: "):
                return p.content.split("\n", 1)[0].removeprefix("ROLE: ").strip()
    raise AssertionError("no ROLE line in the prompt")


def call(tool: str, **args: Any) -> ToolCallPart:
    return ToolCallPart(tool_name=tool, args=args)


def report(status: str = "completed", summary: str = "done", **extra: Any) -> dict:
    """Final AgentReport args (role/ticket_id are overwritten by the validator)."""
    return {"role": "boss", "ticket_id": 0, "status": status, "summary": summary, **extra}


class ScriptedModel:
    """FunctionModel driven by a per-role script.

    script[role] is a list of steps; step i answers that agent's i-th model
    request in its current run. A step is a list of ToolCallParts, a dict
    (the final AgentReport), or a callable(messages, info) -> ModelResponse.
    Also records which tools each role was offered.
    """

    def __init__(self, script: dict[str, list[Step]]):
        self.script = script
        self.tools_seen: dict[str, set[str]] = {}
        self.calls: list[str] = []
        self.model = FunctionModel(self._respond, model_name="scripted-test-model")

    def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        role = role_of(messages)
        self.calls.append(role)
        self.tools_seen[role] = {t.name for t in info.function_tools}
        i = sum(isinstance(m, ModelResponse) for m in messages)
        steps = self.script.get(role, [])
        step = steps[i] if i < len(steps) else report(summary=f"{role} default finish")
        if callable(step):
            return step(messages, info)
        if isinstance(step, dict):
            return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=step)])
        if isinstance(step, str):
            return ModelResponse(parts=[TextPart(step)])
        return ModelResponse(parts=list(step))
