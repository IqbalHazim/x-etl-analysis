"""Hashtag scope (config/hashtags.yaml): search query and per-tweet matching."""

import re
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

HashtagMatch = Literal["primary", "variant", "typo", "split_pair", "none"]

HASHTAG_RE = re.compile(r"#(\w+)")
SPLIT_PAIR = ("Rohingya", "Malaysia")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(_Strict):
    since: date
    until: date  # exclusive

    @model_validator(mode="after")
    def check_order(self) -> "Window":
        if self.until <= self.since:
            raise ValueError("window.until must be after window.since")
        return self


class HashtagConfig(_Strict):
    primary: str
    variants: list[str] = []
    candidate_typos: list[str] = []
    include_split_pair: bool = False
    window: Window

    @property
    def tags(self) -> list[str]:
        return [self.primary, *self.variants, *self.candidate_typos]


def load_hashtags(path: Path) -> HashtagConfig:
    with path.open(encoding="utf-8") as f:
        return HashtagConfig.model_validate(yaml.safe_load(f))


def build_query(config: HashtagConfig, since: date, until: date) -> str:
    """X search query for one window. Always includes the split pair (#Rohingya
    #Malaysia) and typos, so the pilot can count them; scope is decided later."""
    terms = [f"#{tag}" for tag in config.tags]
    terms.append("(" + " ".join(f"#{t}" for t in SPLIT_PAIR) + ")")
    return f"({' OR '.join(terms)}) since:{since.isoformat()} until:{until.isoformat()}"


def tweet_hashtags(hashtags: list[str] | None, text: str) -> list[str]:
    """Hashtags as written, from the API field plus the text (the field can be empty)."""
    found = [h.lstrip("#") for h in (hashtags or [])]
    found += HASHTAG_RE.findall(text or "")
    return list(dict.fromkeys(found))  # dedupe, keep order


def classify(hashtags: list[str], config: HashtagConfig) -> HashtagMatch:
    """Which kind of configured hashtag a tweet carries. Case-insensitive."""
    lower = {h.lower() for h in hashtags}
    if config.primary.lower() in lower:
        return "primary"
    if lower & {v.lower() for v in config.variants}:
        return "variant"
    if lower & {t.lower() for t in config.candidate_typos}:
        return "typo"
    if {t.lower() for t in SPLIT_PAIR} <= lower:
        return "split_pair"
    return "none"


def in_scope(match: HashtagMatch, config: HashtagConfig) -> bool:
    if match == "split_pair":
        return config.include_split_pair
    return match != "none"
