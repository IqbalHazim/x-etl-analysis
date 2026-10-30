import pytest

from xetl.codebook import load_codebook
from xetl.engine import Engine

from conftest import CONFIG


def labels(result, dimension):
    return [(m.keyword, m.label, m.negated) for m in result.matches if m.dimension == dimension]


def test_project_codebook_has_no_conflicting_keywords(engine):
    assert engine.sentiment.max_len >= 4  # "how does this work"


def test_template_example_scores_positive(engine):
    r = engine.score("Kedai rohingya ni murah dan sedap, saya sokong.")
    assert r.sentiment_score == 4
    assert r.legitimacy == {"cognitive": "Granted", "pragmatic": "Granted", "moral": "NA"}
    assert not r.needs_review


def test_longest_phrase_wins_within_sentiment(engine):
    r = engine.score("tak sokong")
    assert r.sentiment_score == 2
    assert labels(r, "sentiment") == [("tak sokong", "2", False)]


def test_longest_phrase_flips_legitimacy_direction(engine):
    # "jual" alone is cognitive Granted; the full phrase is Denied.
    r = engine.score("Macam mana boleh jual kalau tak berdaftar?")
    assert r.legitimacy["cognitive"] == "Denied"
    assert ("jual", "Granted", False) not in labels(r, "cognitive")


def test_shared_keyword_counts_for_both_dimensions(engine):
    r = engine.score("Penipu!")
    assert r.sentiment_score == 1
    assert r.legitimacy["cognitive"] == "Denied"


@pytest.mark.parametrize(
    "text,score",
    [("tak murah", 2), ("not cheap", 2), ("x sedap", 1), ("tk sedap", 1), ("not worth it", 2)],
)
def test_negation(engine, text, score):
    assert engine.score(text).sentiment_score == score


def test_negation_flips_legitimacy(engine):
    assert engine.score("tak murah").legitimacy["pragmatic"] == "Denied"


def test_negator_inside_earlier_phrase_does_not_leak(engine):
    r = engine.score("tak berbaloi murah")
    assert ("murah", "4", False) in labels(r, "sentiment")


def test_negation_stops_at_punctuation(engine):
    r = engine.score("tak, murah")
    assert ("murah", "4", False) in labels(r, "sentiment")


def test_platform_name_x_is_not_a_negator(engine):
    assert engine.score("Saya nampak kat X, sedap").sentiment_score >= 4


def test_brief_sarcasm_example_is_flagged(engine):
    r = engine.score("wah bagus lah, semua orang boleh jual je tak payah lesen")
    assert "sarcasm_marker" in r.review_reasons


def test_no_keyword_gives_default_score_and_review(engine):
    r = engine.score("Hari ini hujan")
    assert r.sentiment_score == 3
    assert r.confidence == 0
    assert "no_sentiment_keyword" in r.review_reasons


def test_mixed_polarity_is_flagged(engine):
    r = engine.score("murah tapi kotor")
    assert "mixed_polarity" in r.review_reasons


def test_ambiguous_keyword_is_flagged(engine):
    assert "ambiguous_keyword:haram" in engine.score("makanan haram").review_reasons


def test_neutral_policy_na(rules):
    na_rules = rules.model_copy(deep=True)
    na_rules.legitimacy.neutral_policy = "na"
    engine = Engine(load_codebook(CONFIG / "codebook.yaml"), na_rules)
    r = engine.score("Saw another stall like this near the market.")
    assert r.sentiment_score == 3
    assert set(r.legitimacy.values()) == {"NA"}


def test_conflicting_codebook_is_rejected(rules):
    codebook = load_codebook(CONFIG / "codebook.yaml").model_copy(deep=True)
    codebook.sentiment[5].en.append("cheap")  # already score 4
    with pytest.raises(ValueError, match="cheap"):
        Engine(codebook, rules)
