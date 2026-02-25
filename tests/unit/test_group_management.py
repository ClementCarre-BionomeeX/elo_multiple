import pytest

from elo_app.application.services import RatingService, RulesRegistry
from elo_app.infrastructure.db import create_connection, init_db
from elo_app.infrastructure.repos import SQLiteRepository
from elo_app.rules.belote import BeloteRules
from elo_app.rules.tarot import TarotRules
from elo_app.domain.models import Outcome, Team


@pytest.fixture()
def service(tmp_path):
    conn = create_connection(tmp_path / "groups.sqlite")
    init_db(conn)
    repo = SQLiteRepository(conn)
    registry = RulesRegistry()
    registry.register("belote", BeloteRules())
    registry.register("tarot", TarotRules())
    return RatingService(repo, registry)


def test_rename_group_and_validation(service):
    players = [service.create_player("P1")]
    group_id = service.create_group("Ancien nom", players)

    service.rename_group(group_id, "Nouveau nom")
    row = service.repo.conn.execute("SELECT name FROM groups WHERE id=?", (group_id,)).fetchone()
    assert row["name"] == "Nouveau nom"

    with pytest.raises(ValueError):
        service.rename_group(group_id, "  ")


def test_add_players_to_group_deduplicates(service):
    players = [service.create_player(f"P{i}") for i in range(3)]
    group_id = service.create_group("Groupe", [players[0]])

    # Add two new players.
    service.add_players_to_group(group_id, [players[1], players[2]])
    members = set(service.repo.list_group_member_ids(group_id))
    assert members == {players[0], players[1], players[2]}

    # Adding an existing player should be ignored and keep the same membership size.
    service.add_players_to_group(group_id, [players[2]])
    members_after = set(service.repo.list_group_member_ids(group_id))
    assert members_after == members

    with pytest.raises(ValueError):
        service.add_players_to_group(group_id, [])


def test_delete_group_blocks_open_sessions_and_cleans_data(service):
    players = [service.create_player(f"P{i}") for i in range(2)]
    group_id = service.create_group("Groupe", players)
    game_id = service.create_game("Belote", ruleset_id="belote", config={"K": 10})
    match_id = service.create_match(group_id, game_id, participant_ids=players)

    # Open match should prevent deletion.
    with pytest.raises(ValueError):
        service.delete_group(group_id)

    # Add a round to generate ratings and events, then close and delete.
    outcome = Outcome(type="winloss", data={"winner": "A"})
    service.add_round(
        match_id,
        teams=[Team("A", [players[0]]), Team("B", [players[1]])],
        outcome=outcome,
    )
    service.end_match(match_id)
    service.delete_group(group_id)

    # Verify cascading cleanup.
    cur = service.repo.conn
    assert cur.execute("SELECT COUNT(*) as c FROM groups").fetchone()["c"] == 0
    assert cur.execute("SELECT COUNT(*) as c FROM group_members").fetchone()["c"] == 0
    assert cur.execute("SELECT COUNT(*) as c FROM matches").fetchone()["c"] == 0
    assert cur.execute("SELECT COUNT(*) as c FROM rounds").fetchone()["c"] == 0
    assert cur.execute("SELECT COUNT(*) as c FROM rating_events").fetchone()["c"] == 0
    assert cur.execute("SELECT COUNT(*) as c FROM ratings_current").fetchone()["c"] == 0
