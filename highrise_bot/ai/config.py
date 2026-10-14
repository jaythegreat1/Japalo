"""AI settings, read from environment variables (Railway/Replit variables or a shell export).

Routes, in the order the brain tries them:
  1. Groq (when GROQ_API_KEY is set): each model in GROQ_MODELS
  2. OmniRoute (when OMNIROUTE_URL is set, or when there is no Groq key):
     OMNIROUTE_MODEL, then each of OMNIROUTE_FALLBACK_MODELS
Everything has a default, so the bot runs without any of these set; the AI just
answers "my brain is taking a nap" until a route is reachable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..constants import ROOT
from .brain import Route

GROQ_URL = "https://api.groq.com/openai/v1"
# Groq's free-tier chat models (Llama 3.x was shut off for free keys on 2026-08-16).
# Limits are per model, so a second model adds capacity: 30 req/min, 8K tokens/min each.
GROQ_DEFAULT_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class AIConfig:
    bot_name: str = "Japalo"
    groq_api_key: str = ""
    groq_url: str = GROQ_URL
    groq_models: list[str] = field(default_factory=lambda: list(GROQ_DEFAULT_MODELS))
    groq_min_interval: float = 2.0
    groq_reasoning_effort: str = "low"  # gpt-oss thinks less, answers faster, uses fewer tokens
    use_omniroute: bool = True
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
        cfg.groq_api_key = env.get("GROQ_API_KEY", "").strip()
        cfg.groq_url = env.get("GROQ_URL", cfg.groq_url).strip().rstrip("/") or GROQ_URL
        if env.get("GROQ_MODELS", "").strip():
            cfg.groq_models = _csv(env["GROQ_MODELS"])
        cfg.groq_min_interval = float(env.get("GROQ_MIN_INTERVAL", cfg.groq_min_interval))
        cfg.groq_reasoning_effort = env.get("GROQ_REASONING_EFFORT", cfg.groq_reasoning_effort).strip()
        # OmniRoute is the fallback: on when its URL is set, or when Groq isn't configured.
        cfg.use_omniroute = bool(env.get("OMNIROUTE_URL", "").strip()) or not cfg.groq_api_key
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

    def routes(self) -> list[Route]:
        routes = []
        if self.groq_api_key:
            for model in self.groq_models:
                extra = {}
                if model.startswith("openai/gpt-oss") and self.groq_reasoning_effort:
                    extra = {"reasoning_effort": self.groq_reasoning_effort}
                routes.append(Route("groq", self.groq_url, model, self.groq_api_key,
                                    self.groq_min_interval, extra))
        if self.use_omniroute:
            names = [self.model] + [m for m in self.fallback_models if m != self.model]
            routes += [
                Route("omniroute", self.omniroute_url, name, self.omniroute_key, self.min_interval)
                for name in names
            ]
        return routes
