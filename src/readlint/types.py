"""JSON response types of the readlint.com evaluation API."""

from typing import Literal, TypedDict


class CheckResult(TypedDict):
    check: str
    group: str
    problem_probability: float
    verdict: Literal["clear", "unsure", "finding"]


class ProseResult(TypedDict):
    index: int
    kind: Literal["paragraph", "list"]
    section: str
    role: str
    text: str
    findings: list[CheckResult]
    unsure: list[CheckResult]


class PhraseResult(TypedDict):
    phrase: str
    block: int | None
    where: str


class EvaluationReport(TypedDict):
    title: str
    description: str
    article_checks: list[CheckResult]
    prose_blocks: list[ProseResult]
    banned_phrases: list[PhraseResult]
    omitted_computed_jsx: list[str]
    model: str
    input_tokens: int
    expires_at: str


class EvaluationSummary(TypedDict):
    id: str
    title: str
    created_at: str
    expires_at: str
    status: Literal["running", "complete", "failed"]
    error_code: str | None


class Evaluation(EvaluationSummary):
    report: EvaluationReport | None


class EvaluationPage(TypedDict):
    items: list[EvaluationSummary]
    next_offset: int | None


class AgentPermissions(TypedDict):
    agents_can_start_trials: bool
    agents_can_confirm_paid_orders: bool
    agents_can_cancel_plans: bool
