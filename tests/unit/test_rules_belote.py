import pytest

from elo_app.domain.models import Outcome, Team
from elo_app.rules.belote import BeloteRules
from tests.helpers import make_round


def test_belote_rules_maps_winner_a_to_victory():
    teams = [Team("A", ["p1", "p2"]), Team("B", ["p3", "p4"])]
    outcome = Outcome(type="winloss", data={"winner": "A"})
    rules = BeloteRules()

    matchups = rules.to_matchups(make_round(teams, outcome))

    assert len(matchups) == 1
    matchup = matchups[0]
    assert matchup.S == 1.0
    assert matchup.W == 1.0
    assert matchup.sideA == ["p1", "p2"]
    assert matchup.sideB == ["p3", "p4"]
    assert matchup.k_override == rules.k_factor


def test_belote_rules_handles_winner_b_and_margin_weight():
    teams = [Team("A", ["p1", "p2"]), Team("B", ["p3", "p4"])]
    outcome = Outcome(type="winloss", data={"winner": "B", "margin": 120})
    rules = BeloteRules(margin_weight_coeff=0.5, margin_max=200)

    matchup = rules.to_matchups(make_round(teams, outcome))[0]

    assert matchup.S == 0.0
    assert 1.0 < matchup.W <= 1.0 + rules.margin_weight_coeff


def test_belote_rules_allows_draw():
    teams = [Team("A", ["p1", "p2"]), Team("B", ["p3", "p4"])]
    outcome = Outcome(type="winloss", data={"winner": "draw"})
    rules = BeloteRules()

    matchup = rules.to_matchups(make_round(teams, outcome))[0]
    assert matchup.S == 0.5


def test_belote_rules_requires_teams_and_correct_outcome_type():
    rules = BeloteRules()
    with pytest.raises(ValueError):
        rules.to_matchups(make_round([], Outcome(type="winloss", data={"winner": "A"})))

    teams = [Team("A", ["p1", "p2"]), Team("B", ["p3", "p4"])]
    with pytest.raises(ValueError):
        rules.to_matchups(make_round(teams, Outcome(type="bad", data={})))

    with pytest.raises(ValueError):
        rules.to_matchups(make_round(teams, Outcome(type="winloss", data={"winner": "X"})))
