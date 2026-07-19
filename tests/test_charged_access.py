"""V4 blocker 2: every holdout access is charged BEFORE execution.

Required adversarial test (audit): a candidate that captures its input and
raises three times with three fresh nonces must show LOOKS_SPENT=3, three
charge rows, and three terminally FAILED result rows — no free holdout
observations, and no truth labels in anything it captured.
"""
import json
import time

import pytest

from eagle_eye.posterior_engine import build_demo_registry
from eagle_eye.sealed_evaluator import EvaluatorError, SealedEvaluator
from eagle_eye.evolution import default_config


def _evaluator(secret, **kw):
    return SealedEvaluator(tenant_id="tenant-demo", run_id="r-charge", secret=secret, **kw)


def test_adversarial_capture_and_raise_burns_three_charged_looks():
    registry = build_demo_registry()
    evaluator = _evaluator("charge-1")
    captured: list[dict] = []

    def adversarial_factory(config):
        def fn(compiled):
            captured.append(compiled)  # exfiltrate the compiled context
            raise RuntimeError("adversarial candidate refuses to answer")
        return fn

    config = default_config()
    for i in range(3):
        with pytest.raises(EvaluatorError, match="look .* consumed"):
            evaluator.compare(champion_config=config, challenger_config=config,
                              candidate_id=f"cand-adv-{i}", snapshot_id="snap-x",
                              registry=registry, fn_factory=adversarial_factory,
                              nonce=f"fresh-nonce-{i}")
    # LOOKS_SPENT=3: fresh nonces bought NOTHING for free
    assert evaluator.looks_spent() == 3
    charges = [r for r in evaluator.ledger.rows if r["body"]["kind"] == "promotion_look_charge"]
    results = [r for r in evaluator.ledger.rows if r["body"]["kind"] == "promotion_look_result"]
    assert len(charges) == 3 and len(results) == 3
    assert all(r["body"]["terminal_status"] == "FAILED" for r in results)
    # every result row links back to exactly one charge row
    assert {r["body"]["charge_row_hash"] for r in results} == {c["row_hash"] for c in charges}
    # alpha was burned by the failures (derived from charges, never stored)
    assert evaluator.alpha_spent() == 3 * evaluator.alpha_per_look
    # the captured contexts contain NO target truth — features and CLOSED
    # historical prior-task outcomes only (those are legitimate training
    # inputs; the sealed secret is the TARGET case's realized outcome)
    assert captured, "the adversary did capture inputs (expected, and charged)"
    blob = json.dumps(captured, default=str)
    for forbidden in ('"outcomes"', '"theta"', '"hyper"', '"p_stockout"',
                      '"truth"', '"regime_id"'):
        assert forbidden not in blob, f"target-truth structure leaked: {forbidden}"
    # strongest form: rebuild the sealed suite from the test's own secret (as
    # the post-reveal verifier would) and prove the actual target truth VALUES
    # never crossed the boundary into the candidate's hands
    from eagle_eye.prediction_court import build_holdout_suite
    from eagle_eye.stats import stable_seed
    suite = build_holdout_suite(stable_seed("promotion-holdout", "charge-1") % (1 << 31), scale=1)
    leaked = [row["target"]["case_id"] for row in suite["cases"]
              if str(round(row["truth"]["outcomes"]["wait_incumbent"]["log_final_delay"], 6)) in blob]
    assert not leaked, f"target truth values leaked for cases: {leaked}"


def test_charge_row_lands_before_candidate_code_runs():
    registry = build_demo_registry()
    evaluator = _evaluator("charge-2")
    seen_at_execution = {}

    def probe_factory(config):
        def fn(compiled):
            # snapshot the ledger AT THE MOMENT candidate code first runs
            if "charges" not in seen_at_execution:
                seen_at_execution["charges"] = sum(
                    1 for r in evaluator.ledger.rows
                    if r["body"]["kind"] == "promotion_look_charge")
            raise RuntimeError("stop after observing")
        return fn

    with pytest.raises(EvaluatorError):
        evaluator.compare(champion_config=default_config(), challenger_config=default_config(),
                          candidate_id="cand-probe", snapshot_id="snap-x",
                          registry=registry, fn_factory=probe_factory, nonce="n-probe")
    assert seen_at_execution["charges"] == 1  # charged BEFORE execution


def test_timeout_is_charged_and_terminal():
    registry = build_demo_registry()
    evaluator = _evaluator("charge-3", timeout_s=0.2)

    def sleepy_factory(config):
        def fn(compiled):
            time.sleep(5.0)
        return fn

    with pytest.raises(EvaluatorError, match="timed out"):
        evaluator.compare(champion_config=default_config(), challenger_config=default_config(),
                          candidate_id="cand-sleepy", snapshot_id="snap-x",
                          registry=registry, fn_factory=sleepy_factory, nonce="n-sleepy")
    assert evaluator.looks_spent() == 1
    results = [r for r in evaluator.ledger.rows if r["body"]["kind"] == "promotion_look_result"]
    assert results[-1]["body"]["terminal_status"] == "TIMED_OUT"


def test_failed_looks_exhaust_the_budget():
    registry = build_demo_registry()
    evaluator = _evaluator("charge-4", max_looks=2)

    def broken_factory(config):
        def fn(compiled):
            raise ValueError("broken")
        return fn

    for i in range(2):
        with pytest.raises(EvaluatorError, match="consumed"):
            evaluator.compare(champion_config=default_config(), challenger_config=default_config(),
                              candidate_id=f"c{i}", snapshot_id="s", registry=registry,
                              fn_factory=broken_factory, nonce=f"n{i}")
    with pytest.raises(EvaluatorError, match="budget exhausted"):
        evaluator.compare(champion_config=default_config(), challenger_config=default_config(),
                          candidate_id="c9", snapshot_id="s", registry=registry,
                          fn_factory=broken_factory, nonce="n9")
    assert evaluator.looks_spent() == 2  # refusal after exhaustion charged nothing


def test_replayed_nonce_refused_without_charge_or_execution():
    registry = build_demo_registry()
    evaluator = _evaluator("charge-5")
    ran = {"count": 0}

    def counting_factory(config):
        def fn(compiled):
            ran["count"] += 1
            raise RuntimeError("x")
        return fn

    with pytest.raises(EvaluatorError, match="consumed"):
        evaluator.compare(champion_config=default_config(), challenger_config=default_config(),
                          candidate_id="c", snapshot_id="s", registry=registry,
                          fn_factory=counting_factory, nonce="dup")
    executed_after_first = ran["count"]
    with pytest.raises(EvaluatorError, match="replayed nonce"):
        evaluator.compare(champion_config=default_config(), challenger_config=default_config(),
                          candidate_id="c", snapshot_id="s", registry=registry,
                          fn_factory=counting_factory, nonce="dup")
    assert evaluator.looks_spent() == 1  # replay refused pre-charge
    assert ran["count"] == executed_after_first  # and pre-execution


def test_malformed_candidate_response_is_charged_failed():
    registry = build_demo_registry()
    evaluator = _evaluator("charge-6")

    def garbage_factory(config):
        def fn(compiled):
            return {"nonsense": True}  # malformed: no interventions/_delay_dist
        return fn

    with pytest.raises(EvaluatorError, match="consumed"):
        evaluator.compare(champion_config=default_config(), challenger_config=default_config(),
                          candidate_id="c-garbage", snapshot_id="s", registry=registry,
                          fn_factory=garbage_factory, nonce="n-garbage")
    results = [r for r in evaluator.ledger.rows if r["body"]["kind"] == "promotion_look_result"]
    assert results[-1]["body"]["terminal_status"] == "FAILED"
    assert evaluator.looks_spent() == 1


def test_failed_final_audit_consumes_the_one_shot():
    registry = build_demo_registry()
    evaluator = _evaluator("charge-7")

    def broken_factory(config):
        def fn(compiled):
            raise ValueError("broken final audit")
        return fn

    with pytest.raises(EvaluatorError, match="one-shot consumed"):
        evaluator.final_audit(config=default_config(), champion_id="c", registry=registry,
                              fn_factory=broken_factory, nonce="fa-broken")
    from eagle_eye.evolution import predictor_from_config
    with pytest.raises(EvaluatorError, match="one-shot"):
        evaluator.final_audit(config=default_config(), champion_id="c", registry=registry,
                              fn_factory=predictor_from_config, nonce="fa-retry")
