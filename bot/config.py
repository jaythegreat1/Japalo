"""Settings for the bot, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file without overriding real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _csv(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


@dataclass
class Config:
    room_id: str
    api_token: str
    omniroute_url: str = "http://localhost:20128/v1"
    omniroute_key: str = ""
    model: str = "auto"
    bot_name: str = "Japalo"
    owners: set[str] = field(default_factory=set)
    prefix: str = "!"
    user_cooldown: float = 4.0
    request_timeout: float = 45.0
    max_history: int = 12
    data_dir: Path = Path("data")
    system_prompt: str = (
        "You are {name}, a friendly, witty AI living in a Highrise room. "
        "Keep answers short (1-3 sentences) because chat bubbles are small. "
        "Never pretend to be a human moderator and never ask for passwords."
    )

    @classmethod
    def from_env(cls, env_file: str | os.PathLike = ".env") -> "Config":
        _load_dotenv(Path(env_file))
        room_id = os.environ.get("HIGHRISE_ROOM_ID", "")
        api_token = os.environ.get("HIGHRISE_API_TOKEN", "")
        cfg = cls(room_id=room_id, api_token=api_token)
        cfg.omniroute_url = os.environ.get("OMNIROUTE_URL", cfg.omniroute_url).rstrip("/")
        cfg.omniroute_key = os.environ.get("OMNIROUTE_API_KEY", cfg.omniroute_key)
        cfg.model = os.environ.get("OMNIROUTE_MODEL", cfg.model)
        cfg.bot_name = os.environ.get("BOT_NAME", cfg.bot_name)
        cfg.owners = _csv(os.environ.get("BOT_OWNERS", ""))
        cfg.prefix = os.environ.get("BOT_PREFIX", cfg.prefix)
        cfg.user_cooldown = float(os.environ.get("BOT_USER_COOLDOWN", cfg.user_cooldown))
        cfg.request_timeout = float(os.environ.get("OMNIROUTE_TIMEOUT", cfg.request_timeout))
        cfg.max_history = int(os.environ.get("BOT_MAX_HISTORY", cfg.max_history))
        cfg.data_dir = Path(os.environ.get("BOT_DATA_DIR", str(cfg.data_dir)))
        if os.environ.get("BOT_SYSTEM_PROMPT"):
            cfg.system_prompt = os.environ["BOT_SYSTEM_PROMPT"]
        return cfg

    def missing(self) -> list[str]:
        """Names of required settings that are not set."""
        missing = []
        if not self.room_id:
            missing.append("HIGHRISE_ROOM_ID")
        if not self.api_token:
            missing.append("HIGHRISE_API_TOKEN")
        return missing
