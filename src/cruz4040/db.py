"""SQLite schema and the per-date season queries the model reads."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path("data/cruz.sqlite")
SEASON_GAMES = 162

# Regular-season statuses that mean the game is official. "Completed Early" is a
# shortened (e.g. rain-ended) official game; it counts like "Final".
COMPLETED_STATUSES = ("Final", "Game Over", "Completed Early")

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule (
    game_pk   INTEGER NOT NULL,
    game_date TEXT    NOT NULL,
    season    INTEGER NOT NULL,
    game_type TEXT    NOT NULL,
    status    TEXT    NOT NULL,
    -- A postponed game and its makeup share a gamePk but not a date.
    PRIMARY KEY (game_pk, game_date)
);

CREATE TABLE IF NOT EXISTS batting (
    game_pk   INTEGER PRIMARY KEY,
    game_date TEXT    NOT NULL,
    season    INTEGER NOT NULL,
    hr        INTEGER NOT NULL,
    sb        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS baseline (
    season INTEGER PRIMARY KEY,
    hr     INTEGER NOT NULL,
    sb     INTEGER NOT NULL,
    games  INTEGER NOT NULL
);
"""

_COMPLETED_GAMES = f"""
SELECT game_pk, game_date FROM schedule
WHERE season = :season
  AND game_type = 'R'
  AND status IN ({", ".join(f"'{s}'" for s in COMPLETED_STATUSES)})
"""

_PROGRESS_SQL = f"""
WITH completed AS ({_COMPLETED_GAMES}),
team AS (
    SELECT game_date, COUNT(*) AS games FROM completed GROUP BY game_date
),
bat AS (
    -- Join on gamePk so only Cruz games that are completed team games count.
    SELECT c.game_date, SUM(b.hr) AS hr, SUM(b.sb) AS sb, COUNT(*) AS games
    FROM batting b JOIN completed c USING (game_pk)
    WHERE b.season = :season
    GROUP BY c.game_date
)
SELECT
    t.game_date,
    SUM(COALESCE(bat.hr, 0))    OVER w AS hr,
    SUM(COALESCE(bat.sb, 0))    OVER w AS sb,
    SUM(COALESCE(bat.games, 0)) OVER w AS games_played,
    SUM(t.games)                OVER w AS team_completed
FROM team t LEFT JOIN bat USING (game_date)
WINDOW w AS (ORDER BY t.game_date ROWS UNBOUNDED PRECEDING)
ORDER BY t.game_date
"""


@dataclass(frozen=True)
class DateState:
    game_date: str
    hr: int
    sb: int
    games_played: int
    team_completed: int
    team_remaining: int


@dataclass(frozen=True)
class Baseline:
    season: int
    hr: int
    sb: int
    games: int


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def season_progress(conn: sqlite3.Connection, season: int) -> list[DateState]:
    """One row per date with a completed regular-season team game, cumulative through that date."""
    rows = conn.execute(_PROGRESS_SQL, {"season": season}).fetchall()
    return [
        DateState(date, hr, sb, gp, done, max(SEASON_GAMES - done, 0))
        for date, hr, sb, gp, done in rows
    ]


def completed_team_games(conn: sqlite3.Connection, season: int) -> int:
    sql = f"SELECT COUNT(*) FROM ({_COMPLETED_GAMES})"
    return conn.execute(sql, {"season": season}).fetchone()[0]


def get_baseline(conn: sqlite3.Connection, season: int) -> Baseline | None:
    row = conn.execute(
        "SELECT season, hr, sb, games FROM baseline WHERE season = ?", (season,)
    ).fetchone()
    return Baseline(*row) if row else None
