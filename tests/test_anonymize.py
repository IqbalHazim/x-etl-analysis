import pytest

from xetl.anonymize import HASH_LENGTH, hash_author_id


def test_same_author_gives_same_hash():
    assert hash_author_id(12345, "salt") == hash_author_id("12345", "salt")


def test_different_salt_gives_different_hash():
    assert hash_author_id(12345, "salt-a") != hash_author_id(12345, "salt-b")


def test_hash_does_not_reveal_raw_id():
    digest = hash_author_id(987654321, "salt")
    assert len(digest) == HASH_LENGTH
    assert "987654321" not in digest


def test_empty_salt_is_rejected():
    with pytest.raises(ValueError):
        hash_author_id(1, "")
