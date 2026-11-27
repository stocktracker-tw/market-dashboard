"""bands.json 是分數區間的唯一來源，而且必須跟引擎一致。"""
import ast
import subprocess

import bands
import gen_stock_pages as gsp
import premarket_score as pm


def _engine_config():
    """engine-src 的 config.py（CI 會先 fetch 這個分支）；拿不到就回 None。"""
    r = subprocess.run(["git", "show", "origin/engine-src:config.py"],
                       capture_output=True, text=True)
    if r.returncode:
        return None
    vals = {}
    for node in ast.parse(r.stdout).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("ACTION_BANDS", "LIGHT_GREEN_MIN", "LIGHT_RED_MAX"):
                vals[name] = ast.literal_eval(node.value)
    return vals


def test_bands_sorted_and_complete():
    mins = [b["min"] for b in bands.BANDS]
    assert mins == sorted(mins, reverse=True)
    assert mins[-1] == 0
    mults = [b["mult"] for b in bands.BANDS]
    assert mults == sorted(mults, reverse=True), "分數越高倍數應越大"


def test_bands_match_engine():
    cfg = _engine_config()
    if cfg is None:
        import pytest
        pytest.skip("沒有 origin/engine-src（先 git fetch origin engine-src）")
    engine = [(t, n, m) for t, n, _a, m in cfg["ACTION_BANDS"]]
    ours = [(b["min"], b["name"], b["mult"]) for b in bands.BANDS]
    assert ours == engine
    assert bands.LIGHT_GREEN_MIN == cfg["LIGHT_GREEN_MIN"]
    assert bands.LIGHT_RED_MAX == cfg["LIGHT_RED_MAX"]


def test_boundaries():
    assert [bands.level(s) for s in (0, 34.9, 35, 44.9, 45, 57.9, 58, 69.9, 70, 100)] == \
        [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    assert gsp.mult_of(44.9) == 0.5 and gsp.mult_of(45) == 1.0
    assert gsp.zone(45) == bands.level(45)


def test_js_zone_matches_python():
    js = bands.js_zone()
    for c in bands.CUTS:
        assert "sc>=%g?" % c in js


def test_premarket_phrases_cover_every_band():
    for b in bands.BANDS:
        assert pm.band_phrase(b["min"]).startswith(b["name"])
        assert b["name"] in pm.PHRASES
