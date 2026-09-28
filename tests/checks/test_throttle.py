from devpilot.checks.throttle import JournalThrottle


def test_first_call_logs():
    throttle = JournalThrottle(window_seconds=600, clock=lambda: 0.0)
    assert throttle.should_log("demo-app", "not_running") is True


def test_second_call_within_window_is_suppressed():
    now = [0.0]
    throttle = JournalThrottle(window_seconds=600, clock=lambda: now[0])

    assert throttle.should_log("demo-app", "not_running") is True
    now[0] = 100.0
    assert throttle.should_log("demo-app", "not_running") is False


def test_call_after_window_logs_again():
    now = [0.0]
    throttle = JournalThrottle(window_seconds=600, clock=lambda: now[0])

    assert throttle.should_log("demo-app", "not_running") is True
    now[0] = 601.0
    assert throttle.should_log("demo-app", "not_running") is True


def test_different_problem_types_are_independent():
    throttle = JournalThrottle(window_seconds=600, clock=lambda: 0.0)

    assert throttle.should_log("demo-app", "not_running") is True
    assert throttle.should_log("demo-app", "oom_killed") is True


def test_different_containers_are_independent():
    throttle = JournalThrottle(window_seconds=600, clock=lambda: 0.0)

    assert throttle.should_log("demo-app", "not_running") is True
    assert throttle.should_log("other-app", "not_running") is True
