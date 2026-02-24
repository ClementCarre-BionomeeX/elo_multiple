import math
from datetime import datetime, timezone

import pytest

from elo_app.application.services import RatingService, RulesRegistry
from elo_app.domain.models import Match, Outcome, Round, Team
from elo_app.infrastructure.db import create_connection, init_db
from elo_app.infrastructure.repos import SQLiteRepository
from elo_app.rules.belote import BeloteRules
from elo_app.rules.tarot import TarotRules


@pytest.fixture()
def service(tmp_path):
    conn = create_connection(tmp_path / "elo.sqlite")
    init_db(conn)
    repo = SQLiteRepository(conn)
    registry = RulesRegistry()
    registry.register("belote", BeloteRules())
    registry.register("tarot", TarotRules())
    return RatingService(repo, registry)


def test_full_flow_belote_round_updates_ratings(service):
    players = [service.create_player(f"Player {i}") for i in range(4)]
    group_id = service.create_group("Groupe", players)
    game_id = service.create_game("Belote", ruleset_id="belote", config={"K": 20})
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    outcome = Outcome(type="winloss", data={"winner": "A", "margin": 80})
    event = service.add_round(
        match_id,
        teams=[Team("A", players[:2]), Team("B", players[2:])],
        outcome=outcome,
    )

    ratings = dict(service.get_ratings(group_id, game_id))
    assert len(ratings) == 4
    assert ratings[players[0]] > 1500
    assert ratings[players[2]] < 1500
    assert sum(event.deltas.values()) == pytest.approx(0.0, abs=1e-9)

    history = service.get_rating_history(group_id, game_id, players[0])
    assert len(history) == 1
    assert history[0][1] == ratings[players[0]]

    matches = service.list_matches(group_id, game_id)
    assert matches and matches[0].id == match_id

    details = service.get_match_details(match_id)
    assert len(details["rounds"]) == 1

    # Recalcul should yield identical ratings and regenerate events.
    before = dict(ratings)
    recalculated = service.recalc_game(group_id, game_id)
    assert recalculated == before
    cur = service.repo.conn.execute(
        "SELECT COUNT(*) as c FROM rating_events WHERE group_id=? AND game_id=?",
        (group_id, game_id),
    )
    assert cur.fetchone()["c"] == 1


def test_full_flow_tarot_round_updates_ratings(service):
    players = [service.create_player(f"Joueur {i}") for i in range(5)]
    group_id = service.create_group("Taroteurs", players)
    game_id = service.create_game("Tarot", ruleset_id="tarot", config={"K": 16})
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    outcome = Outcome(type="contract", data={"success": False, "margin": 200})
    event = service.add_round(
        match_id,
        teams=[Team("ATT", players[:2]), Team("DEF", players[2:])],
        outcome=outcome,
    )

    ratings = dict(service.get_ratings(group_id, game_id))
    assert len(ratings) == 5
    assert all(math.isfinite(r) for r in ratings.values())
    assert sum(event.deltas.values()) == pytest.approx(0.0, abs=1e-9)

    history_att = service.get_rating_history(group_id, game_id, players[0])
    assert len(history_att) == 1
    # Failure should reduce ATT rating.
    assert history_att[-1][1] < 1500


def test_rules_registry_requires_registration():
    registry = RulesRegistry()
    with pytest.raises(KeyError):
        registry.get("unknown")


def test_missing_entities_return_none_or_raise(tmp_path):
    conn = create_connection(tmp_path / "missing.sqlite")
    init_db(conn)
    repo = SQLiteRepository(conn)

    assert repo.get_match("missing") is None
    assert repo.get_game("missing") is None

    registry = RulesRegistry()
    service = RatingService(repo, registry)
    with pytest.raises(ValueError):
        service.get_match_details("missing")


def test_add_round_missing_entities_raise(service):
    players = [service.create_player("Solo")]
    group_id = service.create_group("G", players)
    # Add a match with missing game to trigger game lookup failure.
    bogus_match_id = "bogus-match"
    service.repo.add_match(
        Match(
            id=bogus_match_id,
            group_id=group_id,
            game_id="missing-game",
            participant_ids=players,
            started_at=datetime.now(timezone.utc),
            ended_at=None,
        )
    )
    with pytest.raises(ValueError):
        service.add_round(
            "missing-match",
            teams=[Team("A", players), Team("B", [])],
            outcome=Outcome(type="winloss", data={"winner": "A"}),
        )

    with pytest.raises(ValueError):
        service.add_round(
            bogus_match_id,
            teams=[Team("A", players), Team("B", [])],
            outcome=Outcome(type="winloss", data={"winner": "A"}),
        )

    with pytest.raises(ValueError):
        service.recalc_game(group_id, "missing-game")

    with pytest.raises(ValueError):
        service.delete_round("missing-round")

    match = service.create_match(group_id, service.create_game("Belote", "belote"), players)
    service.end_match(match)
    with pytest.raises(ValueError):
        service.add_round(
            match,
            teams=[Team("A", players), Team("B", [])],
            outcome=Outcome(type="winloss", data={"winner": "A"}),
        )


def test_list_matches_without_game_filters(service):
    players = [service.create_player(f"P{i}") for i in range(2)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", ruleset_id="belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    all_matches = service.list_matches(group_id)
    assert any(m.id == match_id for m in all_matches)


def test_open_session_enforcement_and_history(service):
    players = [service.create_player(f"P{i}") for i in range(4)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", ruleset_id="belote", config={"K": 20})
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    # Second open match should be blocked.
    with pytest.raises(ValueError):
        service.create_match(group_id, game_id, participant_ids=players)

    outcome = Outcome(type="winloss", data={"winner": "A"})
    service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=outcome)
    # Close and verify add_round blocked.
    service.end_match(match_id)
    with pytest.raises(ValueError):
        service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=outcome)

    # Now create a new session after closing.
    match2 = service.create_match(group_id, game_id, participant_ids=players)
    service.add_round(match2, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=outcome)

    hist = service.get_player_round_history(group_id, game_id, players[0])
    assert len(hist) == 2
    # Ensure match_ids are present and ordered
    assert hist[0][2] == match_id
    assert hist[1][2] == match2


def test_end_match_behaviour_and_helpers(service):
    with pytest.raises(ValueError):
        service.end_match("missing")

    players = [service.create_player("X"), service.create_player("Y")]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", ruleset_id="belote")
    assert service.get_open_match(group_id, game_id) is None

    match_id = service.create_match(group_id, game_id, participant_ids=players)
    assert service.get_open_match(group_id, game_id).id == match_id
    service.end_match(match_id)
    # Second call should be a no-op
    service.end_match(match_id)
    assert service.get_open_match(group_id, game_id) is None

    with pytest.raises(ValueError):
        service.get_player_round_history(group_id, "missing-game", players[0])


def test_trueskill_and_surprise_series(service):
    players = [service.create_player(f"P{i}") for i in range(4)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", ruleset_id="belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players)
    outcome1 = Outcome(type="winloss", data={"winner": "A"})
    outcome2 = Outcome(type="winloss", data={"winner": "B"})
    service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=outcome1)
    service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=outcome2)

    ts_series = service.get_trueskill_progression(group_id, game_id)
    assert players[0] in ts_series
    assert len(ts_series[players[0]]) == 2
    assert ts_series[players[0]][0]["idx"] == 0
    assert ts_series[players[0]][1]["idx"] == 1

    surprise = service.get_surprise_series(group_id, game_id)
    assert players[0] in surprise
    assert len(surprise[players[0]]) == 2
    # cumulative should evolve
    assert surprise[players[0]][0]["idx"] == 0
    assert surprise[players[0]][1]["idx"] == 1
    assert surprise[players[0]][1]["cum_p"] != surprise[players[0]][0]["cum_p"]

    stats = service.get_current_player_stats(group_id, game_id)
    assert len(stats) == 4
    # Elo sorted desc
    assert stats[0]["elo"] >= stats[-1]["elo"]


def test_delete_round_recalc_and_cleanup(service):
    players = [service.create_player(f"R{i}") for i in range(4)]
    group_id = service.create_group("Group", players)
    game_id = service.create_game("Belote", ruleset_id="belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    outcome = Outcome(type="winloss", data={"winner": "A"})
    event = service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=outcome)

    round_id = service.get_match_details(match_id)["rounds"][0].id
    assert service.repo.get_round(round_id) is not None

    ratings_after_delete = service.delete_round(round_id)
    assert ratings_after_delete == {}
    assert service.repo.get_round(round_id) is None
    assert service.repo.get_ratings_current(group_id, game_id) == {}
    count_events = service.repo.conn.execute("SELECT COUNT(*) as c FROM rating_events").fetchone()["c"]
    assert count_events == 0


def test_delete_round_validates_match(service):
    # Insert a round referencing a non-existent match to trigger validation.
    rogue_round = Round(
        id="rogue",
        match_id="missing-match",
        index=0,
        teams=[Team("A", ["x"]), Team("B", ["y"])],
        outcome=Outcome(type="winloss", data={"winner": "A"}),
        created_at=datetime.now(timezone.utc),
    )
    service.repo.add_round(rogue_round)
    with pytest.raises(ValueError):
        service.delete_round("rogue")
