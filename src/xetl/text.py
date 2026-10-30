"""Text cleaning and tokenization shared by the engine and the word cloud."""

import re
import unicodedata

URL_RE = re.compile(r"https?://\S+")
MENTION_RE = re.compile(r"(?<!\w)@\w{1,15}")
# Keywords never span these, and a negator before one does not reach past them.
SEGMENT_BREAK_RE = re.compile(r"[.,!?;:()\[\]\"\n…]+|\s[-–—]\s")
TOKEN_RE = re.compile(r"[\w']+(?:-[\w']+)*")
QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def mask_mentions(text: str) -> str:
    """Replace @handles with @user, so no usernames are stored."""
    return MENTION_RE.sub("@user", text)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(QUOTES)
    text = URL_RE.sub("<URL>", text)
    text = mask_mentions(text)
    return " ".join(text.split())


def segments(
    text: str,
    spelling: dict[str, str] | None = None,
    spelling_case_sensitive: dict[str, str] | None = None,
) -> list[list[str]]:
    """Split text into clauses of normalized lowercase tokens."""
    spelling = spelling or {}
    spelling_case_sensitive = spelling_case_sensitive or {}
    result = []
    for part in SEGMENT_BREAK_RE.split(text):
        tokens = []
        for raw in TOKEN_RE.findall(part):
            raw = raw.strip("'")
            if not raw:
                continue
            token = spelling_case_sensitive.get(raw, raw).lower()
            tokens.append(spelling.get(token, token))
        if tokens:
            result.append(tokens)
    return result
