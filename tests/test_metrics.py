"""Metric edges (task 5.4, spec §6.6)."""

import pytest

from src.eval.metrics import (choice_pick, gold_row_recall, list_match, normalise_text, numeric_correct, refused,
                              retrieval_hit, score)


def ans(answer="", value=None, items=(), insufficient=False, unit=None):
    return {"answer": answer, "value": value, "unit": unit, "items": list(items), "sources": [],
            "insufficient_context": insufficient}


# --------------------------------------------------------------------------- numbers

@pytest.mark.parametrize("pred, gold, ok", [
    (5.65, 5.60, True),       # 1% of 5.60 = 0.056: just inside
    (5.6561, 5.60, False),    # just outside
    (5.54, 5.60, False),
    (0.015, 0.01, True),      # small value: 0.01-point floor wins over 1% relative
    (0.021, 0.01, False),
    (0.005, 0.0, True),       # zero gold: floor still applies to percent
    (0.02, 0.0, False),
])
def test_numeric_pct_tolerance(pred, gold, ok):
    assert numeric_correct(pred, gold, "pct") is ok


@pytest.mark.parametrize("pred, gold, unit, ok", [
    (19880.41 * 1.0099, 19880.41, "lakhs", True),
    (19880.41 * 1.0101, 19880.41, "lakhs", False),
    (71, 71, "count", True),
    (72, 71, "count", False),  # 1% of 71 = 0.71: an off-by-one count is wrong
    (0, 0, "count", True),
    (0.001, 0, "lakhs", False),  # no point floor for lakhs/counts: zero gold needs exact 0
])
def test_numeric_relative_only(pred, gold, unit, ok):
    assert numeric_correct(pred, gold, unit) is ok


@pytest.mark.parametrize("pred", [None, "5.6", True])
def test_numeric_rejects_non_numbers(pred):
    assert numeric_correct(pred, 5.6, "pct") is False


# --------------------------------------------------------------------------- text and lists

def test_normalise_text():
    assert normalise_text("  ICICI Bank Limited. ") == normalise_text("icici bank ltd") == "icici bank ltd"
    assert normalise_text("7.17% Tata Capital (21/05/2030) **") == "7 17 tata capital 21 05 2030"


def test_list_match_set_equality_and_jaccard():
    gold = ["8% Bond W **", "HDFC Bank Limited"]
    assert list_match(["hdfc bank ltd.", "8% Bond W"], gold) == (True, 1.0)
    exact, jac = list_match(["HDFC Bank Ltd", "Other Ltd"], gold)
    assert not exact and jac == pytest.approx(1 / 3)
    assert list_match([], gold) == (False, 0.0)
    assert list_match(["a", "A."], ["a"]) == (True, 1.0)  # duplicates collapse


OPTS = {"BSLEQTY": ["Flexi Cap"], "BSLFEF": ["Large Cap"]}


@pytest.mark.parametrize("answer, pick", [
    (ans("Aditya Birla Sun Life Large Cap Fund holds more (3.20% vs 2.01%) than the Flexi Cap Fund."), "BSLFEF"),
    (ans("The Flexi Cap Fund holds 2.01%, less than the Large Cap Fund."), "BSLEQTY"),  # earliest mention rule
    (ans("Both are similar.", items=["Large Cap Fund"]), "BSLFEF"),                     # items win over prose
    (ans("I cannot tell."), None),
    (ans("flexicap"), None),                                                            # whole words only
])
def test_choice_pick(answer, pick):
    assert choice_pick(answer, OPTS) == pick


# --------------------------------------------------------------------------- refusals

@pytest.mark.parametrize("answer, is_refused", [
    (ans("x", insufficient=True), True),
    (ans("The expense ratio is not in the provided data."), True),
    (ans("The context does not contain the fund manager."), True),
    (ans("No information about NAV is given."), True),
    (ans("This cannot be determined from the context."), True),
    (ans("ICICI Bank is 5.60% of AUM.", value=5.6), False),
    (ans("Not in the data, but roughly 5%", value=5.0), False),   # a value given is an answer
    (ans("Infosys Ltd."), False),
    (None, False),
])
def test_refused(answer, is_refused):
    assert refused(answer) is is_refused


# --------------------------------------------------------------------------- retrieval

def test_retrieval_metrics():
    gold = [("f", "S", 8), ("f", "S", 9)]
    assert retrieval_hit(gold, [("f", "S", 9), ("f", "S", 20)]) == 1
    assert retrieval_hit(gold, [["f", "S", 20]]) == 0                 # lists (from JSON) work too
    assert gold_row_recall(gold, [["f", "S", 8]]) == 0.5
    assert retrieval_hit([], [("f", "S", 8)]) is None                  # unanswerable
    assert gold_row_recall(gold, None) is None                         # baseline: no retrieval


# --------------------------------------------------------------------------- score

def test_score_number_and_false_refusal():
    s = score("number", 5.5967, [("f", "S", 8)], ans("5.60%", value=5.6), unit="pct", context_rows=[("f", "S", 8)])
    assert (s.correct, s.numeric_correct, s.refused, s.false_refusal, s.retrieval_hit) == (1, 1, 0, 0, 1)
    s = score("number", 5.5967, [("f", "S", 8)], ans("not in the context", insufficient=True), unit="pct",
              context_rows=[])
    assert (s.correct, s.false_refusal, s.retrieval_hit, s.gold_row_recall) == (0, 1, 0, 0.0)


def test_score_failed_method_counts_wrong():
    s = score("number", 5.0, [("f", "S", 8)], None, unit="pct")
    assert s.correct == 0 and s.false_refusal == 0
    assert score("not_in_data", None, [], None).correct == 0


def test_score_list_choice_unanswerable():
    s = score("list", ["Bond A **", "Bond B"], [], ans("", items=["Bond A", "Bond C"]))
    assert s.correct == 0 and s.jaccard == pytest.approx(1 / 3)
    s = score("choice", "BSLFEF", [], ans("Large Cap Fund"), options=OPTS)
    assert s.correct == s.choice_correct == 1
    s = score("not_in_data", None, [], ans("The data does not include the expense ratio."), context_rows=[])
    assert (s.correct, s.unanswerable_correct, s.false_refusal, s.retrieval_hit) == (1, 1, None, None)
    with pytest.raises(ValueError):
        score("essay", None, [], ans())
