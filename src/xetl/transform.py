"""Transform: merge raw days, dedupe, clean text, classify posts, detect language."""

import json
import logging
from pathlib import Path

import pandas as pd
from lingua import Language, LanguageDetectorBuilder

from xetl.config import Settings
from xetl.hashtags import HashtagConfig, classify, in_scope, tweet_hashtags
from xetl.text import clean_text

log = logging.getLogger(__name__)

RAW_COLUMNS = [
    "tweet_id", "timestamp", "text", "hashtags", "lang", "like_count", "retweet_count",
    "reply_count", "quote_count", "view_count", "author_id_hash", "conversation_id",
    "in_reply_to_id", "retweeted_id", "quoted_id",
]  # fmt: skip
MIN_WORDS_FOR_LANGUAGE = 3


def post_type(row: pd.Series) -> str:
    if pd.notna(row["retweeted_id"]):
        return "retweet"
    if pd.notna(row["quoted_id"]):
        return "quote"
    if pd.notna(row["in_reply_to_id"]):
        return "reply"
    return "original"


def detect_languages(texts: pd.Series) -> pd.Series:
    """Our own language label next to X's `lang`, which often tags Malay as `in`."""
    detector = LanguageDetectorBuilder.from_languages(
        Language.MALAY, Language.ENGLISH, Language.INDONESIAN
    ).build()

    def detect(text: str) -> str:
        words = [w for w in text.split() if not w.startswith(("#", "@", "<URL>"))]
        if len(words) < MIN_WORDS_FOR_LANGUAGE:
            return "und"
        language = detector.detect_language_of(" ".join(words))
        return language.iso_code_639_1.name.lower() if language else "und"

    return texts.map(detect)


def load_raw(raw_dir: Path) -> pd.DataFrame:
    files = sorted(raw_dir.glob("*.jsonl"))
    if not files:
        raise FileNotFoundError(f"No extracted data in {raw_dir}. Run `xetl extract` first.")
    records = [json.loads(line) for f in files for line in f.open(encoding="utf-8")]
    return pd.DataFrame.from_records(records, columns=RAW_COLUMNS)


def run_transform(settings: Settings, config: HashtagConfig, run: str) -> pd.DataFrame:
    df = load_raw(settings.stage_dir("raw", run))
    collected = len(df)
    df = df.drop_duplicates("tweet_id").reset_index(drop=True)
    log.info("%d records, %d after removing duplicate IDs", collected, len(df))

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["text_clean"] = df["text"].fillna("").map(clean_text)
    df["hashtags"] = [tweet_hashtags(h, t) for h, t in zip(df["hashtags"], df["text"], strict=True)]
    df["hashtag_match"] = df["hashtags"].map(lambda tags: classify(tags, config))
    df["in_scope"] = df["hashtag_match"].map(lambda m: in_scope(m, config))
    df["post_type"] = df.apply(post_type, axis=1) if len(df) else pd.Series(dtype=str)
    df["lang_detected"] = detect_languages(df["text_clean"])
    # Same text posted many times (copy-paste campaigns) is flagged, not removed.
    key = df["text_clean"].str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    df["duplicate_text_count"] = key.groupby(key).transform("size")

    out = settings.stage_dir("interim", run) / "tweets.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df
