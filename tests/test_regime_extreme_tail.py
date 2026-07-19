from datetime import date
import math

import eagle_eye.regimes as regimes


def test_extreme_heavy_tail_sample_is_bounded_and_representable(monkeypatch):
    """Unbounded Student-t draws must not overflow exp/timedelta or JSON."""
    heavy = next(
        item for item in regimes.default_world_config()["regimes"]
        if item["hyper"].get("heavy_tail_df")
    )
    monkeypatch.setattr(regimes, "_sample_obs", lambda *_args, **_kwargs: 1e12)

    task = regimes.generate_task(
        regime=heavy,
        tenant_id="tenant-test",
        task_index=0,
        anchor=date(2025, 1, 1),
        n_observations=2,
        intervention_id="split_order",
        world_seed=7,
    )

    realized = task["task"]["realized"]
    assert realized["final_delay_days"] == regimes._MAX_SYNTHETIC_DELAY_DAYS
    assert realized["recovery_days"] <= regimes._MAX_SYNTHETIC_RECOVERY_DAYS
    assert math.isfinite(realized["exposure_usd"])
    assert task["task"]["as_of_end"].startswith("2035-")
