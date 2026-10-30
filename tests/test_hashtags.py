from datetime import date

import pytest

from xetl.hashtags import build_query, classify, in_scope, tweet_hashtags


def test_query_covers_all_tags_and_window(hashtags):
    q = build_query(hashtags, date(2026, 1, 5), date(2026, 1, 6))
    assert "#RohingyaMalaysia OR #Rohingya_Malaysia" in q
    assert "(#Rohingya #Malaysia)" in q
    assert q.endswith("since:2026-01-05 until:2026-01-06")


@pytest.mark.parametrize(
    "tags,expected",
    [
        (["ROHINGYAMALAYSIA"], "primary"),
        (["rohingya_malaysia"], "variant"),
        (["RohingyaMalaysiaa"], "typo"),
        (["Rohingya", "malaysia"], "split_pair"),
        (["Rohingya"], "none"),
    ],
)
def test_classify_is_case_insensitive(hashtags, tags, expected):
    assert classify(tags, hashtags) == expected


def test_split_pair_scope_follows_config(hashtags):
    assert in_scope("split_pair", hashtags) is hashtags.include_split_pair
    assert in_scope("typo", hashtags)
    assert not in_scope("none", hashtags)


def test_hashtags_read_from_text_when_field_empty():
    assert tweet_hashtags([], "kedai bagus #RohingyaMalaysia") == ["RohingyaMalaysia"]
