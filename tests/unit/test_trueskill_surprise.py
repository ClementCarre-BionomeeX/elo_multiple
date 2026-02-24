import math
from datetime import datetime, timezone

from elo_app.application.services import RatingService, RulesRegistry
from elo_app.domain.models import Outcome, Round, Team
from elo_app.infrastructure.db import create_connection, init_db
from elo_app.infrastructure.repos import SQLiteRepository
from elo_app.rules.belote import BeloteRules
from elo_app.rules.tarot import TarotRules


def make_service(tmp_path):
    conn = create_connection(tmp_path / "ts.sqlite")
    init_db(conn)
    repo = SQLiteRepository(conn)
    registry = RulesRegistry()
    registry.register("belote", BeloteRules())
    registry.register("tarot", TarotRules())
    return RatingService(repo, registry)


def test_trueskill_two_rounds_updates_all_players(tmp_path):
    service = make_service(tmp_path)
    players = [service.create_player(f"P{i}") for i in range(4)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", "belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=Outcome("winloss", {"winner": "A"}))
    service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=Outcome("winloss", {"winner": "B"}))

    ts = service.get_trueskill_progression(group_id, game_id)
    assert set(ts.keys()) == set(players)
    for pid in players:
        assert len(ts[pid]) == 2
        assert ts[pid][0]["idx"] == 0
        assert ts[pid][1]["idx"] == 1
        assert math.isfinite(ts[pid][1]["mu"])
        assert math.isfinite(ts[pid][1]["sigma"])


def test_surprise_series_cumulative(tmp_path):
    service = make_service(tmp_path)
    players = [service.create_player(f"S{i}") for i in range(4)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", "belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    # Two wins for team A then a draw.
    service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=Outcome("winloss", {"winner": "A"}))
    service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=Outcome("winloss", {"winner": "A"}))
    service.add_round(match_id, teams=[Team("A", players[:2]), Team("B", players[2:])], outcome=Outcome("winloss", {"winner": "draw"}))

    surprise = service.get_surprise_series(group_id, game_id)
    a_player = players[0]
    b_player = players[2]
    assert len(surprise[a_player]) == 3
    assert surprise[a_player][-1]["cum_p"] > 0
    assert surprise[b_player][-1]["cum_p"] < 0
    # idx should be sequential
    assert surprise[a_player][0]["idx"] == 0
    assert surprise[a_player][1]["idx"] == 1
    assert surprise[a_player][2]["idx"] == 2


def test_rounds_for_dashboard_ordering(tmp_path):
    service = make_service(tmp_path)
    players = [service.create_player(f"R{i}") for i in range(2)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", "belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players)
    service.add_round(match_id, teams=[Team("A", players), Team("B", [])], outcome=Outcome("winloss", {"winner": "A"}))
    rounds = service.get_rounds_for_dashboard(group_id, game_id)
    assert len(rounds) == 1
    rd, match = rounds[0]
    assert rd.match_id == match_id
    assert match.id == match_id


def test_sides_and_scores_contract_and_draw(tmp_path):
    service = make_service(tmp_path)
    players = [service.create_player(f"T{i}") for i in range(4)]
    group_id = service.create_group("G", players)

    # Tarot contract failure
    tarot_game = service.create_game("Tarot", "tarot")
    tarot_match = service.create_match(group_id, tarot_game, participant_ids=players)
    service.add_round(
        tarot_match,
        teams=[Team("ATT", players[:2]), Team("DEF", players[2:])],
        outcome=Outcome("contract", {"success": False}),
    )

    # Belote draw
    belote_game = service.create_game("Belote", "belote")
    belote_match = service.create_match(group_id, belote_game, participant_ids=players)
    service.add_round(
        belote_match,
        teams=[Team("A", players[:2]), Team("B", players[2:])],
        outcome=Outcome("winloss", {"winner": "draw"}),
    )

    ts_tarot = service.get_trueskill_progression(group_id, tarot_game)
    assert ts_tarot[players[0]][0]["idx"] == 0
    surprise_tarot = service.get_surprise_series(group_id, tarot_game)
    assert surprise_tarot[players[0]][0]["idx"] == 0

    ts_belote = service.get_trueskill_progression(group_id, belote_game)
    assert ts_belote[players[0]][0]["idx"] == 0


def test_unknown_outcome_branches(tmp_path):
    service = make_service(tmp_path)
    players = [service.create_player(f"U{i}") for i in range(2)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", "belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    rd = Round(
        id="r-unknown",
        match_id=match_id,
        index=0,
        teams=[Team("A", players), Team("B", [])],
        outcome=Outcome("other", {"foo": "bar"}),
        created_at=datetime.now(timezone.utc),
    )
    service.repo.add_round(rd)

    ts = service.get_trueskill_progression(group_id, game_id)
    assert ts[players[0]][0]["idx"] == 0

    surprise = service.get_surprise_series(group_id, game_id)
    assert surprise[players[0]][0]["idx"] == 0


def test_get_current_trueskill_stats_defaults(tmp_path):
    service = make_service(tmp_path)
    players = [service.create_player("Solo")]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", "belote")
    stats = service.get_current_trueskill_stats(group_id, game_id)
    mu0 = service._ts_env()["mu0"]
    sigma0 = service._ts_env()["sigma0"]
    cons0 = mu0 - 3 * sigma0
    assert stats == {}
    # After one round we get stats
    match_id = service.create_match(group_id, game_id, participant_ids=players)
    service.add_round(match_id, teams=[Team("A", players), Team("B", [])], outcome=Outcome("winloss", {"winner": "A"}))
    stats = service.get_current_trueskill_stats(group_id, game_id)
    assert players[0] in stats
    mu, sigma, cons = stats[players[0]]
    assert mu != mu0 or sigma != sigma0
    assert cons == mu - 3 * sigma
    # When no stats exist for other players, they are absent from the dict
    assert len(stats) == 1
    # Coverage for empty progression: another game with no rounds returns empty stats.
    empty_stats = service.get_current_trueskill_stats(group_id, service.create_game("Other", "belote"))
    assert empty_stats == {}
    # Direct call on empty progression of original game returns empty too if reset
    assert service.get_current_trueskill_stats(group_id, game_id) != {}


def test_get_current_player_stats_includes_defaults(tmp_path):
    service = make_service(tmp_path)
    players = [service.create_player(f"S{i}") for i in range(2)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", "belote")
    stats = service.get_current_player_stats(group_id, game_id)
    assert len(stats) == 2
    assert all("ts_mu" in row for row in stats)
    # After a round, stats should update
    match_id = service.create_match(group_id, game_id, participant_ids=players)
    service.add_round(
        match_id,
        teams=[Team("A", players), Team("B", [])],
        outcome=Outcome("winloss", {"winner": "A"}),
    )
    stats_after = service.get_current_player_stats(group_id, game_id)
    assert stats_after[0]["elo"] != stats[0]["elo"]


def test_get_current_trueskill_stats_skips_empty_progression(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    # Force progression with an empty events list to hit the continue branch.
    monkeypatch.setattr(
        service,
        "get_trueskill_progression",
        lambda group_id, game_id: {"ghost": []},
    )
    stats = service.get_current_trueskill_stats("g", "h")
    assert stats == {}
