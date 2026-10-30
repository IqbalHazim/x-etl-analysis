"""Pilot statistics: the brief's pilot checklist, written as a Markdown report."""

from pathlib import Path

import pandas as pd

from xetl.config import Settings
from xetl.hashtags import SPLIT_PAIR, HashtagConfig

ENGAGEMENT = ["like_count", "retweet_count", "reply_count", "quote_count"]


def md_table(df: pd.DataFrame) -> str:
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    rule = "|" + "---|" * len(df.columns)
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([header, rule, *rows])


def counts(series: pd.Series, name: str) -> pd.DataFrame:
    table = series.value_counts().rename_axis(name).reset_index(name="posts")
    table["%"] = (100 * table["posts"] / max(len(series), 1)).round(1)
    return table


def hashtag_spellings(df: pd.DataFrame, config: HashtagConfig) -> pd.DataFrame:
    """Every configured hashtag (and the split pair) as actually written, e.g. #rohingyamalaysia."""
    wanted = {t.lower() for t in [*config.tags, *SPLIT_PAIR]}
    tags = df["hashtags"].explode().dropna()
    tags = tags[tags.str.lower().isin(wanted)]
    return tags.map(lambda t: f"#{t}").value_counts().rename_axis("hashtag").reset_index(name="posts")


def build_report(
    tweets: pd.DataFrame, coded: pd.DataFrame | None, config: HashtagConfig, tz: str, n_days: int
) -> str:
    """`n_days` is the number of days searched, including days with no posts."""
    scope = tweets[tweets["in_scope"]].copy()
    scope["day"] = scope["timestamp"].dt.tz_convert(tz).dt.date
    per_day = scope.groupby("day").size().rename("posts").reset_index()

    n_days = max(n_days, 1)
    window_days = (config.window.until - config.window.since).days
    per_day_mean = len(scope) / n_days

    originals = scope[scope["post_type"] != "retweet"]
    engagement = pd.DataFrame(
        {
            "metric": ENGAGEMENT,
            "median": [originals[c].median() for c in ENGAGEMENT],
            "p25": [originals[c].quantile(0.25) for c in ENGAGEMENT],
            "p75": [originals[c].quantile(0.75) for c in ENGAGEMENT],
            "max": [originals[c].max() for c in ENGAGEMENT],
        }
    )

    sections = [
        "# Pilot pull statistics",
        f"- Posts collected: **{len(tweets)}** (after removing duplicate IDs)",
        f"- In scope: **{len(scope)}**",
        f"- Days covered: {n_days}; mean {per_day_mean:.1f} in-scope posts/day",
        f"- Full-window estimate ({config.window.since} to {config.window.until}, "
        f"{window_days} days): **~{per_day_mean * window_days:,.0f} posts**",
        f"- Posts sharing identical text with another post: "
        f"{int((scope['duplicate_text_count'] > 1).sum())}",
        "\n## Posts per day (in scope, %s)\n" % tz,
        md_table(per_day),
        "\n## Hashtag match (all collected)\n",
        md_table(counts(tweets["hashtag_match"], "match")),
        "\n## Hashtag spellings as written (finalize the regex from this)\n",
        md_table(hashtag_spellings(tweets, config)),
        "\n## Original vs repost (in scope)\n",
        md_table(counts(scope["post_type"], "post_type")),
        "\n## Language (in scope)\n",
        "X's own label:\n",
        md_table(counts(scope["lang"], "lang")),
        "\nDetected (lingua):\n",
        md_table(counts(scope["lang_detected"], "lang_detected")),
        "\n## Engagement (in scope, excluding retweets)\n",
        md_table(engagement),
    ]
    if coded is not None and len(coded):
        legitimacy = pd.DataFrame(
            [
                {"type": kind, **coded[f"legitimacy_{kind}"].value_counts().to_dict()}
                for kind in ("cognitive", "pragmatic", "moral")
            ]
        ).fillna(0)
        sections += [
            "\n## Sentiment (scored posts)\n",
            md_table(counts(coded["sentiment_score"].sort_values(), "score")),
            "\n## Legitimacy (scored posts)\n",
            md_table(legitimacy),
            f"\nFlagged for manual review: **{int(coded['needs_review'].sum())}** "
            f"of {len(coded)} ({100 * coded['needs_review'].mean():.1f}%)",
            "\n",
            md_table(counts(coded["review_reasons"].str.split("; ").explode()
                            .replace("", pd.NA).dropna()
                            .str.replace(r":.*", "", regex=True), "reason")),  # fmt: skip
        ]
    return "\n".join(sections) + "\n"


def run_stats(settings: Settings, config: HashtagConfig, run: str) -> Path:
    tweets_path = settings.stage_dir("interim", run) / "tweets.parquet"
    if not tweets_path.exists():
        raise FileNotFoundError(f"{tweets_path} not found. Run `xetl transform` first.")
    coded_path = settings.stage_dir("processed", run) / "coded.parquet"
    tweets = pd.read_parquet(tweets_path)
    coded = pd.read_parquet(coded_path) if coded_path.exists() else None

    out = settings.stage_dir("outputs", run) / "pilot_stats.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    n_days = len(list(settings.stage_dir("raw", run).glob("*.jsonl")))  # one file per day searched
    report = build_report(tweets, coded, config, settings.timezone, n_days)
    out.write_text(report, encoding="utf-8")
    return out
