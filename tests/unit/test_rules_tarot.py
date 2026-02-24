import pytest

from elo_app.domain.models import Outcome, Team
from elo_app.rules.tarot import TarotRules
from tests.helpers import make_round


def test_tarot_rules_success_sets_S_to_one():
    teams = [Team("ATT", ["p1", "p2"]), Team("DEF", ["p3", "p4", "p5"])]
    outcome = Outcome(type="contract", data={"success": True})
    rules = TarotRules()

    matchup = rules.to_matchups(make_round(teams, outcome))[0]
    assert matchup.S == 1.0
    assert matchup.W == 1.0
    assert matchup.sideA == ["p1", "p2"]
    assert matchup.sideB == ["p3", "p4", "p5"]
    assert matchup.k_override == rules.k_factor


def test_tarot_rules_failure_sets_S_to_zero_and_margin_weight():
    teams = [Team("ATT", ["p1"]), Team("DEF", ["p2", "p3", "p4"])]
    outcome = Outcome(type="contract", data={"success": False, "margin": 250})
    rules = TarotRules(margin_weight_coeff=0.4, margin_max=300)

    matchup = rules.to_matchups(make_round(teams, outcome))[0]
    assert matchup.S == 0.0
    assert 1.0 < matchup.W <= 1.0 + rules.margin_weight_coeff


def test_tarot_rules_validate_inputs():
    rules = TarotRules()
    with pytest.raises(ValueError):
        rules.to_matchups(make_round([], Outcome(type="contract", data={"success": True})))

    teams = [Team("ATT", ["p1"]), Team("DEF", ["p2", "p3"])]
    with pytest.raises(ValueError):
        rules.to_matchups(make_round(teams, Outcome(type="contract", data={"success": None})))

    with pytest.raises(ValueError):
        rules.to_matchups(make_round(teams, Outcome(type="wrong", data={"success": True})))

