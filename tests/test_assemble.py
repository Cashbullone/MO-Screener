"""Tests für die Datenaufbereitung mit künstlichen Daten (ohne Netzwerk). Start: python tests/test_assemble.py"""
import json
import os
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fetch_data as fd  # noqa: E402
import make_fake  # noqa: E402

RAW, IX, NAMES, SECS = make_fake.build_fake(n_random=60)


def test_assemble_structure():
    p = fd.assemble(RAW, IX, NAMES, sectors=SECS, min_price=5, min_avg_vol=0)
    assert p["asof"] == "2026-10-30" and len(p["dates"]) == fd.KEEP
    assert len(p["stocks"]) == len(RAW)
    for s in p["stocks"]:
        assert len(s["c"]) == len(p["dates"]) and s["c"][-1] == s["p"]
        assert s["atr"] and s["atr"] > 0 and s["sec"] in make_fake.SECS and s["av"] > 0
        assert s["lo"] <= s["p"] <= s["hi"]
    json.dumps(p)


def test_atr20_matches_reference():
    df = RAW["TOPA"].iloc[-120:]
    h, l, c = df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy()
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(len(c) - 20, len(c))]
    assert abs(fd.atr20(df) - round(sum(tr) / 20, 3)) < 1e-9


def test_filters_and_stale():
    raw = dict(RAW)
    df = raw["TOPA"].copy()
    raw["OLD"] = df.iloc[:-3]                           # kein Kurs für die letzten 3 Tage
    raw["PENNY"] = df * np.array([0.01, 0.01, 0.01, 0.01, 1])        # Kurs unter 5 $
    raw["THIN"] = df.assign(Volume=1000.0)
    p = fd.assemble(raw, {**IX, "OLD": {"SP500"}, "PENNY": {"SP500"}, "THIN": {"SP500"}}, NAMES, min_price=5, min_avg_vol=100000)
    got = {s["t"] for s in p["stocks"]}
    assert "PENNY" not in got and "THIN" not in got and "TOPA" in got
    assert "OLD" in got                                  # 3 Tage Rückstand sind erlaubt (Feiertage), 5+ nicht
    raw["OLD2"] = df.iloc[:-8]
    p = fd.assemble(raw, {**IX, "OLD2": {"SP500"}}, NAMES, min_price=5, min_avg_vol=0)
    assert "OLD2" not in {s["t"] for s in p["stocks"]}


def test_drop_after_removes_unfinished_day():
    p = fd.assemble(RAW, IX, NAMES, min_price=5, min_avg_vol=0, drop_after=pd.Timestamp("2026-10-29"))
    assert p["asof"] == "2026-10-29"


def test_market_series():
    m = fd.market_series(make_fake.market())
    assert set(m) == {"sp", "vix"} and len(m["sp"]["c"]) == len(m["sp"]["d"]) == len(make_fake.IDX)
    assert fd.market_series({"^VIX": make_fake.market()["^VIX"]}) is None          # ohne S&P 500 kein Marktfilter


def test_main_writes_files():
    with tempfile.TemporaryDirectory() as tmp:
        fd.OUT_DIR = tmp
        fd.MIN_STOCKS = 10
        fd.build_universe = lambda: (IX, {"SP500": {"ok": True, "n": 1, "new": 1}}, NAMES, SECS)
        fd.download = lambda t: ({k: v for k, v in RAW.items() if k in t}, [])
        fd.fetch_fx = lambda: 1.08
        fd.fetch_market = lambda drop_after=None: fd.market_series(make_fake.market())
        fd.last_complete_day = lambda: pd.Timestamp("2026-10-30")
        fd.INDEXES = ["SP500", "NDX"]
        assert fd.main() == 0
        pr = json.load(open(os.path.join(tmp, "prices.json")))
        me = json.load(open(os.path.join(tmp, "meta.json")))
        assert pr["fx"] == 1.08 and me["stocks"] == len(pr["stocks"]) and me["market"] is True and "sp" in pr["mkt"]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   ", name)
            except Exception:  # noqa: BLE001
                fails += 1
                import traceback
                print("FEHLER", name)
                traceback.print_exc()
    sys.exit(1 if fails else 0)
