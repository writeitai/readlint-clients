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


class BillingInvoice(TypedDict):
    id: str
    status: str
    subtotal_cents: int
    amount_paid_cents: int
    amount_remaining_cents: int | None
    url: str | None


class PaymentAction(TypedDict):
    action_url: str
    reason: Literal["payment_authentication_required", "payment_method_required"]


class PendingSetup(TypedDict):
    attempt_id: str
    state: Literal["pending", "complete", "expired", "blocked"]
    action_url: str | None
    expires_at: str


class BillingStatus(TypedDict):
    enabled: bool
    payment_method_ready: bool
    trial_available: bool
    trial_ends_at: str | None
    paid_order_confirmed: bool
    cancelled_at: str | None
    suspended: bool
    period_ends_at: str | None
    period_kind: Literal["trial", "paid"] | None
    credits_remaining_cents: float
    usage_above_credits_cents: float
    fractional_balance_cents: float
    invoices: list[BillingInvoice]
    order_id: str | None
    order_state: Literal[
        "none", "scheduled", "payment_pending", "requires_action", "active", "cancelled"
    ]
    access_active: bool
    pending_setup: PendingSetup | None
    payment_action: PaymentAction | None


class BillingQuote(TypedDict):
    quote_id: str
    expires_at: str
    currency: Literal["usd"]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    monthly_credits_cents: int
    usage_rate_cents_per_million: int
    credit_expiry: str
    first_charge_timing: str
    renewal_terms: str
    cancellation_terms: str
    terms_version: str
    terms_url: str
    privacy_version: str
    privacy_url: str
    disclosure_version: str
    disclosure_text: str
    affirmation: str


class BillingOrder(TypedDict):
    accepted: Literal[True]
    order_id: str
    accepted_at: str
    accepted_state: Literal["scheduled", "payment_pending"] | None
    current: BillingStatus
    retryable: bool


class BillingCancellation(TypedDict):
    cancelled: Literal[True]
    order_id: str | None
    trial_period_id: str | None
    current: BillingStatus


class BillingPortal(TypedDict):
    url: str
