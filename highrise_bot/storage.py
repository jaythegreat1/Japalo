"""Real persistence, backed by SQLite (one local file — no external service,
no connection string secret, free on any host, and trivial to inspect from
a phone via the Replit Shell with `sqlite3 data/bot.db`).

Kept behind a small class so a later move to Postgres (e.g. to share data
with a web dashboard) only means swapping this module's internals, not
every call site in bot.py.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS warnings (
    user_id TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS warning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    actor_id TEXT,
    reason TEXT NOT NULL,
    source TEXT NOT NULL,
    count INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS moderation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    moderator_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    duration INTEGER,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    user_id TEXT PRIMARY KEY,
    points INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS score_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    points INTEGER NOT NULL,
    game TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS user_stats (
    user_id TEXT PRIMARY KEY,
    joins INTEGER NOT NULL DEFAULT 0,
    xp INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tips (
    user_id TEXT PRIMARY KEY,
    gold INTEGER NOT NULL DEFAULT 0,
    tip_count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS favorites (
    user_id TEXT NOT NULL,
    slot INTEGER NOT NULL,
    emote_number INTEGER NOT NULL,
    PRIMARY KEY (user_id, slot)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usernames (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS captured_emotes (
    emote_id TEXT PRIMARY KEY,
    first_seen_user_id TEXT NOT NULL,
    first_seen_at REAL NOT NULL
);
"""


class Storage:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Storage.connect() must be awaited before use.")
        return self._conn

    # ------------------------------------------------------------------
    # Warnings (moderation strike counts)
    # ------------------------------------------------------------------

    async def get_warning_count(self, user_id: str) -> int:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT count FROM warnings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def increment_warning(self, user_id: str) -> int:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO warnings (user_id, count, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    count = count + 1,
                    updated_at = excluded.updated_at
                """,
                (user_id, time.time()),
            )
            await conn.commit()
        return await self.get_warning_count(user_id)

    async def record_warning(
        self,
        user_id: str,
        reason: str,
        source: str = "manual",
        actor_id: str | None = None,
    ) -> int:
        """Persist a warning and its audit trail as one operation."""
        conn = self._require_conn()
        async with self._lock:
            now = time.time()
            await conn.execute(
                """
                INSERT INTO warnings (user_id, count, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    count = count + 1, updated_at = excluded.updated_at
                """,
                (user_id, now),
            )
            async with conn.execute(
                "SELECT count FROM warnings WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
            count = int(row[0]) if row else 1
            await conn.execute(
                """
                INSERT INTO warning_events
                    (user_id, actor_id, reason, source, count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, actor_id, reason, source, count, now),
            )
            await conn.commit()
        return count

    async def reset_warnings(self, user_id: str) -> None:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute("DELETE FROM warnings WHERE user_id = ?", (user_id,))
            await conn.commit()

    async def record_moderation(
        self,
        moderator_id: str,
        target_user_id: str,
        action: str,
        duration: int | None = None,
    ) -> None:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO moderation_events
                    (moderator_id, target_user_id, action, duration, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (moderator_id, target_user_id, action, duration, time.time()),
            )
            await conn.commit()

    # ------------------------------------------------------------------
    # Minigame scores
    # ------------------------------------------------------------------

    async def get_score(self, user_id: str) -> int:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT points FROM scores WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def add_point(self, user_id: str, game: str = "unknown", points: int = 1) -> int:
        conn = self._require_conn()
        async with self._lock:
            now = time.time()
            await conn.execute(
                """
                INSERT INTO scores (user_id, points) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET points = points + excluded.points
                """,
                (user_id, points),
            )
            await conn.execute(
                """
                INSERT INTO score_events (user_id, points, game, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, points, game, now),
            )
            await conn.execute(
                """
                INSERT INTO user_stats (user_id, joins, xp, updated_at)
                VALUES (?, 0, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    xp = xp + excluded.xp, updated_at = excluded.updated_at
                """,
                (user_id, points * 10, now),
            )
            await conn.commit()
        return await self.get_score(user_id)

    async def top_scores(self, limit: int = 5) -> list[tuple[str, int]]:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT user_id, points FROM scores ORDER BY points DESC, user_id LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def top_scores_period(
        self, period: str = "all", limit: int = 5, now: float | None = None
    ) -> list[tuple[str, int]]:
        """Return score-event totals for all-time, today, or this week."""
        if period == "all":
            return await self.top_scores(limit)
        seconds = {"daily": 86_400, "weekly": 7 * 86_400}.get(period)
        if seconds is None:
            raise ValueError("period must be all, daily, or weekly")
        cutoff = (time.time() if now is None else now) - seconds
        conn = self._require_conn()
        async with conn.execute(
            """
            SELECT user_id, SUM(points) AS total
            FROM score_events
            WHERE created_at >= ?
            GROUP BY user_id
            ORDER BY total DESC, user_id
            LIMIT ?
            """,
            (cutoff, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [(row[0], int(row[1])) for row in rows]

    async def record_join(self, user_id: str, xp: int = 5) -> int:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO user_stats (user_id, joins, xp, updated_at)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    joins = joins + 1, xp = xp + excluded.xp,
                    updated_at = excluded.updated_at
                """,
                (user_id, xp, time.time()),
            )
            await conn.commit()
        return await self.get_join_count(user_id)

    async def add_xp(self, user_id: str, xp: int) -> int:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO user_stats (user_id, joins, xp, updated_at)
                VALUES (?, 0, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    xp = xp + excluded.xp, updated_at = excluded.updated_at
                """,
                (user_id, xp, time.time()),
            )
            await conn.commit()
        return await self.get_xp(user_id)

    async def get_join_count(self, user_id: str) -> int:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT joins FROM user_stats WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_xp(self, user_id: str) -> int:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT xp FROM user_stats WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def add_tip(self, user_id: str, gold: int) -> tuple[int, int]:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO tips (user_id, gold, tip_count, updated_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    gold = gold + excluded.gold,
                    tip_count = tip_count + 1,
                    updated_at = excluded.updated_at
                """,
                (user_id, gold, time.time()),
            )
            await conn.commit()
        return await self.get_tip_total(user_id), await self.get_total_tips()

    async def get_tip_total(self, user_id: str) -> int:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT gold FROM tips WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_total_tips(self) -> int:
        conn = self._require_conn()
        async with conn.execute("SELECT COALESCE(SUM(gold), 0) FROM tips") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def top_tippers(self, limit: int = 5) -> list[tuple[str, int]]:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT user_id, gold FROM tips ORDER BY gold DESC, user_id LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [(row[0], int(row[1])) for row in rows]

    async def set_favorite(self, user_id: str, slot: int, emote_number: int) -> None:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO favorites (user_id, slot, emote_number)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, slot) DO UPDATE SET
                    emote_number = excluded.emote_number
                """,
                (user_id, slot, emote_number),
            )
            await conn.commit()

    async def get_favorite(self, user_id: str, slot: int) -> int | None:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT emote_number FROM favorites WHERE user_id = ? AND slot = ?",
            (user_id, slot),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else None

    async def list_favorites(self, user_id: str) -> list[tuple[int, int]]:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT slot, emote_number FROM favorites WHERE user_id = ? ORDER BY slot",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [(int(row[0]), int(row[1])) for row in rows]

    async def delete_favorite(self, user_id: str, slot: int) -> None:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                "DELETE FROM favorites WHERE user_id = ? AND slot = ?",
                (user_id, slot),
            )
            await conn.commit()

    # ------------------------------------------------------------------
    # Settings (backing store for !config)
    # ------------------------------------------------------------------

    async def get_setting(self, key: str) -> str | None:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            await conn.commit()

    async def all_settings(self) -> dict[str, str]:
        conn = self._require_conn()
        async with conn.execute("SELECT key, value FROM settings") as cursor:
            rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    # ------------------------------------------------------------------
    # Username cache (so leaderboards can show names without a live
    # room query for users who may have already left)
    # ------------------------------------------------------------------

    async def remember_username(self, user_id: str, username: str) -> None:
        conn = self._require_conn()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO usernames (user_id, username) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
                """,
                (user_id, username),
            )
            await conn.commit()

    async def get_username(self, user_id: str) -> str | None:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT username FROM usernames WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    async def record_captured_emote(self, emote_id: str, user_id: str) -> bool:
        """Log a live emote_id not in the configured catalog. Returns True the
        first time this id is seen; False on later repeats (INSERT OR IGNORE)."""
        conn = self._require_conn()
        async with self._lock:
            cursor = await conn.execute(
                """
                INSERT OR IGNORE INTO captured_emotes
                    (emote_id, first_seen_user_id, first_seen_at)
                VALUES (?, ?, ?)
                """,
                (emote_id, user_id, time.time()),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def list_captured_emotes(self) -> list[tuple[str, str, float]]:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT emote_id, first_seen_user_id, first_seen_at "
            "FROM captured_emotes ORDER BY first_seen_at DESC"
        ) as cursor:
            return list(await cursor.fetchall())
