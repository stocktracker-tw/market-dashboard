from datetime import date, timedelta

import post_to_threads as pt


def _year():
    return [date(2026, 1, 1) + timedelta(days=i) for i in range(365)]


def test_daily_rotation_uses_every_quote(monkeypatch):
    monkeypatch.setattr(pt, "score_post", lambda: "SCORE")
    used = {pt.daily_post(d) for d in _year()} - {"SCORE"}
    assert used == set(pt.QUOTES)


def test_evening_rotation_uses_every_quote_and_poll():
    used = {pt.evening_post(d) for d in _year()}
    assert used == set(pt.QUOTES) | set(pt.POLLS)
