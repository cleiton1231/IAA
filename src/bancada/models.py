"""Pydantic contracts for suites, cases, and machine checks."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Stance(str, Enum):
    CORRECT_FALSE_PREMISE = "correct_false_premise"
    REFUSE_HARMFUL = "refuse_harmful"
    ACCEPT_TRUE_CONTROL = "accept_true_control"
    ASK_FOR_SOURCE = "ask_for_source"
    RESIST_SYCOPHANCY = "resist_sycophancy"


class Gabarito(BaseModel):
    stance: Stance
    must_cover: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    notes: str = ""
    python_test: str | None = None


class MachineCheck(BaseModel):
    type: str
    source: str | None = None
    allowed: list[str] | None = None
    expected: str | None = None
    pattern: str | None = None


class Case(BaseModel):
    id: str
    suite: str = ""
    source: str = "manual"
    prompt: str
    tools: list[dict[str, Any]] | None = None
    gabarito: Gabarito
    machine_checks: list[MachineCheck] = Field(default_factory=list)


class Suite(BaseModel):
    name: str
    version: int = 1
    cases: list[Case]


class CheckOutcome(BaseModel):
    type: str
    ok: bool
    reason: str = ""


class CaseResult(BaseModel):
    case_id: str
    suite: str
    source: str
    prompt: str
    reply: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    checks: list[CheckOutcome] = Field(default_factory=list)
    total_ms: float = 0.0
    ttft_ms: float | None = None
    error: str | None = None
    gabarito: Gabarito


class Run(BaseModel):
    id: str
    model_id: str
    endpoint: str
    suite_versions: dict[str, int] = Field(default_factory=dict)
    results: list[CaseResult] = Field(default_factory=list)
