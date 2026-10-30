"""Rule-based sentiment and legitimacy scoring (Option A).

Each dimension (sentiment, cognitive, pragmatic, moral) has its own matcher, so
one phrase can count for several dimensions, as the brief requires ("penipu" is
both sentiment 1 and cognitive Denied). Within a dimension the longest phrase
wins: "macam mana boleh jual" (cognitive Denied) is matched before "jual"
(cognitive Granted), and "tak sokong" (2) before "sokong" (4).
"""

import math
from dataclasses import dataclass, field

from xetl.codebook import Codebook, KeywordSet
from xetl.rules import Rules
from xetl.text import segments

LEGITIMACY_TYPES = ("cognitive", "pragmatic", "moral")
GRANTED, DENIED, NA = "Granted", "Denied", "NA"


def band(score: int) -> str:
    """Same rule as the template's sentiment_band formula."""
    if score <= 2:
        return "Negative"
    return "Neutral" if score == 3 else "Positive"


@dataclass(frozen=True)
class Match:
    dimension: str  # "sentiment" or a legitimacy type
    keyword: str
    label: str  # "1".."5" for sentiment, Granted/Denied for legitimacy (after negation)
    negated: bool


@dataclass
class Result:
    sentiment_score: int
    legitimacy: dict[str, str]
    confidence: float
    matches: list[Match] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)


class PhraseMatcher:
    """Greedy longest-phrase-first matching over one clause of tokens."""

    def __init__(self, phrases: dict[tuple[str, ...], str]):
        self.phrases = phrases
        self.max_len = max(len(p) for p in phrases)

    def find(self, tokens: list[str], negators: set[str], window: int):
        i, last_match_end = 0, 0
        while i < len(tokens):
            for n in range(min(self.max_len, len(tokens) - i), 0, -1):
                phrase = tuple(tokens[i : i + n])
                if phrase in self.phrases:
                    # Look back for a negator, but not into an earlier match:
                    # in "tak berbaloi murah", "tak" belongs to "tak berbaloi".
                    lookback = tokens[max(last_match_end, i - window) : i]
                    yield phrase, self.phrases[phrase], any(t in negators for t in lookback)
                    i += n
                    last_match_end = i
                    break
            else:
                i += 1


class Engine:
    def __init__(self, codebook: Codebook, rules: Rules):
        self.rules = rules
        m = rules.matching
        self._tokenize = lambda text: segments(text, m.spelling, m.spelling_case_sensitive)
        self._negators = set(m.negators)

        self.sentiment = PhraseMatcher(
            self._phrases({str(score): level for score, level in codebook.sentiment.items()})
        )
        self.legitimacy = {
            kind: PhraseMatcher(
                self._phrases({GRANTED: direction.granted, DENIED: direction.denied})
            )
            for kind, direction in codebook.legitimacy.items()
        }
        self._sarcasm = [tuple(self._flat(p)) for p in rules.review.sarcasm_markers]
        self._ambiguous = set(rules.review.ambiguous_keywords)

    def _flat(self, text: str) -> list[str]:
        return [t for seg in self._tokenize(text) for t in seg]

    def _phrases(self, labelled: dict[str, KeywordSet]) -> dict[tuple[str, ...], str]:
        """Tokenize keywords the same way as tweets, and refuse ambiguous codebooks."""
        phrases: dict[tuple[str, ...], str] = {}
        for label, keywords in labelled.items():
            for keyword in keywords.all:
                phrase = tuple(self._flat(keyword))
                if phrases.get(phrase, label) != label:
                    raise ValueError(
                        f"keyword {keyword!r} is listed as both {phrases[phrase]} and {label}"
                    )
                phrases[phrase] = label
        return phrases

    def score(self, text: str) -> Result:
        window = self.rules.matching.negation_window
        matches: list[Match] = []
        clauses = self._tokenize(text)
        for tokens in clauses:
            for phrase, label, negated in self.sentiment.find(tokens, self._negators, window):
                if negated:
                    label = str(6 - int(label))  # 4 <-> 2, 5 <-> 1, 3 stays 3
                matches.append(Match("sentiment", " ".join(phrase), label, negated))
            for kind, matcher in self.legitimacy.items():
                for phrase, label, negated in matcher.find(tokens, self._negators, window):
                    if negated:
                        label = DENIED if label == GRANTED else GRANTED
                    matches.append(Match(kind, " ".join(phrase), label, negated))

        reasons: list[str] = []
        score, confidence = self._sentiment(matches, reasons)
        legitimacy = {kind: self._legitimacy(kind, matches, reasons) for kind in LEGITIMACY_TYPES}
        if self.rules.legitimacy.neutral_policy == "na" and score == 3:
            legitimacy = dict.fromkeys(LEGITIMACY_TYPES, NA)

        if confidence < self.rules.review.min_confidence and matches_of(matches, "sentiment"):
            reasons.append("low_confidence")
        positive = score > 3 or GRANTED in legitimacy.values()
        if positive and self._has_sarcasm_marker(clauses):
            reasons.append("sarcasm_marker")
        for m in matches:
            if m.keyword in self._ambiguous:
                reasons.append(f"ambiguous_keyword:{m.keyword}")
        return Result(score, legitimacy, confidence, matches, list(dict.fromkeys(reasons)))

    def _sentiment(self, matches: list[Match], reasons: list[str]) -> tuple[int, float]:
        scores = [int(m.label) for m in matches_of(matches, "sentiment")]
        if not scores:
            reasons.append("no_sentiment_keyword")
            return self.rules.sentiment.no_match_score, 0.0
        if self.rules.sentiment.combine == "mean":
            score = math.floor(sum(scores) / len(scores) + 0.5)
        else:
            score = max(scores, key=lambda s: (abs(s - 3), s < 3))
        if any(s < 3 for s in scores) and any(s > 3 for s in scores):
            reasons.append("mixed_polarity")
        agreeing = sum(band(s) == band(score) for s in scores)
        return score, round(agreeing / len(scores), 2)

    @staticmethod
    def _legitimacy(kind: str, matches: list[Match], reasons: list[str]) -> str:
        labels = [m.label for m in matches_of(matches, kind)]
        granted, denied = labels.count(GRANTED), labels.count(DENIED)
        if granted == denied:
            if granted:
                reasons.append(f"mixed_{kind}")
            return NA
        return GRANTED if granted > denied else DENIED

    def _has_sarcasm_marker(self, clauses: list[list[str]]) -> bool:
        tokens = [t for seg in clauses for t in seg]
        for marker in self._sarcasm:
            n = len(marker)
            if any(tuple(tokens[i : i + n]) == marker for i in range(len(tokens) - n + 1)):
                return True
        return False


def matches_of(matches: list[Match], dimension: str) -> list[Match]:
    return [m for m in matches if m.dimension == dimension]
