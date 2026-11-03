import json
from types import SimpleNamespace

from conftest import synthetic
from datadraft import court
from datadraft.decide import rule
from datadraft.delta import Evaluator, horizon, parse_trade
from datadraft.projections import project

A = ["QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "WR3"]
B = ["QB2", "RB3", "RB4", "WR4", "WR5", "TE2", "RB5"]
PTS = {"QB1": 20, "RB1": 15, "RB2": 10, "WR1": 14, "WR2": 12, "TE1": 8, "WR3": 9,
       "QB2": 19, "RB3": 16, "RB4": 6, "WR4": 13, "WR5": 11, "TE2": 9, "RB5": 7}
IDS = {"E1", "E2", "E3"}


def ruled():
    snap = synthetic({1: A, 2: B}, PTS)
    t = parse_trade(snap, "RB2 Player for RB3 Player")
    m = project(snap)
    return snap, m, rule(Evaluator(snap, m, horizon(snap, t.give + t.get)), t)


def arg(text, ids):
    return {"text": text, "evidence_ids": ids}


def test_validator_accepts_placeholders_and_ranks():
    ok, errors = court.validate({"for": [arg("He'd be your RB2 and adds {E2} a week.", ["E2"])]}, IDS)
    assert errors == [] and ok["for"][0].evidence_ids == ["E2"]


def test_validator_rejects_bare_numbers_unknown_ids_and_uncited():
    raw = {"for": [arg("Adds 6 points a week.", ["E2"]),
                   arg("Adds {E9} a week.", ["E9"]),
                   arg("He is simply better.", [])],
           "against": [arg("Week {E3} matters. So does depth.", ["E3"])]}
    ok, errors = court.validate(raw, IDS)
    assert ok["for"] == [] and ok["against"] == []
    assert len(errors) == 4
    assert "bare number" in errors[0] and "unknown" in errors[1] and "no evidence" in errors[2]
    assert "one sentence" in errors[3]


def test_bundle_has_no_team_names():
    snap, m, r = ruled()
    text = json.dumps(court.bundle(snap, m, r))
    assert "Team 1" not in text and "Team 2" not in text
    assert "RB3 Player" in text


class FakeClient:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []
        self.messages = self
        self.beta = self

    def create(self, **kw):
        self.sent.append(kw)
        text = json.dumps(self.replies.pop(0))
        return SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=500),
                               content=[SimpleNamespace(type="text", text=text)])


GOOD = {"for": [arg("It adds {E2} a week to your lineup.", ["E2"])],
        "against": [arg("They lose {E3} a week.", ["E3"])],
        "rationale": [arg("The gain clears the band of {E4}.", ["E2", "E4"])]}
BAD = {"for": [arg("It adds 6 a week.", ["E2"])], "against": [], "rationale": []}


def test_regenerates_with_errors_then_renders_values():
    snap, m, r = ruled()
    client = FakeClient([BAD, GOOD])
    res = court.argue(snap, m, r, client=client)
    assert res.calls == 2 and res.notice == ""
    assert "bare number" in client.sent[1]["messages"][-1]["content"]
    assert res.arguments["for"][0].text == "It adds +6.0 a week to your lineup."


def test_withholds_after_three_failures():
    snap, m, r = ruled()
    res = court.argue(snap, m, r, client=FakeClient([BAD, BAD, BAD]))
    assert res.calls == 3 and res.notice == court.WITHHELD and res.arguments["for"] == []


def test_no_key_skips_court():
    snap, m, r = ruled()
    res = court.argue(snap, m, r)
    assert res.calls == 0 and "ANTHROPIC_API_KEY" in res.notice


def test_bundle_omits_non_positive_best_week_and_counts_weeks():
    snap, m, r = ruled()  # +6.0 every week
    labels = {i["label"]: i["value"] for i in court.bundle(snap, m, r)}
    assert "your best week for this trade" in labels
    assert "your worst week for this trade" not in labels
    assert labels["weeks where your lineup shows a gain"] == "2 of 2"
    assert labels["weeks where your lineup shows a loss"] == "0 of 2"


def test_cost_is_tracked_per_call_at_the_serving_models_rates():
    snap, m, r = ruled()
    res = court.argue(snap, m, r, client=FakeClient([BAD, GOOD]))
    # 2 calls x (2000 x $4 + 500 x $20) / 1M = 2 x $0.018
    assert res.calls == 2 and round(res.cost_usd, 4) == 0.036


def test_spend_cap_never_starts_a_call_that_could_overshoot():
    snap, m, r = ruled()
    client = FakeClient([GOOD])
    res = court.argue(snap, m, r, client=client, budget_usd=0.01)
    assert client.sent == [] and res.notice == court.CAP_NOTICE and not res.arguments
    roomy = court.argue(snap, m, r, client=FakeClient([GOOD]), budget_usd=1.0)
    assert roomy.calls == 1 and roomy.arguments["for"]


def test_requests_use_server_side_refusal_fallback():
    snap, m, r = ruled()
    client = FakeClient([GOOD])
    court.argue(snap, m, r, client=client)
    assert client.sent[0]["fallbacks"] == "default"
    assert client.sent[0]["betas"] == ["server-side-fallback-2026-07-01"]
