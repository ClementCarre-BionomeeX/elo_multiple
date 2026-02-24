from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from elo_app.domain.models import Game, Group, Match, Outcome, Player, RatingEvent, Round, Team


class SQLiteRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # Creation helpers -----------------------------------------------------
    def add_player(self, player: Player) -> None:
        self.conn.execute("INSERT INTO players(id, name) VALUES (?, ?)", (player.id, player.name))
        self.conn.commit()

    def add_group(self, group: Group) -> None:
        self.conn.execute("INSERT INTO groups(id, name) VALUES (?, ?)", (group.id, group.name))
        self.conn.executemany(
            "INSERT INTO group_members(group_id, player_id) VALUES (?, ?)",
            [(group.id, pid) for pid in group.member_ids],
        )
        self.conn.commit()

    def add_game(self, game: Game) -> None:
        self.conn.execute(
            "INSERT INTO games(id, name, ruleset_id, config_json) VALUES (?, ?, ?, ?)",
            (game.id, game.name, game.ruleset_id, json.dumps(game.config)),
        )
        self.conn.commit()

    def add_match(self, match: Match) -> None:
        self.conn.execute(
            """
            INSERT INTO matches(id, group_id, game_id, participant_ids_json, started_at, ended_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                match.id,
                match.group_id,
                match.game_id,
                json.dumps(match.participant_ids),
                match.started_at.isoformat(),
                match.ended_at.isoformat() if match.ended_at else None,
            ),
        )
        self.conn.commit()

    def find_open_match(self, group_id: str, game_id: str) -> Match | None:
        row = self.conn.execute(
            """
            SELECT * FROM matches
            WHERE group_id=? AND game_id=? AND ended_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (group_id, game_id),
        ).fetchone()
        if row is None:
            return None
        return Match(
            id=row["id"],
            group_id=row["group_id"],
            game_id=row["game_id"],
            participant_ids=json.loads(row["participant_ids_json"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=None,
        )

    def set_match_end(self, match_id: str, ended_at: datetime) -> None:
        self.conn.execute(
            "UPDATE matches SET ended_at=? WHERE id=?",
            (ended_at.isoformat(), match_id),
        )
        self.conn.commit()

    def add_round(self, round_obj: Round) -> None:
        self.conn.execute(
            """
            INSERT INTO rounds(id, match_id, idx, teams_json, outcome_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                round_obj.id,
                round_obj.match_id,
                round_obj.index,
                json.dumps([asdict(team) for team in round_obj.teams]),
                json.dumps(asdict(round_obj.outcome)),
                round_obj.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def delete_round(self, round_id: str) -> None:
        self.conn.execute("DELETE FROM rounds WHERE id=?", (round_id,))
        self.conn.commit()

    def add_rating_event(self, event: RatingEvent) -> None:
        self.conn.execute(
            """
            INSERT INTO rating_events(id, group_id, game_id, round_id, deltas_json, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.group_id,
                event.game_id,
                event.round_id,
                json.dumps(event.deltas),
                json.dumps(event.meta),
                event.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def clear_rating_events(self, group_id: str, game_id: str) -> None:
        self.conn.execute(
            "DELETE FROM rating_events WHERE group_id=? AND game_id=?", (group_id, game_id)
        )
        self.conn.commit()

    def delete_rating_events_for_round(self, round_id: str) -> None:
        self.conn.execute("DELETE FROM rating_events WHERE round_id=?", (round_id,))
        self.conn.commit()

    def replace_rating_events(
        self, group_id: str, game_id: str, events: Iterable[RatingEvent]
    ) -> None:
        self.clear_rating_events(group_id, game_id)
        self.conn.executemany(
            """
            INSERT INTO rating_events(id, group_id, game_id, round_id, deltas_json, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    event.id,
                    event.group_id,
                    event.game_id,
                    event.round_id,
                    json.dumps(event.deltas),
                    json.dumps(event.meta),
                    event.created_at.isoformat(),
                )
                for event in events
            ],
        )
        self.conn.commit()

    # Ratings --------------------------------------------------------------
    def get_ratings_current(self, group_id: str, game_id: str) -> dict[str, float]:
        cur = self.conn.execute(
            "SELECT player_id, rating FROM ratings_current WHERE group_id=? AND game_id=?",
            (group_id, game_id),
        )
        return {row["player_id"]: float(row["rating"]) for row in cur.fetchall()}

    def clear_ratings_current(self, group_id: str, game_id: str) -> None:
        self.conn.execute(
            "DELETE FROM ratings_current WHERE group_id=? AND game_id=?", (group_id, game_id)
        )
        self.conn.commit()

    def replace_ratings_current(
        self, group_id: str, game_id: str, ratings: dict[str, float], games_played: dict[str, int]
    ) -> None:
        self.clear_ratings_current(group_id, game_id)
        self.conn.executemany(
            """
            INSERT INTO ratings_current(group_id, game_id, player_id, rating, games_played)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (group_id, game_id, pid, rating, games_played.get(pid, 0))
                for pid, rating in ratings.items()
            ],
        )
        self.conn.commit()

    def update_ratings_current(
        self, group_id: str, game_id: str, deltas: dict[str, float], default_rating: float
    ) -> dict[str, float]:
        current = self.get_ratings_current(group_id, game_id)
        updated = {}
        for player_id, delta in deltas.items():
            start_rating = current.get(player_id, default_rating)
            new_rating = start_rating + delta
            updated[player_id] = new_rating
            self.conn.execute(
                """
                INSERT INTO ratings_current(group_id, game_id, player_id, rating, games_played)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(group_id, game_id, player_id)
                DO UPDATE SET rating=excluded.rating, games_played=ratings_current.games_played + 1
                """,
                (group_id, game_id, player_id, new_rating),
            )
        self.conn.commit()
        return updated

    # Fetch helpers --------------------------------------------------------
    def get_match(self, match_id: str) -> Match | None:
        cur = self.conn.execute(
            "SELECT * FROM matches WHERE id = ?",
            (match_id,),
        ).fetchone()
        if cur is None:
            return None
        return Match(
            id=cur["id"],
            group_id=cur["group_id"],
            game_id=cur["game_id"],
            participant_ids=json.loads(cur["participant_ids_json"]),
            started_at=datetime.fromisoformat(cur["started_at"]),
            ended_at=datetime.fromisoformat(cur["ended_at"]) if cur["ended_at"] else None,
        )

    def get_game(self, game_id: str) -> Game | None:
        row = self.conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if row is None:
            return None
        return Game(
            id=row["id"],
            name=row["name"],
            ruleset_id=row["ruleset_id"],
            config=json.loads(row["config_json"]),
        )

    def count_rounds_for_match(self, match_id: str) -> int:
        row = self.conn.execute("SELECT COUNT(*) as count FROM rounds WHERE match_id=?", (match_id,)).fetchone()
        return int(row["count"])

    def get_round(self, round_id: str) -> Round | None:
        row = self.conn.execute(
            "SELECT * FROM rounds WHERE id=?", (round_id,)
        ).fetchone()
        if row is None:
            return None
        teams_data = json.loads(row["teams_json"])
        teams = [Team(**team) for team in teams_data]
        outcome_dict = json.loads(row["outcome_json"])
        outcome = Outcome(type=outcome_dict["type"], data=outcome_dict["data"])
        return Round(
            id=row["id"],
            match_id=row["match_id"],
            index=row["idx"],
            teams=teams,
            outcome=outcome,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_rounds(self, match_id: str) -> list[Round]:
        cur = self.conn.execute(
            "SELECT * FROM rounds WHERE match_id=? ORDER BY idx ASC",
            (match_id,),
        )
        rounds = []
        for row in cur.fetchall():
            teams_data = json.loads(row["teams_json"])
            teams = [Team(**team) for team in teams_data]
            outcome_dict = json.loads(row["outcome_json"])
            outcome = Outcome(type=outcome_dict["type"], data=outcome_dict["data"])
            rounds.append(
                Round(
                    id=row["id"],
                    match_id=row["match_id"],
                    index=row["idx"],
                    teams=teams,
                    outcome=outcome,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return rounds

    def list_matches(self, group_id: str, game_id: str | None = None) -> list[Match]:
        if game_id:
            cur = self.conn.execute(
                "SELECT * FROM matches WHERE group_id=? AND game_id=? ORDER BY started_at DESC",
                (group_id, game_id),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM matches WHERE group_id=? ORDER BY started_at DESC",
                (group_id,),
            )
        matches = []
        for row in cur.fetchall():
            matches.append(
                Match(
                    id=row["id"],
                    group_id=row["group_id"],
                    game_id=row["game_id"],
                    participant_ids=json.loads(row["participant_ids_json"]),
                    started_at=datetime.fromisoformat(row["started_at"]),
                    ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                )
            )
        return matches

    def list_rating_events_for_player(
        self, group_id: str, game_id: str, player_id: str
    ) -> list[RatingEvent]:
        cur = self.conn.execute(
            """
            SELECT * FROM rating_events
            WHERE group_id=? AND game_id=? AND json_extract(deltas_json, ?) IS NOT NULL
            ORDER BY created_at ASC
            """,
            (group_id, game_id, f'$.{player_id}'),
        )
        events = []
        for row in cur.fetchall():
            events.append(
                RatingEvent(
                    id=row["id"],
                    group_id=row["group_id"],
                    game_id=row["game_id"],
                    round_id=row["round_id"],
                    deltas=json.loads(row["deltas_json"]),
                    meta=json.loads(row["meta_json"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return events

    def list_group_member_ids(self, group_id: str) -> list[str]:
        cur = self.conn.execute(
            "SELECT player_id FROM group_members WHERE group_id=?",
            (group_id,),
        )
        return [row["player_id"] for row in cur.fetchall()]
