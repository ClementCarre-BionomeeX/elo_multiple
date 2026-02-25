import pytest

from elo_app.application.services import RatingService, RulesRegistry
from elo_app.domain.models import Outcome, Team
from elo_app.infrastructure.db import create_connection, init_db
from elo_app.infrastructure.repos import SQLiteRepository
from elo_app.rules.belote import BeloteRules
from elo_app.rules.tarot import TarotRules


@pytest.fixture()
def service(tmp_path):
    conn = create_connection(tmp_path / "stats.sqlite")
    init_db(conn)
    repo = SQLiteRepository(conn)
    registry = RulesRegistry()
    registry.register("belote", BeloteRules())
    registry.register("tarot", TarotRules())
    return RatingService(repo, registry)


def test_current_trueskill_stats_empty_when_no_rounds(service):
    players = [service.create_player("P1"), service.create_player("P2")]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", ruleset_id="belote")

    assert service.get_current_trueskill_stats(group_id, game_id) == {}


def test_current_trueskill_stats_after_round(service):
    players = [service.create_player("A"), service.create_player("B"), service.create_player("C")]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", ruleset_id="belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players[:2])

    service.add_round(
        match_id,
        teams=[Team("A", [players[0]]), Team("B", [players[1]])],
        outcome=Outcome(type="winloss", data={"winner": "A"}),
    )
    stats = service.get_current_trueskill_stats(group_id, game_id)

    # Only participants should appear; winner should have higher μ than loser.
    assert set(stats.keys()) == {players[0], players[1]}
    mu_winner, _, _ = stats[players[0]]
    mu_loser, _, _ = stats[players[1]]
    assert mu_winner > mu_loser


def test_current_player_stats_blends_defaults(service):
    players = [service.create_player(f"P{i}") for i in range(3)]
    group_id = service.create_group("G", players)
    game_id = service.create_game("Belote", ruleset_id="belote")
    match_id = service.create_match(group_id, game_id, participant_ids=players[:2])

    service.add_round(
        match_id,
        teams=[Team("A", [players[0]]), Team("B", [players[1]])],
        outcome=Outcome(type="winloss", data={"winner": "A"}),
    )

    rows = service.get_current_player_stats(group_id, game_id)
    ids = {row["player_id"] for row in rows}
    assert ids == set(players)  # includes non-participant

    lookup = {row["player_id"]: row for row in rows}
    # Default player should keep base Elo and TrueSkill values.
    assert lookup[players[2]]["elo"] == pytest.approx(service.default_rating)
    env = service._ts_env()
    assert lookup[players[2]]["ts_mu"] == pytest.approx(env["mu0"])
    assert lookup[players[2]]["ts_sigma"] == pytest.approx(env["sigma0"])
    # Winner should rank higher than loser by Elo.
    assert lookup[players[0]]["elo"] > lookup[players[1]]["elo"]
