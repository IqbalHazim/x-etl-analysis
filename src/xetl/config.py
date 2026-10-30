"""Runtime settings, read from environment variables (prefix XETL_) or `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XETL_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    config_dir: Path = Path("config")
    template_path: Path = Path("templates/Rohingya_Digital_Entrepreneurship_Sentiment_Analysis.xlsx")
    accounts_db: Path = Path("data/state/accounts.db")
    author_hash_salt: SecretStr  # required, no default, so it fails loudly if missing
    # Days in stats and timestamps in the workbook are shown in this time zone.
    timezone: str = "Asia/Kuala_Lumpur"
    log_level: str = "INFO"
    git_sha: str = "unknown"  # set by the Docker build; locally read from git instead

    @property
    def codebook_path(self) -> Path:
        return self.config_dir / "codebook.yaml"

    @property
    def hashtags_path(self) -> Path:
        return self.config_dir / "hashtags.yaml"

    @property
    def rules_path(self) -> Path:
        return self.config_dir / "rules.yaml"

    @property
    def stopwords_path(self) -> Path:
        return self.config_dir / "stopwords_bm.txt"

    def stage_dir(self, stage: str, run: str) -> Path:
        """Folder for one pipeline stage of one run, e.g. data/raw/pilot."""
        return self.data_dir / stage / run


@lru_cache
def get_settings() -> Settings:
    return Settings()
