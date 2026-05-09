"""Runtime configuration loaded from env vars with sensible defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


REPO_ROOT = Path(__file__).resolve().parents[3]
_load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    model_fast: str
    model_deep: str
    db_path: Path
    http_timeout: float
    http_ua: str
    repo_root: Path

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


def load_settings() -> Settings:
    db_path = Path(os.environ.get("INTEL_DB_PATH", "data/intel.db"))
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        model_fast=os.environ.get("INTEL_MODEL_FAST", "claude-haiku-4-5"),
        model_deep=os.environ.get("INTEL_MODEL_DEEP", "claude-sonnet-4-6"),
        db_path=db_path,
        http_timeout=float(os.environ.get("INTEL_HTTP_TIMEOUT", "20")),
        http_ua=os.environ.get("INTEL_HTTP_UA", "ai-intel/0.1 (+research)"),
        repo_root=REPO_ROOT,
    )


settings = load_settings()
