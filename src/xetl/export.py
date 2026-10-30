"""Export: fill a dated copy of the client's Excel template, plus the word cloud.

The template itself is never modified. In the copy we:
- replace the example rows in Raw_Data and Coded_Data with real data,
- keep the sentiment_band formula per row,
- stretch the summary formulas (fixed at rows 2-16 in the template) to the real row count,
- fill the Word_Cloud sheet with the generated image and frequency table,
- add an Engine_Trace sheet explaining each score (new sheet; existing headers untouched).
The three built-in charts read the summary sheets, so they update when Excel recalculates.
"""

import re
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.drawing.image import Image
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet
from wordcloud import STOPWORDS, WordCloud

from xetl.config import Settings
from xetl.hashtags import HashtagConfig
from xetl.rules import Rules
from xetl.text import segments

RANGE_RE = re.compile(r"Coded_Data!\$([A-Z]+)\$2:\$\1\$\d+")
BAND_FORMULA = '=IF(C{r}<=2,"Negative",IF(C{r}=3,"Neutral","Positive"))'
WORD_TABLE_FIRST_ROW = 26  # Word_Cloud!A25 holds the "Word | Frequency" header
WORD_TABLE_SIZE = 50
TRACE_COLUMNS = ["tweet_id", "post_type", "hashtag_match", "lang_detected", "needs_review",
                 "review_reasons", "matched_keywords"]  # fmt: skip


def write_row(ws: Worksheet, row: int, values: list) -> None:
    for col, value in enumerate(values, start=1):
        if isinstance(value, str):
            value = ILLEGAL_CHARACTERS_RE.sub("", value)
        cell = ws.cell(row=row, column=col, value=value)
        # A tweet starting with "=" must stay text, never become a formula.
        if isinstance(value, str) and value.startswith("="):
            cell.data_type = "s"


def clear_below(ws: Worksheet, first_row: int) -> None:
    if ws.max_row >= first_row:
        ws.delete_rows(first_row, ws.max_row - first_row + 1)


def word_frequencies(
    texts: pd.Series, rules: Rules, stopwords: set[str], hashtags: HashtagConfig
) -> Counter:
    m = rules.matching
    skip = stopwords | {w.lower() for w in STOPWORDS} | {t.lower() for t in hashtags.tags}
    freq: Counter = Counter()
    for text in texts:
        for tokens in segments(text, m.spelling, m.spelling_case_sensitive):
            freq.update(t for t in tokens if len(t) > 1 and not t.isdigit() and t not in skip)
    return freq


def load_stopwords(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return {w.strip().lower() for w in lines if w.strip() and not w.startswith("#")}


def render_wordcloud(freq: Counter, path: Path) -> Path | None:
    if not freq:
        return None
    cloud = WordCloud(width=1600, height=800, background_color="white", collocations=False)
    cloud.generate_from_frequencies(dict(freq.most_common(200)))
    cloud.to_file(str(path))
    return path


def write_workbook(
    template: Path, out: Path, coded: pd.DataFrame, freq: Counter, image: Path | None, tz: str
) -> Path:
    wb = load_workbook(template)
    n = len(coded)
    last_row = max(n + 1, 2)

    raw = wb["Raw_Data"]
    clear_below(raw, 2)
    timestamps = coded["timestamp"].dt.tz_convert(tz).dt.strftime("%Y-%m-%d %H:%M")
    for i, (row, ts) in enumerate(zip(coded.itertuples(index=False), timestamps, strict=True)):
        write_row(raw, i + 2, [
            row.tweet_id, ts, row.text, " ".join(f"#{h}" for h in row.hashtags),
            row.like_count, row.retweet_count, row.reply_count, row.quote_count,
            row.author_id_hash, row.lang,
        ])  # fmt: skip

    coded_ws = wb["Coded_Data"]
    clear_below(coded_ws, 2)
    for i, row in enumerate(coded.itertuples(index=False)):
        r = i + 2
        write_row(coded_ws, r, [
            row.tweet_id, row.text_clean, int(row.sentiment_score), BAND_FORMULA.format(r=r),
            row.legitimacy_cognitive, row.legitimacy_pragmatic, row.legitimacy_moral,
            float(row.model_confidence), "N",  # manually_reviewed: set to Y by the reviewer
        ])  # fmt: skip

    for name in ("Sentiment_Summary", "Legitimacy_Summary"):
        for ws_row in wb[name].iter_rows():
            for cell in ws_row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cell.value = RANGE_RE.sub(rf"Coded_Data!$\1$2:$\1${last_row}", cell.value)
        wb[name]["A2"] = f"Reads automatically from Coded_Data (rows 2-{last_row})."

    cloud = wb["Word_Cloud"]
    cloud._images = []
    cloud["A2"] = f"Generated from {n} posts on {date.today().isoformat()}."
    clear_below(cloud, WORD_TABLE_FIRST_ROW)
    for i, (word, count) in enumerate(freq.most_common(WORD_TABLE_SIZE)):
        write_row(cloud, WORD_TABLE_FIRST_ROW + i, [word, count])
    if image:
        picture = Image(str(image))
        picture.width, picture.height = 800, 400
        cloud.add_image(picture, "A3")

    if "Engine_Trace" in wb.sheetnames:
        del wb["Engine_Trace"]
    trace = wb.create_sheet("Engine_Trace")
    write_row(trace, 1, TRACE_COLUMNS)
    for cell in trace[1]:
        cell.font = Font(bold=True)
    for i, row in enumerate(coded[TRACE_COLUMNS].itertuples(index=False)):
        values = list(row)
        values[4] = "Y" if values[4] else "N"
        write_row(trace, i + 2, values)

    wb.calculation.fullCalcOnLoad = True  # formulas have no cached values until Excel recalcs
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def run_export(settings: Settings, rules: Rules, hashtags: HashtagConfig, run: str) -> Path:
    if not settings.template_path.exists():
        raise FileNotFoundError(f"Template not found at {settings.template_path} (see README).")
    coded_path = settings.stage_dir("processed", run) / "coded.parquet"
    if not coded_path.exists():
        raise FileNotFoundError(f"{coded_path} not found. Run `xetl analyze` first.")
    coded = pd.read_parquet(coded_path)

    out_dir = settings.stage_dir("outputs", run)
    out_dir.mkdir(parents=True, exist_ok=True)
    freq = word_frequencies(
        coded["text_clean"], rules, load_stopwords(settings.stopwords_path), hashtags
    )
    pd.DataFrame(freq.most_common(), columns=["word", "frequency"]).to_csv(
        out_dir / "word_frequencies.csv", index=False
    )
    image = render_wordcloud(freq, out_dir / "wordcloud.png")

    name = f"{settings.template_path.stem}_{run}_{date.today().isoformat()}.xlsx"
    return write_workbook(
        settings.template_path, out_dir / name, coded, freq, image, settings.timezone
    )
