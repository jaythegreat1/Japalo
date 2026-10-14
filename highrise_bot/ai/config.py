"""AI settings, read from environment variables (Replit Secrets or a shell export).

Everything has a default, so the bot runs without any of these set; the AI just
answers "my brain is taking a nap" until OmniRoute is reachable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..constants import ROOT


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class AIConfig:
    bot_name: str = "Japalo"
    omniroute_url: str = "http://localhost:20128/v1"
    omniroute_key: str = ""
    model: str = "auto"
    fallback_models: list[str] = field(default_factory=list)
    timeout: float = 45.0
    min_interval: float = 4.0
    rate_limit_wait: float = 15.0
    max_history: int = 12
    user_cooldown: float = 4.0
    memory_path: Path = ROOT / "data" / "ai_memory.json"

    @classmethod
    def from_env(cls) -> "AIConfig":
        env = os.environ
        cfg = cls()
        cfg.bot_name = env.get("BOT_NAME", cfg.bot_name).strip() or cfg.bot_name
        cfg.omniroute_url = env.get("OMNIROUTE_URL", cfg.omniroute_url).strip().rstrip("/")
        cfg.omniroute_key = env.get("OMNIROUTE_API_KEY", "").strip()
        cfg.model = env.get("OMNIROUTE_MODEL", cfg.model).strip() or cfg.model
        cfg.fallback_models = _csv(env.get("OMNIROUTE_FALLBACK_MODELS", ""))
        cfg.timeout = float(env.get("OMNIROUTE_TIMEOUT", cfg.timeout))
        cfg.min_interval = float(env.get("OMNIROUTE_MIN_INTERVAL", cfg.min_interval))
        cfg.rate_limit_wait = float(env.get("OMNIROUTE_RATE_LIMIT_WAIT", cfg.rate_limit_wait))
        cfg.max_history = int(env.get("AI_MAX_HISTORY", cfg.max_history))
        cfg.user_cooldown = float(env.get("AI_USER_COOLDOWN", cfg.user_cooldown))
        if env.get("AI_MEMORY_FILE"):
            cfg.memory_path = ROOT / env["AI_MEMORY_FILE"]
        return cfg
