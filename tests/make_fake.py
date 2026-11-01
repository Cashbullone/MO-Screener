"""Erzeugt ein künstliches Aktienuniversum samt S&P 500 und VIX zum Testen (ohne Netzwerk).

Benannte Fälle (neben vielen Zufallsreihen):
  TOPA/TOPB  gleichmäßiger, langer Aufwärtstrend (Spitze der Rangliste)
  JUMP       starker Trend, aber eine Kurslücke über 15 % in den letzten 90 Tagen
  BELO       starker 12-1-Verlauf, zuletzt unter die 100-Tage-Linie gefallen
  DOWN       langer Abwärtstrend
Start: python tests/make_fake.py OUTDIR [crash]   schreibt OUTDIR/prices.json
  crash: der S&P 500 endet unter seiner 200-Tage-Linie (Marktfilter sperrt)
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

N_DAYS = 420
IDX = pd.bdate_range(end="2026-10-30", periods=N_DAYS)
SECS = ["Information Technology", "Health Care", "Financials", "Consumer Discretionary", "Communication Services",
        "Industrials", "Consumer Staples", "Energy", "Utilities", "Real Estate", "Materials"]


def series(seed, drift=None, vol=None, start=None, shocks=None, vol_mult=1):
    r = np.random.default_rng(seed)
    drift = r.normal(0.0004, 0.0008) if drift is None else drift
    vol = r.uniform(0.01, 0.025) if vol is None else vol
    start = r.uniform(30, 300) if start is None else start
    ret = drift + vol * r.standard_normal(N_DAYS)
    for i, x in (shocks or {}).items():
        ret[i] = x
    c = start * np.exp(np.cumsum(ret))
    gap = 1 + 0.3 * vol * r.standard_normal(N_DAYS)
    o = np.concatenate(([c[0]], c[:-1])) * gap
    h = np.maximum(o, c) * (1 + vol * r.uniform(0.1, 0.8, N_DAYS))
    l = np.minimum(o, c) * (1 - vol * r.uniform(0.1, 0.8, N_DAYS))
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": float(r.integers(2, 30) * 1_000_000 * vol_mult)}, index=IDX)


def market(crash=False, seed=99):
    """S&P 500 und VIX. crash=True: Absturz in den letzten Wochen, VIX hoch."""
    r = np.random.default_rng(seed)
    ret = 0.0010 + 0.005 * r.standard_normal(N_DAYS)
    if crash:
        ret[-45:] = -0.006 + 0.006 * r.standard_normal(45)
    c = 4200 * np.exp(np.cumsum(ret))
    sp = pd.DataFrame({"Close": c, "High": c * 1.004, "Low": c * 0.996, "Open": c, "Volume": 1e9}, index=IDX)
    v = 16 + 3 * r.standard_normal(N_DAYS)
    if crash:
        v[-30:] = 36 + 3 * r.standard_normal(30)
    vix = pd.DataFrame({"Close": np.clip(v, 9, None), "High": v, "Low": v, "Open": v, "Volume": 0.0}, index=IDX)
    return {"^GSPC": sp, "^VIX": vix}


def build_fake(n_random=300, seed=7):
    raw, ix, names, sectors = {}, {}, {}, {}
    raw["TOPA"] = series(1, drift=0.0030, vol=0.006, start=40)
    raw["TOPB"] = series(2, drift=0.0027, vol=0.007, start=55)
    raw["JUMP"] = series(3, drift=0.0030, vol=0.006, start=40, shocks={N_DAYS - 40: 0.2})
    raw["BELO"] = series(4, drift=0.0028, vol=0.006, start=50, shocks={N_DAYS - 12: -0.18})
    raw["DOWN"] = series(5, drift=-0.0030, vol=0.008, start=300)
    for i in range(n_random):
        raw["R%s" % "".join(chr(65 + int(d)) for d in "%04d" % i)] = series(seed * 1000 + i)
    for i, t in enumerate(sorted(raw)):
        ix[t] = {"SP500"} if i % 4 else {"NDX"}
        names[t] = "Firma %s" % t
        sectors[t] = SECS[i % len(SECS)]
    sectors["TOPA"] = sectors["TOPB"] = "Information Technology"      # derselbe Sektor: Sektorgrenze testen
    return raw, ix, names, sectors


def build_payload(crash=False, n_random=300):
    import fetch_data as fd
    raw, ix, names, sectors = build_fake(n_random=n_random)
    payload = fd.assemble(raw, ix, names, sectors=sectors, min_price=5, min_avg_vol=0)
    payload["fx"] = 1.08
    payload["failed"] = []
    payload["mkt"] = fd.market_series(market(crash))
    return payload


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "site_test"
    os.makedirs(out, exist_ok=True)
    p = build_payload(crash="crash" in sys.argv[2:])
    with open(os.path.join(out, "prices.json"), "w") as f:
        json.dump(p, f, separators=(",", ":"))
    print("Aktien:", len(p["stocks"]), "Bytes:", os.path.getsize(os.path.join(out, "prices.json")))
