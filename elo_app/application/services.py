from __future__ import annotations

import uuid
from datetime import datetime, timezone
from math import erf, exp, sqrt

from elo_app.domain.elo_engine import DEFAULT_RATING, apply_matchup, expected, team_rating
from elo_app.domain.matchup import Matchup
from elo_app.domain.models import Game, Group, Match, Outcome, Player, RatingEvent, Round, Team
from elo_app.domain.policies import DeltaDistributionPolicy, TeamRatingPolicy
from elo_app.infrastructure.repos import SQLiteRepository
from elo_app.rules.base import GameRules


class RulesRegistry:
    def __init__(self):
        self._rules: dict[str, GameRules] = {}

    def register(self, key: str, rules: GameRules) -> None:
        self._rules[key] = rules

    def get(self, key: str) -> GameRules:
        if key not in self._rules:
            raise KeyError(f"No rules registered for {key}")
        return self._rules[key]


class RatingService:
    def __init__(
        self,
        repo: SQLiteRepository,
        rules_registry: RulesRegistry,
        default_rating: float = DEFAULT_RATING,
        team_policy: TeamRatingPolicy = TeamRatingPolicy.STRENGTH_SUM,
        distribution_policy: DeltaDistributionPolicy = DeltaDistributionPolicy.EQUAL,
    ):
        self.repo = repo
        self.rules_registry = rules_registry
        self.default_rating = default_rating
        self.team_policy = team_policy
        self.distribution_policy = distribution_policy

    # Creation helpers --------------------------------------------------
    def create_player(self, name: str) -> str:
        player_id = str(uuid.uuid4())
        self.repo.add_player(Player(id=player_id, name=name))
        return player_id

    def create_group(self, name: str, member_ids: list[str]) -> str:
        group_id = str(uuid.uuid4())
        self.repo.add_group(Group(id=group_id, name=name, member_ids=member_ids))
        return group_id

    def create_game(self, name: str, ruleset_id: str, config: dict | None = None) -> str:
        game_id = str(uuid.uuid4())
        self.repo.add_game(Game(id=game_id, name=name, ruleset_id=ruleset_id, config=config or {}))
        return game_id

    def create_match(self, group_id: str, game_id: str, participant_ids: list[str]) -> str:
        existing_open = self.repo.find_open_match(group_id, game_id)
        if existing_open:
            raise ValueError("Une session est déjà ouverte pour ce groupe/jeu.")
        match_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        self.repo.add_match(
            Match(
                id=match_id,
                group_id=group_id,
                game_id=game_id,
                participant_ids=participant_ids,
                started_at=now,
                ended_at=None,
            )
        )
        return match_id

    def end_match(self, match_id: str) -> None:
        match = self.repo.get_match(match_id)
        if match is None:
            raise ValueError(f"Match not found: {match_id}")
        if match.ended_at is not None:
            return
        self.repo.set_match_end(match_id, datetime.now(timezone.utc))

    def delete_group(self, group_id: str) -> None:
        open_matches = [m for m in self.repo.list_matches(group_id) if m.ended_at is None]
        if open_matches:
            raise ValueError("Impossible de supprimer : une session est encore ouverte pour ce groupe.")
        self.repo.delete_group(group_id)

    def rename_group(self, group_id: str, new_name: str) -> None:
        if not new_name.strip():
            raise ValueError("Le nom ne peut pas être vide.")
        self.repo.rename_group(group_id, new_name.strip())

    # Rating computation -----------------------------------------------
    def add_round(self, match_id: str, teams: list[Team], outcome: Outcome) -> RatingEvent:
        match = self.repo.get_match(match_id)
        if match is None:
            raise ValueError(f"Match not found: {match_id}")
        if match.ended_at is not None:
            raise ValueError("Cette session est close, créez-en une nouvelle pour ajouter des rounds.")

        game = self.repo.get_game(match.game_id)
        if game is None:
            raise ValueError(f"Game not found for match {match.game_id}")

        round_index = self.repo.count_rounds_for_match(match_id)
        round_obj = Round(
            id=str(uuid.uuid4()),
            match_id=match_id,
            index=round_index,
            teams=teams,
            outcome=outcome,
            created_at=datetime.now(timezone.utc),
        )

        rules = self.rules_registry.get(game.ruleset_id)
        matchups = rules.to_matchups(round_obj)
        ratings = self.repo.get_ratings_current(match.group_id, match.game_id)

        K_base = game.config.get("K", 20) if isinstance(game.config, dict) else 20
        aggregated_deltas: dict[str, float] = {}
        for matchup in matchups:
            deltas = apply_matchup(
                ratings,
                matchup,
                K=K_base,
                team_policy=self.team_policy,
                distribution_policy=self.distribution_policy,
                default_rating=self.default_rating,
            )
            for pid, delta in deltas.items():
                aggregated_deltas[pid] = aggregated_deltas.get(pid, 0.0) + delta

        updated = self.repo.update_ratings_current(
            match.group_id, match.game_id, aggregated_deltas, self.default_rating
        )

        event = RatingEvent(
            id=str(uuid.uuid4()),
            group_id=match.group_id,
            game_id=match.game_id,
            round_id=round_obj.id,
            deltas=aggregated_deltas,
            meta={"k_base": K_base, "matchups": len(matchups)},
            created_at=datetime.now(timezone.utc),
        )

        self.repo.add_round(round_obj)
        self.repo.add_rating_event(event)
        return event

    # Queries -----------------------------------------------------------
    def get_ratings(self, group_id: str, game_id: str) -> list[tuple[str, float]]:
        ratings = self.repo.get_ratings_current(group_id, game_id)
        return sorted(ratings.items(), key=lambda item: item[1], reverse=True)

    def get_rating_history(self, group_id: str, game_id: str, player_id: str) -> list[tuple[datetime, float]]:
        events = self.repo.list_rating_events_for_player(group_id, game_id, player_id)
        history: list[tuple[datetime, float]] = []
        current = self.default_rating
        for event in events:
            delta = event.deltas.get(player_id, 0.0)
            current += delta
            history.append((event.created_at, current))
        return history

    def get_rounds_for_dashboard(self, group_id: str, game_id: str) -> list[tuple[Round, Match]]:
        matches = sorted(self.repo.list_matches(group_id, game_id), key=lambda m: m.started_at)
        rounds: list[tuple[Round, Match]] = []
        for match in matches:
            for rd in self.repo.list_rounds(match.id):
                rounds.append((rd, match))
        rounds.sort(
            key=lambda rm: (
                rm[0].created_at,
                rm[1].started_at,
                rm[0].index,
                rm[0].id,
            )
        )
        return rounds

    # --- TrueSkill (simplified) --------------------------------------------------
    def _ts_env(self) -> dict[str, float]:
        mu0 = 25.0
        sigma0 = mu0 / 3
        beta = sigma0 / 2
        tau = sigma0 / 100
        return {"mu0": mu0, "sigma0": sigma0, "beta": beta, "tau": tau}

    def _ts_pdf(self, x: float) -> float:
        return exp(-x * x / 2.0) / sqrt(2.0 * 3.141592653589793)

    def _ts_cdf(self, x: float) -> float:
        return 0.5 * (1 + erf(x / sqrt(2.0)))

    def _ts_update_two_team(
        self,
        ratings: dict[str, tuple[float, float]],
        team_a: list[str],
        team_b: list[str],
        outcome_a: float,
        env: dict[str, float],
    ) -> None:
        if outcome_a == 0.5:
            return
        mu_a = sum(ratings.get(pid, (env["mu0"], env["sigma0"]))[0] for pid in team_a)
        mu_b = sum(ratings.get(pid, (env["mu0"], env["sigma0"]))[0] for pid in team_b)
        sig_a_sq = sum(
            ratings.get(pid, (env["mu0"], env["sigma0"]))[1] ** 2 + env["tau"] ** 2
            for pid in team_a
        )
        sig_b_sq = sum(
            ratings.get(pid, (env["mu0"], env["sigma0"]))[1] ** 2 + env["tau"] ** 2
            for pid in team_b
        )
        c = sqrt(sig_a_sq + sig_b_sq + 2 * env["beta"] ** 2)
        t = (mu_a - mu_b) / c
        sign = 1.0 if outcome_a > 0.5 else -1.0
        v = self._ts_pdf(sign * t) / max(self._ts_cdf(sign * t), 1e-12)
        w = v * (v + sign * t)

        def _apply(team: list[str], direction: float) -> None:
            for pid in team:
                mu, sigma = ratings.get(pid, (env["mu0"], env["sigma0"]))
                sigma_sq = sigma**2 + env["tau"] ** 2
                mu += direction * (sigma_sq / c) * v
                sigma_sq = sigma_sq * (1 - (sigma_sq / (c * c)) * w)
                ratings[pid] = (mu, sqrt(max(sigma_sq, 1e-6)))

        _apply(team_a, sign)
        _apply(team_b, -sign)

    def get_trueskill_progression(
        self, group_id: str, game_id: str
    ) -> dict[str, list[dict[str, object]]]:
        rounds = self.get_rounds_for_dashboard(group_id, game_id)
        env = self._ts_env()
        ratings: dict[str, tuple[float, float]] = {}
        series: dict[str, list[dict[str, object]]] = {}

        for rd, _match in rounds:
            team_a = rd.teams[0].player_ids if rd.teams else []
            team_b = rd.teams[1].player_ids if len(rd.teams) > 1 else []
            if rd.outcome.type == "winloss":
                winner = rd.outcome.data.get("winner")
                if winner == "A":
                    outcome = 1.0
                elif winner == "B":
                    outcome = 0.0
                else:
                    outcome = 0.5
            elif rd.outcome.type == "contract":
                success = rd.outcome.data.get("success")
                outcome = 1.0 if success else 0.0
            else:
                outcome = 0.5

            self._ts_update_two_team(ratings, team_a, team_b, outcome, env)

            for pid in set(team_a + team_b):
                mu, sigma = ratings.get(pid, (env["mu0"], env["sigma0"]))
                conservative = mu - 3 * sigma
                lst = series.setdefault(pid, [])
                lst.append(
                    {
                        "idx": len(lst),
                        "time": rd.created_at,
                        "match_id": rd.match_id,
                        "mu": mu,
                        "sigma": sigma,
                        "conservative": conservative,
                    }
                )
        return series

    # --- Surprise vs expectation ----------------------------------------------
    def _sides_and_scores(self, rd: Round) -> tuple[list[str], list[str], float, float]:
        team_a = rd.teams[0].player_ids if rd.teams else []
        team_b = rd.teams[1].player_ids if len(rd.teams) > 1 else []
        if rd.outcome.type == "winloss":
            winner = rd.outcome.data.get("winner")
            if winner == "A":
                return team_a, team_b, 1.0, 0.0
            if winner == "B":
                return team_a, team_b, 0.0, 1.0
            return team_a, team_b, 0.5, 0.5
        if rd.outcome.type == "contract":
            success = rd.outcome.data.get("success")
            s_att = 1.0 if success else 0.0
            s_def = 1.0 - s_att
            return team_a, team_b, s_att, s_def
        return team_a, team_b, 0.5, 0.5

    def get_surprise_series(
        self, group_id: str, game_id: str
    ) -> dict[str, list[dict[str, object]]]:
        rounds = self.get_rounds_for_dashboard(group_id, game_id)
        ratings: dict[str, float] = {}
        series: dict[str, list[dict[str, object]]] = {}
        for rd, _match in rounds:
            team_a, team_b, S_a, S_b = self._sides_and_scores(rd)
            rA = team_rating(ratings, team_a, self.team_policy, self.default_rating)
            rB = team_rating(ratings, team_b, self.team_policy, self.default_rating)
            E_a = expected(rA, rB)
            E_b = 1 - E_a
            matchup = Matchup(sideA=team_a, sideB=team_b, S=S_a)
            for pid in team_a:
                lst = series.setdefault(pid, [])
                prev = lst[-1]["cum_p"] if lst else 0.0
                p = S_a - E_a
                lst.append(
                    {
                        "idx": len(lst),
                        "time": rd.created_at,
                        "match_id": rd.match_id,
                        "expected": E_a,
                        "actual": S_a,
                        "p": p,
                        "cum_p": prev + p,
                    }
                )
            for pid in team_b:
                lst = series.setdefault(pid, [])
                prev = lst[-1]["cum_p"] if lst else 0.0
                p = S_b - E_b
                lst.append(
                    {
                        "idx": len(lst),
                        "time": rd.created_at,
                        "match_id": rd.match_id,
                        "expected": E_b,
                        "actual": S_b,
                        "p": p,
                        "cum_p": prev + p,
                    }
                )
            deltas = apply_matchup(
                ratings,
                matchup,
                K=20,
                team_policy=self.team_policy,
                distribution_policy=self.distribution_policy,
                default_rating=self.default_rating,
            )
            for pid, delta in deltas.items():
                ratings[pid] = ratings.get(pid, self.default_rating) + delta
        return series

    def get_current_trueskill_stats(
        self, group_id: str, game_id: str
    ) -> dict[str, tuple[float, float, float]]:
        env = self._ts_env()
        progression = self.get_trueskill_progression(group_id, game_id)
        stats: dict[str, tuple[float, float, float]] = {}
        for pid, events in progression.items():
            if not events:
                continue
            last = events[-1]
            stats[pid] = (last["mu"], last["sigma"], last["conservative"])
        return stats

    def get_current_player_stats(
        self, group_id: str, game_id: str
    ) -> list[dict[str, object]]:
        members = self.repo.list_group_member_ids(group_id)
        elo_ratings = dict(self.get_ratings(group_id, game_id))
        ts_stats = self.get_current_trueskill_stats(group_id, game_id)
        env = self._ts_env()
        mu0, sigma0 = env["mu0"], env["sigma0"]
        cons0 = mu0 - 3 * sigma0
        rows: list[dict[str, object]] = []
        for pid in members:
            mu, sigma, cons = ts_stats.get(pid, (mu0, sigma0, cons0))
            rows.append(
                {
                    "player_id": pid,
                    "elo": float(elo_ratings.get(pid, self.default_rating)),
                    "ts_mu": float(mu),
                    "ts_sigma": float(sigma),
                    "ts_cons": float(cons),
                }
            )
        rows.sort(key=lambda r: r["elo"], reverse=True)
        return rows

    def get_player_round_history(
        self, group_id: str, game_id: str, player_id: str
    ) -> list[tuple[datetime, float, str]]:
        """Retourne l'historique par round avec session (match_id) pour l'UI."""
        game = self.repo.get_game(game_id)
        if game is None:
            raise ValueError(f"Game not found: {game_id}")
        rules = self.rules_registry.get(game.ruleset_id)
        matches = sorted(self.repo.list_matches(group_id, game_id), key=lambda m: m.started_at)

        ratings: dict[str, float] = {}
        history: list[tuple[datetime, float, str]] = []
        K_base = game.config.get("K", 20) if isinstance(game.config, dict) else 20
        for match in matches:
            rounds = sorted(self.repo.list_rounds(match.id), key=lambda r: (r.created_at, r.index))
            for round_obj in rounds:
                matchups = rules.to_matchups(round_obj)
                aggregated_deltas: dict[str, float] = {}
                for matchup in matchups:
                    deltas = apply_matchup(
                        ratings,
                        matchup,
                        K=K_base,
                        team_policy=self.team_policy,
                        distribution_policy=self.distribution_policy,
                        default_rating=self.default_rating,
                    )
                    for pid, delta in deltas.items():
                        aggregated_deltas[pid] = aggregated_deltas.get(pid, 0.0) + delta
                for pid, delta in aggregated_deltas.items():
                    ratings[pid] = ratings.get(pid, self.default_rating) + delta
                history.append(
                    (
                        round_obj.created_at,
                        ratings.get(player_id, self.default_rating),
                        match.id,
                    )
                )
        return history

    def list_matches(self, group_id: str, game_id: str | None = None) -> list[Match]:
        return self.repo.list_matches(group_id, game_id)

    def get_open_match(self, group_id: str, game_id: str) -> Match | None:
        return self.repo.find_open_match(group_id, game_id)

    def get_match_details(self, match_id: str) -> dict[str, object]:
        match = self.repo.get_match(match_id)
        if match is None:
            raise ValueError(f"Match not found: {match_id}")
        rounds = self.repo.list_rounds(match_id)
        return {"match": match, "rounds": rounds}

    def delete_round(self, round_id: str) -> dict[str, float]:
        round_obj = self.repo.get_round(round_id)
        if round_obj is None:
            raise ValueError(f"Round not found: {round_id}")
        match = self.repo.get_match(round_obj.match_id)
        if match is None:
            raise ValueError(f"Match not found for round: {round_obj.match_id}")

        self.repo.delete_round(round_id)
        self.repo.delete_rating_events_for_round(round_id)
        return self.recalc_game(match.group_id, match.game_id)

    def recalc_game(self, group_id: str, game_id: str) -> dict[str, float]:
        """Rejoue tous les rounds pour recalculer les ratings et les événements."""
        game = self.repo.get_game(game_id)
        if game is None:
            raise ValueError(f"Game not found: {game_id}")

        rules = self.rules_registry.get(game.ruleset_id)
        matches = self.repo.list_matches(group_id, game_id)

        ratings: dict[str, float] = {}
        games_played: dict[str, int] = {}
        new_events: list[RatingEvent] = []

        for match in sorted(matches, key=lambda m: m.started_at):
            for round_obj in self.repo.list_rounds(match.id):
                matchups = rules.to_matchups(round_obj)
                K_base = game.config.get("K", 20) if isinstance(game.config, dict) else 20
                aggregated_deltas: dict[str, float] = {}
                for matchup in matchups:
                    deltas = apply_matchup(
                        ratings,
                        matchup,
                        K=K_base,
                        team_policy=self.team_policy,
                        distribution_policy=self.distribution_policy,
                        default_rating=self.default_rating,
                    )
                    for pid, delta in deltas.items():
                        aggregated_deltas[pid] = aggregated_deltas.get(pid, 0.0) + delta

                for pid, delta in aggregated_deltas.items():
                    ratings[pid] = ratings.get(pid, self.default_rating) + delta
                    games_played[pid] = games_played.get(pid, 0) + 1

                new_events.append(
                    RatingEvent(
                        id=str(uuid.uuid4()),
                        group_id=group_id,
                        game_id=game_id,
                        round_id=round_obj.id,
                        deltas=aggregated_deltas,
                        meta={"k_base": K_base, "matchups": len(matchups)},
                        created_at=datetime.now(timezone.utc),
                    )
                )

        self.repo.replace_ratings_current(group_id, game_id, ratings, games_played)
        self.repo.replace_rating_events(group_id, game_id, new_events)
        return ratings
