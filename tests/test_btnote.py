"""首頁回測對照行：讀得到 backtest.html 的數字、冪等、不跟盤前徽章互換位置。"""
import patch_site as ps
import premarket_score as pm

PAGE = ('<div id="gauge"></div><h2>進場分數 40</h2><p>說明</p>'
        '<div class="foot">x</div>')
BT = ('<h2>台股 0050 <span>0050.TW</span></h2><table><tbody>'
      '<tr><td>固定定額</td><td>840,000</td><td>2,723,023</td><td>+224.2%</td>'
      '<td class="best">33.8%</td><td>-11.1%</td></tr>'
      '<tr><td>主動</td><td>970,000</td><td>3,031,637</td><td>+212.5%</td>'
      '<td>33.6%</td><td>-13.4%</td></tr></tbody></table>'
      '每月基準投入 10000；')


def _patch(html, tmp_path, monkeypatch):
    f = tmp_path / "backtest.html"
    f.write_text(BT, encoding="utf-8")
    monkeypatch.setattr(ps, "BACKTEST_HTML", str(f))
    return ps.patch_btnote(html)[0]


def test_parses_backtest():
    rows, months = ps._backtest_0050(BT)
    assert rows["active"][2] == 33.6 and rows["fixed"][2] == 33.8 and months == 84
    assert "沒有打贏" in ps._btnote_html((rows, months))


def test_idempotent_and_stable_with_premarket(tmp_path, monkeypatch):
    once = _patch(PAGE, tmp_path, monkeypatch)
    assert once.count('id="btnote"') == 1
    assert _patch(once, tmp_path, monkeypatch) == once
    # 盤前徽章後來才插進來：補丁重跑後回測行要在徽章之後，之後誰先重跑都不變
    with_badge = pm.inject(once, pm.badge_html(38, "basis"))
    a = _patch(with_badge, tmp_path, monkeypatch)
    assert a.index('id="premarket"') < a.index('id="btnote"')
    b = pm.inject(a, pm.badge_html(38, "basis"))
    assert b == a and _patch(b, tmp_path, monkeypatch) == a


def test_missing_backtest_hides_line(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "BACKTEST_HTML", str(tmp_path / "nope.html"))
    once = _patch(PAGE, tmp_path, monkeypatch)
    monkeypatch.setattr(ps, "BACKTEST_HTML", str(tmp_path / "nope.html"))
    assert 'id="btnote"' not in ps.patch_btnote(once)[0]
