"""Command-line entry point: 'xetl <command>'.

Stage modules (twscrape, lingua, wordcloud) are imported inside their commands,
so `xetl info` and `--help` stay fast.
"""

import logging
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import typer

from xetl.codebook import KeywordSet, load_codebook
from xetl.config import Settings, get_settings
from xetl.engine import Engine
from xetl.hashtags import load_hashtags
from xetl.manifest import record_step
from xetl.rules import load_rules

app = typer.Typer(help="X ETL and sentiment/legitimacy analysis.", no_args_is_help=True)
validate_app = typer.Typer(help="Human validation: coding sheets and kappa.", no_args_is_help=True)
app.add_typer(validate_app, name="validate")

RunOpt = typer.Option("pilot", "--run", "-r", help="Run name; keeps each run's data separate.")
DateOpt = {"formats": ["%Y-%m-%d"]}


def _engine(settings: Settings) -> Engine:
    return Engine(load_codebook(settings.codebook_path), load_rules(settings.rules_path))


def _window(since: datetime | None, until: datetime | None) -> tuple[date, date]:
    window = load_hashtags(get_settings().hashtags_path).window
    return (since.date() if since else window.since), (until.date() if until else window.until)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    level = "DEBUG" if verbose else get_settings().log_level
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@app.command()
def info() -> None:
    """Show resolved settings and validate all config files (smoke test)."""
    settings = get_settings()
    codebook = load_codebook(settings.codebook_path)
    load_rules(settings.rules_path)
    hashtags = load_hashtags(settings.hashtags_path)

    typer.echo(f"data dir:    {settings.data_dir.resolve()}")
    typer.echo(f"template:    {_status(settings.template_path)}")
    typer.echo(f"accounts db: {_status(settings.accounts_db)}")
    typer.echo(f"hashtags:    {', '.join('#' + t for t in hashtags.tags)}")
    typer.echo(f"window:      {hashtags.window.since} to {hashtags.window.until} (exclusive)")
    typer.echo(f"codebook v{codebook.version}")
    for score, level in codebook.sentiment.items():
        typer.echo(f"   sentiment {score} {level.band:<18} {_counts(level)}")
    for kind, direction in codebook.legitimacy.items():
        typer.echo(f"   {kind:<9} granted   {_counts(direction.granted)}")
        typer.echo(f"   {kind:<9} denied    {_counts(direction.denied)}")
    _engine(settings)  # builds the matchers, so keyword conflicts surface here
    typer.echo("config OK")


@app.command("pick-week")
def pick_week(seed: int = typer.Option(..., help="Record this seed in Notion.")) -> None:
    """Pick a random 7-day pilot window inside the configured collection window."""
    window = load_hashtags(get_settings().hashtags_path).window
    weeks = (window.until - window.since).days // 7
    start = window.since + timedelta(weeks=random.Random(seed).randrange(weeks))
    typer.echo(f"--since {start} --until {start + timedelta(days=7)}")


@app.command()
def extract(
    run: str = RunOpt,
    since: datetime = typer.Option(None, help="First day (default: config window).", **DateOpt),
    until: datetime = typer.Option(None, help="Day after the last (exclusive).", **DateOpt),
    limit_per_day: int = typer.Option(-1, help="Max posts per day; -1 for no limit."),
) -> None:
    """Search X day by day and save sanitized posts to data/raw/<run>/."""
    from xetl.extract import run_extract

    settings = get_settings()
    hashtags = load_hashtags(settings.hashtags_path)
    start, end = _window(since, until)
    counts = run_extract(settings, hashtags, run, start, end, limit_per_day)
    record_step(settings, run, "extract", since=start, until=end, posts_per_day=counts,
                hashtags=hashtags.model_dump(mode="json"))  # fmt: skip
    typer.echo(f"extracted {sum(counts.values())} posts over {len(counts)} days")


@app.command()
def transform(run: str = RunOpt) -> None:
    """Merge, dedupe and clean raw posts into data/interim/<run>/tweets.parquet."""
    from xetl.transform import run_transform

    settings = get_settings()
    df = run_transform(settings, load_hashtags(settings.hashtags_path), run)
    in_scope = int(df["in_scope"].sum())
    record_step(settings, run, "transform", posts=len(df), in_scope=in_scope)
    typer.echo(f"{len(df)} posts, {in_scope} in scope")


@app.command()
def analyze(run: str = RunOpt) -> None:
    """Score in-scope posts into data/processed/<run>/coded.parquet."""
    from xetl.analyze import run_analyze

    settings = get_settings()
    coded = run_analyze(settings, _engine(settings), run)
    flagged = int(coded["needs_review"].sum())
    record_step(settings, run, "analyze", scored=len(coded), needs_review=flagged,
                rules=load_rules(settings.rules_path).model_dump())  # fmt: skip
    typer.echo(f"scored {len(coded)} posts, {flagged} flagged for review")


@app.command()
def stats(run: str = RunOpt) -> None:
    """Write the pilot statistics report to data/outputs/<run>/pilot_stats.md."""
    from xetl.stats import run_stats

    settings = get_settings()
    out = run_stats(settings, load_hashtags(settings.hashtags_path), run)
    typer.echo(out.read_text(encoding="utf-8"))
    typer.echo(f"written to {out}")


@app.command()
def export(run: str = RunOpt) -> None:
    """Fill a dated copy of the Excel template in data/outputs/<run>/."""
    from xetl.export import run_export

    settings = get_settings()
    rules, hashtags = load_rules(settings.rules_path), load_hashtags(settings.hashtags_path)
    out = run_export(settings, rules, hashtags, run)
    record_step(settings, run, "export", workbook=out.name)
    typer.echo(f"workbook written to {out}")


@app.command()
def pilot(
    run: str = RunOpt,
    since: datetime = typer.Option(..., help="First day of the pilot week.", **DateOpt),
    until: datetime = typer.Option(..., help="Day after the last (exclusive).", **DateOpt),
) -> None:
    """Run extract, transform, analyze, stats and export in one go."""
    extract(run=run, since=since, until=until, limit_per_day=-1)
    transform(run=run)
    analyze(run=run)
    stats(run=run)
    export(run=run)


@validate_app.command("sample")
def validate_sample(
    run: str = RunOpt,
    n: int = typer.Option(150, help="Sample size (brief: 100-150)."),
    seed: int = typer.Option(42, help="Random seed; record it in Notion."),
) -> None:
    """Draw a stratified sample and write one blind coding sheet per coder."""
    from xetl.validation import draw_sample, write_coding_sheet

    settings = get_settings()
    coded = pd.read_parquet(settings.stage_dir("processed", run) / "coded.parquet")
    sample = draw_sample(coded, n, seed)
    out_dir = settings.stage_dir("outputs", run) / "validation"
    for coder in ("coder1", "coder2"):
        write_coding_sheet(sample, out_dir / f"coding_sheet_{coder}.xlsx")
    sample[["tweet_id"]].to_csv(out_dir / "sample_ids.csv", index=False)
    record_step(settings, run, "validate-sample", n=len(sample), seed=seed)
    typer.echo(f"{len(sample)} tweets; coding sheets in {out_dir}")


@validate_app.command("score")
def validate_score(
    coder1: Path = typer.Option(..., exists=True, help="Completed sheet from coder 1."),
    coder2: Path = typer.Option(..., exists=True, help="Completed sheet from coder 2."),
    adjudicated: Path = typer.Option(None, exists=True, help="Resolved adjudication.xlsx."),
    run: str = RunOpt,
) -> None:
    """Inter-coder kappa, engine vs gold, and per-keyword precision."""
    from xetl.validation import score_validation

    settings = get_settings()
    coded = pd.read_parquet(settings.stage_dir("processed", run) / "coded.parquet")
    out_dir = settings.stage_dir("outputs", run) / "validation"
    out = score_validation(coded, coder1, coder2, out_dir, adjudicated)
    record_step(settings, run, "validate-score", report=out.name)
    typer.echo(out.read_text(encoding="utf-8"))


def _status(path: Path) -> str:
    return f"{path} ({'found' if path.exists() else 'MISSING'})"


def _counts(keywords: KeywordSet) -> str:
    return f"en={len(keywords.en):>2} bm={len(keywords.bm):>2}"
