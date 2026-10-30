from datetime import UTC, datetime
from types import SimpleNamespace

from xetl.extract import sanitize
from xetl.text import clean_text, segments


def test_clean_text_masks_urls_and_mentions():
    assert clean_text("@ali  tengok https://t.co/x  sedap") == "@user tengok <URL> sedap"


def test_email_is_not_a_mention():
    assert clean_text("a@b.com") == "a@b.com"


def test_segments_split_on_punctuation_and_normalize():
    assert segments("Sdp, tk mahal!", {"sdp": "sedap", "tk": "tak"}) == [["sedap"], ["tak", "mahal"]]


def test_case_sensitive_spelling_only_matches_exact_case():
    assert segments("x sedap X", spelling_case_sensitive={"x": "tak"}) == [["tak", "sedap", "x"]]


def test_sanitize_drops_usernames():
    user = SimpleNamespace(id=123456789, username="real_handle", displayname="Real Name")
    tweet = SimpleNamespace(
        id_str="1", date=datetime(2026, 1, 5, tzinfo=UTC), rawContent="@real_handle murah",
        hashtags=["RohingyaMalaysia"], lang="in", likeCount=1, retweetCount=0, replyCount=0,
        quoteCount=0, viewCount=10, user=user, conversationIdStr="1",
        inReplyToTweetIdStr=None, retweetedTweet=None, quotedTweet=None,
    )  # fmt: skip
    record = sanitize(tweet, "salt")
    flat = str(record)
    assert "real_handle" not in flat and "Real Name" not in flat and "123456789" not in flat
    assert record["text"] == "@user murah"
