"""Application configuration (env-driven)."""
import json
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # apps/server
DATA_DIR = BASE_DIR.parent / "data"  # lifeos/data


class Settings(BaseSettings):
    app_name: str = "LifeOS"
    database_url: str = f"sqlite+aiosqlite:///{DATA_DIR / 'lifeos.db'}"
    jwt_secret: str = "lifeos-dev-secret-change-me"
    jwt_expire_hours: int = 24 * 7
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-5.3-flash"  # glm-4-flash retired (error 1314)
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    llm_cache_hours: int = 24
    files_dir: Path = DATA_DIR / "files"
    daily_summary_hour: int = 21
    daily_summary_minute: int = 30

    model_config = {"env_prefix": "LIFEOS_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.files_dir.mkdir(parents=True, exist_ok=True)


def _load_or_create_jwt_secret() -> str:
    """64+ char random secret, auto-generated on first start and persisted (P2-1)."""
    import secrets

    if settings.jwt_secret and len(settings.jwt_secret) >= 32 and settings.jwt_secret != "lifeos-dev-secret-change-me":
        return settings.jwt_secret
    secret_file = DATA_DIR / "secret.key"
    if secret_file.exists():
        s = secret_file.read_text(encoding="utf-8").strip()
        if len(s) >= 32:
            return s
    s = secrets.token_urlsafe(64)
    secret_file.write_text(s, encoding="utf-8")
    return s


settings.jwt_secret = _load_or_create_jwt_secret()

# ---- LLM runtime overrides persisted to data/llm_config.json (base_url/model/api_key) ----
LLM_CONFIG_PATH = DATA_DIR / "llm_config.json"


def load_llm_config() -> dict:
    if LLM_CONFIG_PATH.exists():
        try:
            return json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_llm_config(cfg: dict) -> None:
    LLM_CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
