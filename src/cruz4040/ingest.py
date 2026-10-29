"""Fetch Cruz game logs, the Pirates schedule, and the prior-season baseline into SQLite."""

import argparse
import sqlite3

import statsapi

from cruz4040 import db

PLAYER_QUERY = "cruz, oneil"
TEAM_QUERY = "pittsburgh pirates"
PIRATES_ID = 134


def resolve_ids() -> tuple[int, int]:
    players = statsapi.lookup_player(PLAYER_QUERY)
    teams = statsapi.lookup_team(TEAM_QUERY)
    if len(players) != 1 or len(teams) != 1:
        raise RuntimeError(f"ambiguous lookup: {len(players)} players, {len(teams)} teams")
    team_id = teams[0]["id"]
    if team_id != PIRATES_ID:
        raise RuntimeError(f"expected Pirates team id {PIRATES_ID}, got {team_id}")
    return players[0]["id"], team_id


def store_schedule(conn: sqlite3.Connection, season: int, games: list[dict]) -> int:
    """Upsert schedule entries. Statuses change (scheduled -> final), so rows are replaced."""
    rows = [(g["game_id"], g["game_date"], season, g["game_type"], g["status"]) for g in games]
    conn.executemany(
        "INSERT OR REPLACE INTO schedule (game_pk, game_date, season, game_type, status)"
        " VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def store_game_log(conn: sqlite3.Connection, season: int, splits: list[dict]) -> int:
    """Insert regular-season game-log rows, skipping gamePks already cached."""
    cached = {r[0] for r in conn.execute("SELECT game_pk FROM batting WHERE season = ?", (season,))}
    rows = [
        (s["game"]["gamePk"], s["date"], season, s["stat"]["homeRuns"], s["stat"]["stolenBases"])
        for s in splits
        if s.get("gameType") == "R" and s["game"]["gamePk"] not in cached
    ]
    conn.executemany(
        "INSERT INTO batting (game_pk, game_date, season, hr, sb) VALUES (?, ?, ?, ?, ?)", rows
    )
    return len(rows)


def fetch_schedule(team_id: int, season: int) -> list[dict]:
    return statsapi.schedule(team=team_id, start_date=f"01/01/{season}", end_date=f"12/31/{season}")


def fetch_game_log(player_id: int, season: int) -> list[dict]:
    hydrate = f"stats(group=[hitting],type=[gameLog],season={season})"
    resp = statsapi.get("people", {"personIds": player_id, "hydrate": hydrate})
    stats = resp["people"][0].get("stats", [])
    return stats[0]["splits"] if stats else []


def fetch_baseline(player_id: int, season: int) -> db.Baseline:
    data = statsapi.player_stat_data(
        player_id, group="[hitting]", type="season", sportId=1, season=season
    )
    s = data["stats"][0]["stats"]
    return db.Baseline(season, s["homeRuns"], s["stolenBases"], s["gamesPlayed"])


def ingest(conn: sqlite3.Connection, season: int) -> None:
    player_id, team_id = resolve_ids()

    n_sched = store_schedule(conn, season, fetch_schedule(team_id, season))
    n_new = store_game_log(conn, season, fetch_game_log(player_id, season))

    prior = season - 1
    if db.get_baseline(conn, prior) is None:
        b = fetch_baseline(player_id, prior)
        conn.execute(
            "INSERT INTO baseline (season, hr, sb, games) VALUES (?, ?, ?, ?)",
            (b.season, b.hr, b.sb, b.games),
        )
    conn.commit()

    done = db.completed_team_games(conn, season)
    print(f"{season}: {n_sched} schedule rows, {n_new} new Cruz games, {done} team games completed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--db", default=str(db.DB_PATH))
    args = parser.parse_args()

    conn = db.connect(args.db)
    try:
        ingest(conn, args.season)
    finally:
        conn.close()
