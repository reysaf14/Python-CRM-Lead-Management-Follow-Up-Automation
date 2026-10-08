"""Pure deterministic lead scoring rules and decision calculation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_BUDGET_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[,.\s]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?!\d)"
)


class BudgetBand(BaseModel):
    """One inclusive budget range and its deterministic point contribution."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=40)
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    points: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> "BudgetBand":
        if self.min_amount is not None and self.max_amount is not None:
            if self.min_amount > self.max_amount:
                raise ValueError("min_amount cannot exceed max_amount")
        return self


class ScoringRuleSet(BaseModel):
    """Versioned scoring policy; values are data, not code paths."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=255)
    high_threshold: int = Field(ge=1, le=1000)
    medium_threshold: int = Field(ge=0, le=999)
    sales_inquiry_points: int = Field(ge=0, le=100)
    service_interest_points: int = Field(ge=0, le=100)
    budget_known_points: int = Field(ge=0, le=100)
    business_summary_points: int = Field(ge=0, le=100)
    budget_bands: list[BudgetBand] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "ScoringRuleSet":
        if self.medium_threshold >= self.high_threshold:
            raise ValueError("medium_threshold must be lower than high_threshold")
        return self


# This is an explicit implementation baseline for synthetic execution only.
# Business owners must confirm point values and thresholds before production.
DEFAULT_SCORING_RULES = ScoringRuleSet(
    version="m4-baseline-draft-v1",
    description="Draft deterministic scoring baseline for synthetic MVP verification",
    high_threshold=70,
    medium_threshold=40,
    sales_inquiry_points=30,
    service_interest_points=25,
    budget_known_points=10,
    business_summary_points=10,
    budget_bands=[
        BudgetBand(label="budget_1000_plus", min_amount=Decimal("1000"), points=25),
        BudgetBand(label="budget_500_to_999", min_amount=Decimal("500"), max_amount=Decimal("999.99"), points=15),
        BudgetBand(label="budget_under_500", max_amount=Decimal("499.99"), points=5),
    ],
)


def parse_stated_budget(value: str | None) -> Decimal | None:
    """Parse only a stated numeric amount; never infer budget from other facts."""

    if not value:
        return None
    match = _BUDGET_RE.search(value)
    if not match:
        return None
    candidate = match.group(1).replace(",", "").replace(" ", "")
    try:
        return Decimal(candidate)
    except InvalidOperation:
        return None


def _find_budget_band(amount: Decimal | None, rules: ScoringRuleSet) -> BudgetBand | None:
    if amount is None:
        return None
    for band in rules.budget_bands:
        if band.min_amount is not None and amount < band.min_amount:
            continue
        if band.max_amount is not None and amount > band.max_amount:
            continue
        return band
    return None


@dataclass(frozen=True)
class ScoreDecision:
    """Deterministic result safe to persist as a score evaluation."""

    score: int
    priority: str
    explanation: str
    input_snapshot: dict[str, Any]


def calculate_score(
    *,
    facts: dict[str, Any],
    rules: ScoringRuleSet,
    source_message_id: int,
) -> ScoreDecision:
    """Calculate score and explanation from validated extraction facts only."""

    intent = facts.get("intent")
    service_interest = facts.get("service_interest")
    stated_budget = facts.get("stated_budget")
    business_summary = facts.get("business_summary")
    budget_amount = parse_stated_budget(stated_budget if isinstance(stated_budget, str) else None)
    budget_band = _find_budget_band(budget_amount, rules)

    points = 0
    reasons: list[str] = []
    if intent == "sales_inquiry":
        points += rules.sales_inquiry_points
        reasons.append(f"sales inquiry (+{rules.sales_inquiry_points})")
    if service_interest:
        points += rules.service_interest_points
        reasons.append(f"service interest provided (+{rules.service_interest_points})")
    if budget_amount is not None:
        points += rules.budget_known_points
        reasons.append(f"stated budget provided (+{rules.budget_known_points})")
    if budget_band is not None:
        points += budget_band.points
        reasons.append(f"{budget_band.label} (+{budget_band.points})")
    if business_summary:
        points += rules.business_summary_points
        reasons.append(f"business summary provided (+{rules.business_summary_points})")

    if points >= rules.high_threshold:
        priority = "High"
    elif points >= rules.medium_threshold:
        priority = "Medium"
    else:
        priority = "Low"

    if not reasons:
        reasons.append("no applicable positive scoring criteria")
    explanation = (
        "; ".join(reasons)
        + f"; total={points}; priority={priority}; rule_version={rules.version}."
    )
    snapshot = {
        "source_message_id": source_message_id,
        "intent": intent,
        "has_service_interest": bool(service_interest),
        "has_stated_budget": budget_amount is not None,
        "budget_band": budget_band.label if budget_band is not None else None,
        "has_business_summary": bool(business_summary),
    }
    return ScoreDecision(
        score=points,
        priority=priority,
        explanation=explanation,
        input_snapshot=snapshot,
    )
