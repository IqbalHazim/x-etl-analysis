"""Load and validate the engine rules (config/rules.yaml)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(_Strict):
    exclude_retweets: bool = True


class Matching(_Strict):
    negators: list[str]
    negation_window: int = Field(ge=0)
    spelling: dict[str, str] = {}
    spelling_case_sensitive: dict[str, str] = {}

    @field_validator("negators")
    @classmethod
    def lowercase(cls, words: list[str]) -> list[str]:
        return [w.strip().lower() for w in words]


class SentimentRules(_Strict):
    combine: Literal["mean", "extreme"] = "mean"
    no_match_score: int = Field(3, ge=1, le=5)


class LegitimacyRules(_Strict):
    neutral_policy: Literal["keep", "na"] = "keep"


class ReviewRules(_Strict):
    min_confidence: float = Field(0.6, ge=0, le=1)
    sarcasm_markers: list[str] = []
    ambiguous_keywords: list[str] = []


class Rules(_Strict):
    version: int
    scope: Scope
    matching: Matching
    sentiment: SentimentRules
    legitimacy: LegitimacyRules
    review: ReviewRules


def load_rules(path: Path) -> Rules:
    with path.open(encoding="utf-8") as f:
        return Rules.model_validate(yaml.safe_load(f))
