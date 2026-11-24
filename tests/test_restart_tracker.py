"""RestartTracker rules (REQ-004), with the clock passed in."""

from __future__ import annotations

import pytest

T = 1_700_000_000.0


@pytest.fixture
def tracker(hh):
    return hh.RestartTracker()


def test_tracker_first_value(tracker):
    assert tracker.restart_at is None
    assert tracker.observe(100, True, T) == T - 100
    assert tracker.restart_at == T - 100


def test_tracker_first_value_is_whole_seconds(tracker):
    assert tracker.observe(100.4, True, T + 0.9) == float(int(T + 0.9 - 100.4))
    assert tracker.restart_at == int(tracker.restart_at)


def test_tracker_stable_while_ticking(tracker):
    first = tracker.observe(100, True, T)
    second = tracker.observe(102, True, T + 2)
    third = tracker.observe(104, True, T + 4.5)
    assert first == second == third == T - 100


def test_tracker_uptime_goes_backwards(tracker):
    first = tracker.observe(5000, True, T)
    assert first == T - 5000
    second = tracker.observe(3, True, T + 10)
    assert second == T + 10 - 3
    # Further ticking after the restart keeps the new value.
    assert tracker.observe(5, True, T + 12) == second


def test_tracker_uptime_backwards_within_tolerance_still_resets(tracker):
    # Rule 3 applies even when the candidate is within the tolerance.
    tracker.observe(200, True, T)
    assert tracker.observe(150, True, T - 30) == T - 30 - 150
    assert tracker.restart_at == T - 180


def test_tracker_missed_restart_tolerance(tracker):
    first = tracker.observe(1000, True, T)
    assert first == T - 1000
    # Hub restarted while we were not looking: uptime is higher, not lower.
    second = tracker.observe(4990, True, T + 5000)
    assert second == T + 10


def test_tracker_small_drift_within_tolerance_kept(hh, tracker):
    tracker.observe(1000, True, T)
    drift = hh.RESTART_TOLERANCE_SECONDS
    assert tracker.observe(1000, True, T + drift) == T - 1000
    assert tracker.observe(1000, True, T + drift + 1) == T + drift + 1 - 1000


def test_tracker_offline_keeps_value(tracker):
    stored = tracker.observe(100, True, T)
    assert tracker.observe(5000, False, T + 50) == stored
    assert tracker.restart_at == stored
    # Offline frames do not update the last uptime seen either.
    assert tracker.observe(152, True, T + 52) == stored


def test_tracker_offline_before_first_value(tracker):
    assert tracker.observe(100, False, T) is None
    assert tracker.restart_at is None
    assert tracker.observe(110, True, T + 10) == T - 100


def test_tracker_online_unknown_still_observes(tracker):
    assert tracker.observe(100, None, T) == T - 100


def test_tracker_missing_uptime_keeps_value(tracker):
    stored = tracker.observe(100, True, T)
    assert tracker.observe(None, True, T + 1000) == stored
    assert tracker.restart_at == stored


def test_tracker_missing_uptime_before_first_value(tracker):
    assert tracker.observe(None, True, T) is None


@pytest.mark.parametrize("bad", [-1, -0.5, True, False, "100", float("nan"), float("inf")])
def test_tracker_negative_or_bool_uptime_ignored(tracker, bad):
    assert tracker.observe(bad, True, T) is None
    stored = tracker.observe(100, True, T)
    assert tracker.observe(bad, True, T + 500) == stored


def test_tracker_fed_from_parsed_frame(hh, frame):
    health = hh.parse_hub_health(frame)
    tracker = hh.RestartTracker()
    assert tracker.observe(health.uptime_seconds, health.online, T) == T - 3600
