"""Load and validate the keyword codebook (config/codebook.yaml)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

SENTIMENT_SCORES = {1, 2, 3, 4, 5}
LEGITIMACY_TYPES = {"cognitive", "pragmatic", "moral"}


class _Strict(BaseModel):
    # Unknown keys (e.g a typo like "seniment" or "bn") are errors, not silently ignored.
    model_config = ConfigDict(extra="forbid")


class KeywordSet(_Strict):
    en: list[str]
    bm: list[str]

    @field_validator("en", "bm")
    @classmethod
    def clean(cls, keywords: list[str]) -> list[str]:
        cleaned = [k.strip().lower() for k in keywords]
        if "" in cleaned:
            raise ValueError("empty keyword")
        duplicates = sorted({k for k in cleaned if cleaned.count(k) > 1})
        if duplicates:
            raise ValueError(f"duplicate keywords: {duplicates}")
        return cleaned

    @property
    def all(self) -> list[str]:
        return self.en + self.bm


class SentimentLevel(KeywordSet):
    band: str


class Direction(_Strict):
    granted: KeywordSet
    denied: KeywordSet


class Codebook(_Strict):
    version: int
    sentiment: dict[int, SentimentLevel]
    legitimacy: dict[str, Direction]

    @field_validator("sentiment")
    @classmethod
    def check_scores(cls, value: dict[int, SentimentLevel]) -> dict[int, SentimentLevel]:
        if set(value) != SENTIMENT_SCORES:
            raise ValueError(f"sentiment must define scores 1-5, got {sorted(value)}")
        return value

    @field_validator("legitimacy")
    @classmethod
    def check_types(cls, value: dict[str, Direction]) -> dict[str, Direction]:
        if set(value) != LEGITIMACY_TYPES:
            raise ValueError(f"legitimacy must define {sorted(LEGITIMACY_TYPES)}")
        return value


def load_codebook(path: Path) -> Codebook:
    with path.open(encoding="utf-8") as f:
        return Codebook.model_validate(yaml.safe_load(f))
