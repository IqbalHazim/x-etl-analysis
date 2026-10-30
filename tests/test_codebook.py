from pathlib import Path

import pytest
from pydantic import ValidationError

from xetl.codebook import Codebook, load_codebook

CODEBOOK = Path(__file__).parents[1] / "config" / "codebook.yaml"


def minimal_codebook() -> dict:
    keywords = {"en": ["a"], "bm": ["b"]}
    return {
        "version": 1,
        "sentiment": {score: {"band": "x", **keywords} for score in range(1, 6)},
        "legitimacy": {
            kind: {"granted": keywords, "denied": keywords}
            for kind in ("cognitive", "pragmatic", "moral")},
    }


def test_project_codebook_loads():
    codebook = load_codebook(CODEBOOK)
    assert sorted(codebook.sentiment) == [1, 2, 3, 4, 5]
    assert set(codebook.legitimacy) == {"cognitive", "pragmatic", "moral"}


def test_keywords_shared_across_dimensions_are_kept():
    # The brief intends some keywords to count for both sentiment and legitimacy.
    codebook = load_codebook(CODEBOOK)
    assert "penipu" in codebook.sentiment[1].bm
    assert "penipu" in codebook.legitimacy["cognitive"].denied.bm


def test_keywords_are_normalized():
    data = minimal_codebook()
    data["sentiment"][1]["en"] = ["  Hate "]
    assert Codebook.model_validate(data).sentiment[1].en == ["hate"]


def test_missing_score_is_rejected():
    data = minimal_codebook()
    del data["sentiment"][3]
    with pytest.raises(ValidationError, match="scores 1-5"):
        Codebook.model_validate(data)


def test_duplicate_keyword_is_rejected():
    data = minimal_codebook()
    data["sentiment"][1]["en"] = ["hate", "Hate "]
    with pytest.raises(ValidationError, match="duplicate"):
        Codebook.model_validate(data)


def test_unknown_key_is_rejected():
    data = minimal_codebook()
    data["seniment"] = data.pop("sentiment")
    with pytest.raises(ValidationError):
        Codebook.model_validate(data)


def test_yaml_boolean_keyword_is_rejected():
    # Unquoted `no` in YAML loads as False, which must not slip through as a keyword.
    data = minimal_codebook()
    data["sentiment"][1]["en"] = [False]
    with pytest.raises(ValidationError):
        Codebook.model_validate(data)
