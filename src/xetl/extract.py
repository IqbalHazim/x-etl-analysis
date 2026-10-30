"""Extract: search X with twscrape, one day at a time, and store sanitized JSONL.

Records are anonymized here, before anything touches disk: author IDs are
hashed and @handles in the text are masked, so no usernames are ever stored.
Each day is written to `<day>.jsonl.part` and renamed when complete, so an
interrupted run resumes from the first unfinished day.
"""

import asyncio
import json
import logging
from contextlib import aclosing
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from twscrape import API

from xetl.anonymize import hash_author_id
from xetl.config import Settings
from xetl.hashtags import HashtagConfig, build_query
from xetl.text import mask_mentions

log = logging.getLogger(__name__)


def sanitize(tweet: Any, salt: str) -> dict[str, Any]:
    """Keep only the fields we need, with the author hashed and mentions masked."""
    retweeted, quoted = tweet.retweetedTweet, tweet.quotedTweet
    return {
        "tweet_id": tweet.id_str,
        "timestamp": tweet.date.isoformat(),
        "text": mask_mentions(tweet.rawContent or ""),
        "hashtags": list(tweet.hashtags or []),
        "lang": tweet.lang,
        "like_count": tweet.likeCount,
        "retweet_count": tweet.retweetCount,
        "reply_count": tweet.replyCount,
        "quote_count": tweet.quoteCount,
        "view_count": tweet.viewCount,
        "author_id_hash": hash_author_id(tweet.user.id, salt),
        "conversation_id": tweet.conversationIdStr,
        "in_reply_to_id": tweet.inReplyToTweetIdStr,
        "retweeted_id": retweeted.id_str if retweeted else None,
        "quoted_id": quoted.id_str if quoted else None,
    }


def days(since: date, until: date) -> list[date]:
    return [since + timedelta(days=n) for n in range((until - since).days)]


async def _extract(
    api: API, config: HashtagConfig, out_dir: Path, since: date, until: date, limit: int, salt: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for day in days(since, until):
        out = out_dir / f"{day.isoformat()}.jsonl"
        if out.exists():
            log.info("%s already extracted, skipping", day)
            counts[day.isoformat()] = sum(1 for _ in out.open())
            continue
        query = build_query(config, day, day + timedelta(days=1))
        log.info("searching %s", query)
        part = out.with_suffix(".jsonl.part")
        n = 0
        with part.open("w", encoding="utf-8") as f:
            async with aclosing(api.search(query, limit=limit)) as tweets:
                async for tweet in tweets:
                    f.write(json.dumps(sanitize(tweet, salt), ensure_ascii=False) + "\n")
                    n += 1
        part.rename(out)
        counts[day.isoformat()] = n
        log.info("%s: %d posts", day, n)
    return counts


def run_extract(
    settings: Settings, config: HashtagConfig, run: str, since: date, until: date, limit: int = -1
) -> dict[str, int]:
    if not settings.accounts_db.exists():
        raise FileNotFoundError(
            f"No twscrape accounts at {settings.accounts_db}. Add accounts first (see README)."
        )
    out_dir = settings.stage_dir("raw", run)
    out_dir.mkdir(parents=True, exist_ok=True)
    api = API(str(settings.accounts_db), raise_when_no_account=True)
    salt = settings.author_hash_salt.get_secret_value()
    return asyncio.run(_extract(api, config, out_dir, since, until, limit, salt))
