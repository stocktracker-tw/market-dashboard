"""文案方向：分數越高越適合加碼（引擎 ACTION_BANDS）。"""
import os
import re

from conftest import ROOT

# 「低…多扣」「高…少扣」才是寫反；不跨過標點，免得把「高多扣、低少扣」誤判
REVERSED = re.compile(r"(低分|分數低|低時)[^，。、]{0,3}多扣|(高分|分數高|高時)[^，。、]{0,3}少扣")


def test_no_reversed_buy_more_wording():
    for rel in ("scripts/gen_stock_pages.py", "scripts/post_to_threads.py", "THREADS_CONTENT.md"):
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert not REVERSED.search(text), rel
