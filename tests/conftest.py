from pathlib import Path

import pytest

from xetl.codebook import load_codebook
from xetl.engine import Engine
from xetl.hashtags import load_hashtags
from xetl.rules import load_rules

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "config"
TEMPLATE = ROOT / "templates" / "Rohingya_Digital_Entrepreneurship_Sentiment_Analysis.xlsx"


@pytest.fixture(scope="session")
def rules():
    return load_rules(CONFIG / "rules.yaml")


@pytest.fixture(scope="session")
def hashtags():
    return load_hashtags(CONFIG / "hashtags.yaml")


@pytest.fixture(scope="session")
def engine(rules):
    return Engine(load_codebook(CONFIG / "codebook.yaml"), rules)
