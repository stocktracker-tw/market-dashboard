"""排程延遲時的防呆：盤前分數只在開盤前算、Yahoo 盤中 K 棒不收、TAIFEX 沒變不寫。"""
import json
from datetime import datetime, timedelta, timezone

import exit_scores as ex
import fetch_taifex as ft
import premarket_score as pm

TPE = timezone(timedelta(hours=8))


def test_premarket_window():
    at = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TPE)  # noqa: E731
    assert pm.in_premarket_window(at("2026-11-19 08:13"))
    assert not pm.in_premarket_window(at("2026-11-19 09:00"))
    assert not pm.in_premarket_window(at("2026-11-19 13:10"))
    assert not pm.in_premarket_window(at("2026-11-21 08:13"))      # 週六


def test_premarket_inject_idempotent():
    html = '<h2>進場分數 40</h2><p>x</p>'
    once = pm.inject(html, pm.badge_html(40, "basis"))
    assert pm.inject(once, pm.badge_html(41, "basis")).count('id="premarket"') == 1


def test_yahoo_drops_intraday_bar(monkeypatch):
    now = datetime.now(TPE)
    if now.hour * 100 + now.minute >= 1430:
        import pytest
        pytest.skip("收盤後當天那根本來就該收")
    t0 = int(datetime(now.year, now.month, now.day, 1, tzinfo=timezone.utc).timestamp())
    ts = [t0 - 2 * 86400, t0 - 86400, t0]
    monkeypatch.setattr(ex, "fetch_json", lambda *a, **k: {"chart": {"result": [
        {"timestamp": ts, "indicators": {"quote": [{"close": [10, 11, 12]}]}}]}})
    rows = ex.yahoo_year("2330", "twse")
    assert [c for _, c in rows] == [10, 11]


def test_taifex_skips_unchanged(tmp_path, monkeypatch):
    out = tmp_path / "taifex.json"
    old = {"pcr": {"date": "1", "pcr_oi": 1.0, "pcr_vol": 1.0},
           "inst": {"date": "1", "inst_net_oi": 1, "foreign_net_oi": 1}, "updated": "old"}
    out.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(ft, "OUT", str(out))
    monkeypatch.setattr(ft, "fetch_pcr", lambda: old["pcr"])
    monkeypatch.setattr(ft, "fetch_inst", lambda: old["inst"])
    assert ft.main() == 0
    assert json.loads(out.read_text(encoding="utf-8"))["updated"] == "old"
    monkeypatch.setattr(ft, "fetch_pcr", lambda: {"date": "2", "pcr_oi": 2.0, "pcr_vol": 2.0})
    assert ft.main() == 0
    assert json.loads(out.read_text(encoding="utf-8"))["pcr"]["date"] == "2"
