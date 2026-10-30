# x-etl-analysis

Collects public X posts tagged **#RohingyaMalaysia**, anonymizes them, scores each post
for sentiment (1–5) and legitimacy type (cognitive / pragmatic / moral: Granted / Denied / NA)
with a rule-based keyword engine, and fills a copy of the client's Excel template.

The project plan, decisions and client questions are kept in Notion. This README covers the code.

## Contents
- [Setup](#setup)
- [Configuration](#configuration)
- [Running the pipeline](#running-the-pipeline)
- [Validation](#validation)
- [How scoring works](#how-scoring-works)
- [Data layout and privacy](#data-layout-and-privacy)
- [Development](#development)

## Setup

### Prerequisites
- Docker Desktop with WSL integration on (Settings → Resources → WSL Integration), **or**
- [uv](https://docs.astral.sh/uv/) for running locally (it installs Python 3.12 for you)

### 1. Secrets
```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # paste into XETL_AUTHOR_HASH_SALT
```
Back the salt up (e.g. a password manager). If it changes, author hashes from later runs
no longer match earlier ones.

### 2. Excel template
The client's template is not in git. Put it at:
```
templates/Rohingya_Digital_Entrepreneurship_Sentiment_Analysis.xlsx
```
It is only ever read; every export writes a new dated copy.

### 3. Build
```bash
# Docker
GIT_SHA=$(git rev-parse --short HEAD) docker compose build
docker compose run --rm xetl info

# or locally
uv sync
uv run xetl info
```
`xetl info` validates every config file and prints the keyword counts. Run it after any config edit.

In the commands below, `xetl …` means either `docker compose run --rm xetl …` or `uv run xetl …`.

### 4. X accounts (twscrape)
Collection uses [twscrape](https://github.com/vladkens/twscrape), which logs in with real X
accounts. Use dedicated accounts only, never personal ones; they can be suspended.
Account sessions are stored in `data/state/accounts.db`.

```bash
mkdir -p data/state
# accounts.txt: one account per line, in the format you pass as the second argument
docker compose run --rm --entrypoint twscrape xetl --db data/state/accounts.db \
    add_accounts data/state/accounts.txt username:password:email:email_password
docker compose run --rm --entrypoint twscrape xetl --db data/state/accounts.db login_accounts
docker compose run --rm --entrypoint twscrape xetl --db data/state/accounts.db accounts
```
Locally, replace `docker compose run --rm --entrypoint twscrape xetl` with `uv run twscrape`.
Purchased accounts often come with cookies instead; see `twscrape add_cookie --help`.
Delete `accounts.txt` once the accounts are added.

## Configuration

| File | What it controls |
|---|---|
| `config/codebook.yaml` | Sentiment and legitimacy keywords (from the brief). The only place keywords live. |
| `config/hashtags.yaml` | Hashtag, variants, typos to watch, whether `#Rohingya #Malaysia` counts, collection window. |
| `config/rules.yaml` | How keywords are matched and combined: negators, slang spellings, conflict rule, review triggers. |
| `config/stopwords_bm.txt` | Malay words left out of the word cloud. |
| `.env` | Secrets and path overrides (see `.env.example`). |

In Docker, `config/` is mounted, so edits apply without rebuilding.

## Running the pipeline

Each run has a name (`--run`, default `pilot`) and its own folders, so the pilot and the
full run never mix.

```bash
xetl pick-week --seed 7                  # random pilot week inside the window; record the seed
xetl pilot --since 2026-06-08 --until 2026-06-15   # all steps below in one go
```

Or step by step:

| Command | Reads | Writes |
|---|---|---|
| `xetl extract --since D --until D` | X search | `data/raw/<run>/<day>.jsonl` |
| `xetl transform` | raw | `data/interim/<run>/tweets.parquet` |
| `xetl analyze` | interim | `data/processed/<run>/coded.parquet`, `data/outputs/<run>/review_queue.csv` |
| `xetl stats` | interim + processed | `data/outputs/<run>/pilot_stats.md` |
| `xetl export` | processed | `data/outputs/<run>/<template>_<run>_<date>.xlsx`, `wordcloud.png`, `word_frequencies.csv` |

- `--until` is exclusive: `--since 2026-06-08 --until 2026-06-15` is 7 days.
- Without `--since/--until`, `extract` uses the window in `hashtags.yaml` (the full run).
- Extraction runs one day at a time. If it stops, run the same command again; finished days
  are skipped. To re-pull a day, delete its `.jsonl` file.
- Every step appends to `data/manifests/<run>.json` (parameters, counts, git SHA), so results
  can be traced back to the exact code and config.

### What the exported workbook contains
- **Raw_Data / Coded_Data**: the example rows are replaced with real data, and `sentiment_band` stays a formula.
- **Sentiment_Summary / Legitimacy_Summary**: formula ranges are stretched to the real row
  count, so the three built-in charts cover all rows. Excel recalculates when the file is opened.
- **Word_Cloud**: the generated image plus the top 50 words.
- **Engine_Trace** (new sheet): why each post got its score, and whether it needs review.

`manually_reviewed` is written as `N`; reviewers set it to `Y` after checking a post.

## Validation

The brief requires a human check: 100–150 posts, 2 coders, Cohen's κ ≥ 0.7.

```bash
xetl validate sample --n 150 --seed 42
# send data/outputs/<run>/validation/coding_sheet_coder1.xlsx and _coder2.xlsx to the coders
xetl validate score --coder1 path/to/coder1.xlsx --coder2 path/to/coder2.xlsx
# resolve disagreements in data/outputs/<run>/validation/adjudication.xlsx, then:
xetl validate score --coder1 ... --coder2 ... --adjudicated path/to/adjudication.xlsx
```

- The coding sheets don't show the engine's labels, so coders aren't influenced by them.
- The sample is stratified across sentiment bands.
- `validation_report.md` contains:
  - inter-coder κ (quadratic-weighted for the 1–5 score)
  - engine vs gold κ and accuracy
  - per-class precision and recall
  - **per-keyword precision**, lowest first: the keywords to fix in codebook v2.

## How scoring works

The engine (`src/xetl/engine.py`) is rule-based (Option A), using only the codebook.

1. **Clean.** URLs become `<URL>` and @handles become `@user`. The text is split into clauses at
   punctuation, then into lowercase tokens. Slang spellings are rewritten (`tk`→`tak`,
   `sdp`→`sedap`, lowercase `x`→`tak`; uppercase `X`, the platform, is left alone).
2. **Match each dimension separately.** Sentiment, cognitive, pragmatic and moral each have their
   own matcher, so one phrase can count for several (e.g. `penipu` is sentiment 1 and cognitive Denied,
   as the brief intends). Within a dimension the **longest phrase wins**:
   - `tak sokong` (2) is matched instead of `sokong` (4)
   - `macam mana boleh jual` (cognitive Denied) is matched instead of `jual` (Granted)
3. **Negation.** A negator up to 2 tokens before a keyword flips it: `tak murah` → sentiment 2,
   pragmatic Denied. Negation doesn't reach past punctuation or into an earlier match.
4. **Combine.**
   - Sentiment is the rounded mean of the matched scores (`combine: mean`). No match gives 3.
   - Each legitimacy type takes the majority direction. A tie gives NA and a review flag.
5. **Confidence** (`model_confidence`): the share of matched sentiment keywords that agree with the
   final band. 0 when nothing matched.
6. **Review flags** (`needs_review`, with reasons):
   - no sentiment keyword
   - mixed polarity
   - confidence below 0.6
   - sarcasm cue alongside a positive match (the brief's `wah bagus lah…` example)
   - ambiguous keyword (`haram`, `best`, …)
   - tied legitimacy

All thresholds and lists are in `config/rules.yaml`.

**Known limits:**
- Keywords not in the codebook score nothing.
- Sarcasm is only flagged, never corrected.
- X search results are not exhaustive.

The validation report measures how much these matter.

## Data layout and privacy

```
data/                      (gitignored; mounted into Docker)
  state/accounts.db        twscrape sessions — treat as a secret
  raw/<run>/               sanitized posts, one file per day
  interim/<run>/           cleaned + classified posts
  processed/<run>/         scored posts
  outputs/<run>/           reports, workbook, word cloud, validation files
  manifests/<run>.json     run history
```

- **No usernames are stored anywhere.** Records are sanitized during extraction, before they
  reach disk. Author IDs become an HMAC-SHA256 hash (keyed with the secret salt, 16 hex
  characters), and @handles in the text become `@user`. Display names and profile data are
  never kept.
- A plain hash of a numeric user ID could be reversed by hashing every ID. The secret salt
  prevents that.
- Keep `data/` and `.env` out of git and shared drives. Delete raw data at the end of the project
  as agreed with the client.

## Development

```bash
uv run pytest          # 45 tests; the export test needs the template in templates/
```

| Module | Responsibility |
|---|---|
| `config.py` | Settings from `.env` |
| `codebook.py`, `rules.py`, `hashtags.py` | Load and validate the config files (unknown keys are errors) |
| `text.py` | Cleaning and tokenization |
| `engine.py` | Keyword matching and scoring |
| `extract.py` → `transform.py` → `analyze.py` → `stats.py` / `export.py` | Pipeline stages |
| `validation.py` | Coding sheets, κ, keyword precision |
| `manifest.py` | Run history |
| `cli.py` | `xetl` commands |

Packaging: `uv build` produces a wheel with the `xetl` command. The Docker image is the
supported way to run the pipeline.
