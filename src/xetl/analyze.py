"""Analyze: score every in-scope post with the keyword engine."""

import json
from dataclasses import asdict

import pandas as pd

from xetl.config import Settings
from xetl.engine import Engine, band

CODED_COLUMNS = [
    "sentiment_score", "sentiment_band", "legitimacy_cognitive", "legitimacy_pragmatic",
    "legitimacy_moral", "model_confidence", "needs_review", "review_reasons",
    "matched_keywords", "matches_json",
]  # fmt: skip


def describe_matches(result) -> str:
    """Readable trace, e.g. "sentiment:murah=4; pragmatic:!murah=Denied" (! = negated)."""
    return "; ".join(
        f"{m.dimension}:{'!' if m.negated else ''}{m.keyword}={m.label}" for m in result.matches
    )


def score_frame(df: pd.DataFrame, engine: Engine) -> pd.DataFrame:
    results = [engine.score(text) for text in df["text_clean"]]
    coded = pd.DataFrame(
        {
            "sentiment_score": [r.sentiment_score for r in results],
            "sentiment_band": [band(r.sentiment_score) for r in results],
            "legitimacy_cognitive": [r.legitimacy["cognitive"] for r in results],
            "legitimacy_pragmatic": [r.legitimacy["pragmatic"] for r in results],
            "legitimacy_moral": [r.legitimacy["moral"] for r in results],
            "model_confidence": [r.confidence for r in results],
            "needs_review": [r.needs_review for r in results],
            "review_reasons": ["; ".join(r.review_reasons) for r in results],
            "matched_keywords": [describe_matches(r) for r in results],
            "matches_json": [json.dumps([asdict(m) for m in r.matches]) for r in results],
        },
        index=df.index,
        columns=CODED_COLUMNS,
    )
    return pd.concat([df, coded], axis=1)


def run_analyze(settings: Settings, engine: Engine, run: str) -> pd.DataFrame:
    path = settings.stage_dir("interim", run) / "tweets.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `xetl transform` first.")
    df = pd.read_parquet(path)
    df = df[df["in_scope"]]
    if engine.rules.scope.exclude_retweets:
        df = df[df["post_type"] != "retweet"]
    coded = score_frame(df.reset_index(drop=True), engine)

    out = settings.stage_dir("processed", run) / "coded.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    coded.to_parquet(out, index=False)

    queue = settings.stage_dir("outputs", run) / "review_queue.csv"
    queue.parent.mkdir(parents=True, exist_ok=True)
    columns = ["tweet_id", "text_clean", "sentiment_score", "legitimacy_cognitive",
               "legitimacy_pragmatic", "legitimacy_moral", "review_reasons", "matched_keywords"]  # fmt: skip
    coded.loc[coded["needs_review"], columns].to_csv(queue, index=False)
    return coded
