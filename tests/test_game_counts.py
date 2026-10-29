import pytest

from cruz4040 import db
from cruz4040.ingest import store_game_log, store_schedule

SEASON = 2026


def game(pk, date, game_type="R", status="Final"):
    return {"game_id": pk, "game_date": date, "game_type": game_type, "status": status}


def log(pk, date, hr=0, sb=0, game_type="R"):
    return {
        "game": {"gamePk": pk},
        "date": date,
        "gameType": game_type,
        "stat": {"homeRuns": hr, "stolenBases": sb},
    }


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


def test_only_completed_regular_season_games_count(conn):
    store_schedule(
        conn,
        SEASON,
        [
            game(1, "2026-03-01", game_type="S"),
            game(2, "2026-03-02", game_type="E"),
            game(3, "2026-03-26"),
            game(4, "2026-03-27", status="Suspended"),
            game(5, "2026-03-28", status="Scheduled"),
            game(6, "2026-03-29", status="Completed Early"),
        ],
    )
    assert db.completed_team_games(conn, SEASON) == 2
    assert [s.game_date for s in db.season_progress(conn, SEASON)] == ["2026-03-26", "2026-03-29"]


def test_postponed_entry_sharing_makeup_gamepk_counts_once(conn):
    store_schedule(
        conn,
        SEASON,
        [
            game(10, "2026-07-10", status="Postponed"),
            game(10, "2026-07-11"),
        ],
    )
    assert db.completed_team_games(conn, SEASON) == 1
    [state] = db.season_progress(conn, SEASON)
    assert state.game_date == "2026-07-11"


def test_doubleheader_counts_as_two(conn):
    store_schedule(conn, SEASON, [game(20, "2026-07-18"), game(21, "2026-07-18")])
    store_game_log(conn, SEASON, [log(20, "2026-07-18", hr=1), log(21, "2026-07-18", sb=2)])

    [state] = db.season_progress(conn, SEASON)
    assert state.team_completed == 2
    assert state.team_remaining == db.SEASON_GAMES - 2
    assert (state.hr, state.sb, state.games_played) == (1, 2, 2)


def test_progress_is_cumulative_and_counts_missed_games(conn):
    store_schedule(
        conn,
        SEASON,
        [
            game(30, "2026-04-01"),
            game(31, "2026-04-02"),
            game(32, "2026-04-03"),
        ],
    )
    # Cruz sits out 2026-04-02.
    store_game_log(conn, SEASON, [log(30, "2026-04-01", hr=1), log(32, "2026-04-03", hr=1, sb=1)])

    states = db.season_progress(conn, SEASON)
    assert [(s.hr, s.sb, s.games_played, s.team_completed) for s in states] == [
        (1, 0, 1, 1),
        (1, 0, 1, 2),
        (2, 1, 2, 3),
    ]


def test_game_log_ignores_non_regular_and_unfinished_games(conn):
    store_schedule(
        conn, SEASON, [game(40, "2026-04-05"), game(41, "2026-04-06", status="Suspended")]
    )
    store_game_log(
        conn,
        SEASON,
        [
            log(39, "2026-03-01", hr=3, game_type="S"),
            log(40, "2026-04-05", hr=1),
            log(41, "2026-04-06", hr=1),
        ],
    )
    states = db.season_progress(conn, SEASON)
    assert states[-1].hr == 1


def test_game_log_ingest_is_incremental(conn):
    assert store_game_log(conn, SEASON, [log(50, "2026-04-10", hr=1)]) == 1
    assert store_game_log(conn, SEASON, [log(50, "2026-04-10", hr=1), log(51, "2026-04-11")]) == 1
    assert conn.execute("SELECT COUNT(*) FROM batting").fetchone()[0] == 2
