"""Browsertest der App gegen eine unabhängige Python-Rechnung (Momentum, Marktfilter, Wochenplan, Depot).

Braucht Playwright (pip install playwright, playwright install chromium). Start: python tests/check_app.py
Die Rechnung in diesem Skript ist absichtlich getrennt von der JavaScript-Rechnung der App geschrieben.
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import make_fake  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SITE = os.path.join(os.path.dirname(__file__), "..", "site", "index.html")
DEF = dict(eq=50000, cur="USD", fx=1.08, mf=True, bd=10, bx=30, mt=20, mx=30, fp=50, minP=10, minDV=20,
           maxPos=10, rp=0.25, cap=15, sx=3, sl=9, wd=3)


# ------------------------------------------------------------ Referenzrechnung
def ref_mom(c):
    n = len(c)
    m = c[n - 22] / c[n - 253] - 1
    r = c[n - 252:n - 21] / c[n - 253:n - 22] - 1                    # Tage n-252 .. n-22
    up, dn = float((r > 0).mean()), float((r < 0).mean())
    y, x = np.log(c[-90:]), np.arange(90)
    b, a = np.polyfit(x, y, 1)
    r2 = 1 - ((y - (a + b * x)) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return dict(m=m, cl=(math.exp(b * 250) - 1) * 100 * r2, fip=float(np.sign(m)) * (dn - up), up=up, dn=dn)


def pct(vals, v):
    lo = sum(1 for x in vals if x < v)
    return min(99, max(1, 1 + 98 * lo / (len(vals) - 1)))


def ref_rank(payload, cfg):
    V = {}
    for s in payload["stocks"]:
        if s["p"] >= cfg["minP"] and s["p"] * s["av"] >= cfg["minDV"] * 1e6:
            c = np.array(s["c"], dtype=float)
            if np.isnan(c).any():
                continue
            V[s["t"]] = ref_mom(c)
    ms, cls = [v["m"] for v in V.values()], [v["cl"] for v in V.values()]
    for t, v in V.items():
        v["sc"] = (pct(ms, v["m"]) + pct(cls, v["cl"])) / 2
    order = sorted(V, key=lambda t: (-V[t]["sc"], -V[t]["cl"], t))
    for i, t in enumerate(order):
        V[t]["r"], V[t]["top"] = i + 1, (i + 1) / len(order) * 100
    return V, order


def ref_market(payload, cfg):
    sp, vx = payload["mkt"]["sp"], payload["mkt"]["vix"]
    c, d, v = np.array(sp["c"]), sp["d"], dict(zip(vx["d"], vx["c"]))
    n = len(c)
    above200 = c[-1] > c[-200:].mean()
    months = {}
    for i, u in enumerate(d):
        t = np.datetime64(u, "D").astype("datetime64[M]")
        months[t] = i                                              # letzter Handelstag je Monat
    keys = sorted(months)
    last = pd.Timestamp(np.datetime64(d[-1], "D"))
    nb = last + pd.Timedelta(days=1)
    while nb.weekday() >= 5:
        nb += pd.Timedelta(days=1)
    if nb.month == last.month:                                     # laufender Monat noch nicht abgeschlossen
        keys = keys[:-1]
    mon = [c[months[k]] for k in keys[-10:]]
    below = (mon[-1] < sum(mon) / 10) if len(mon) == 10 else None

    def brake(i):
        dd = (1 - c[i] / c[max(0, i - 251):i + 1].max()) * 100
        return d[i] in v and dd > cfg["bd"] and v[d[i]] > cfg["bx"]
    now = brake(n - 1)
    lastB = next((i for i in range(n - 1, -1, -1) if d[n - 1] - d[i] <= 28 and brake(i)), -1) if True else -1
    w = None if lastB < 0 else (d[n - 1] - d[lastB]) // 7
    f = 0.5 if now else (0.5 + 0.5 * w / 3 if lastB >= 0 and w < 3 else 1)
    level = int((0.5 if below else 1) * f * 100 + 0.5)
    return dict(block=(not above200) or below is True, level=level, above200=bool(above200), below=below, brake=now)


def ref_plan(payload, cfg, positions, V, order, mk):
    by = {s["t"]: s for s in payload["stocks"]}
    cut = None
    if cfg["fp"] > 0:
        pool = sorted(V[t]["fip"] for t in V if V[t]["top"] <= cfg["mt"])
        keep = math.ceil(len(pool) * (100 - cfg["fp"]) / 100)
        cut = pool[keep - 1] if keep >= 1 else -math.inf

    def info(s):
        c = np.array(s["c"], dtype=float)
        s100 = c[-100:].mean()
        gap = max(abs(c[i] / c[i - 1] - 1) for i in range(len(c) - 90, len(c)))
        return s["p"] < s100, gap > 0.15

    def gate_ok(t):
        v, (b100, gp) = V[t], info(by[t])
        return v["top"] <= cfg["mt"] and not b100 and not gp and not (cut is not None and v["top"] <= cfg["mt"] and v["fip"] > cut)

    held = {}
    for p in positions:
        h = held.setdefault(p["t"], dict(q=0, cost=0))
        h["q"] += p["q"]
        h["cost"] += p["q"] * p["p"]
    sells, keep_ = [], []
    for t, h in held.items():
        s = by.get(t)
        if not s:
            keep_.append(t)
            continue
        b100, gp = info(s)
        ex = b100 or gp or (t in V and V[t]["top"] > cfg["mx"]) or (cfg["sl"] > 0 and s["p"] <= h["cost"] / h["q"] * (1 - cfg["sl"] / 100))
        (sells if ex else keep_).append(t)
    eq = cfg["eq"]
    slots = cfg["maxPos"] - len(keep_)
    invested = sum(held[t]["q"] * by[t]["p"] if t in by else held[t]["cost"] for t in keep_)
    secn = {}
    for t in keep_:
        if t in by and by[t].get("sec"):
            secn[by[t]["sec"]] = secn.get(by[t]["sec"], 0) + 1
    room = max(0, mk["level"] / 100 * eq - invested)
    buys = []
    if not (mk["block"] and cfg["mf"]):
        for t in order:
            if t in held or not gate_ok(t):
                continue
            if slots <= 0:
                break
            s = by[t]
            if cfg["sx"] > 0 and s["sec"] and secn.get(s["sec"], 0) >= cfg["sx"]:
                continue
            q = max(0, min(math.floor(eq * cfg["rp"] / 100 / s["atr"]), math.floor(eq * cfg["cap"] / 100 / s["p"]) if cfg["cap"] > 0 else 10 ** 9))
            if q * s["p"] > room:
                q = math.floor(room / s["p"])
            if q < 1:
                continue
            buys.append((t, q))
            slots -= 1
            room -= q * s["p"]
            secn[s["sec"]] = secn.get(s["sec"], 0) + 1
    return sorted(sells), buys


# ------------------------------------------------------------------ Browser
class Run:
    def __init__(self, pw, payload, cfg=None, pos=None, width=1100):
        self.errors = []
        self.browser = pw.chromium.launch()
        self.ctx = self.browser.new_context(viewport={"width": width, "height": 900})
        self.ctx.add_init_script("localStorage.setItem('mo1', %s)" % json.dumps(json.dumps({"cfg": cfg or {}, "pos": pos or []})))
        body, html = json.dumps(payload), open(SITE, encoding="utf-8").read()
        self.ctx.route("http://mo.test/**", lambda r: r.fulfill(
            status=200, content_type="application/json" if r.request.url.endswith(".json") else "text/html",
            body=body if r.request.url.endswith(".json") else html))
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.page.goto("http://mo.test/index.html")
        self.page.wait_for_function("document.querySelector('#msg').textContent.startsWith('Kursdaten geladen')")

    def js(self, expr):
        return self.page.evaluate(expr)

    def close(self):
        self.browser.close()


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1, abs(b))


def main():
    fails = []

    def check(cond, msg):
        print(("ok    " if cond else "FEHLER ") + msg)
        if not cond:
            fails.append(msg)

    normal = make_fake.build_payload(crash=False)
    crash = make_fake.build_payload(crash=True)
    with sync_playwright() as pw:
        # 1 Momentum und Rang
        r = Run(pw, normal, cfg={"cur": "USD", "fp": 50})
        js = r.js("() => JSON.parse(JSON.stringify(MO))")
        V, order = ref_rank(normal, DEF)
        check(set(js) == set(V), "gleiche Aktien im Ranking (%d)" % len(V))
        worst = {k: max(abs(js[t][k] / sc - V[t][s]) for t in V) for k, s, sc in (("m", "m", 100), ("cl", "cl", 1), ("fip", "fip", 1))}
        check(worst["m"] < 1e-9 and worst["cl"] < 1e-6 and worst["fip"] < 1e-9, "12-1, Clenow, Frog-in-the-Pan stimmen (Abweichung %s)" % {k: "%.2e" % v for k, v in worst.items()})
        check(all(js[t]["r"] == V[t]["r"] for t in V), "Rangfolge identisch")
        check(all(abs(js[t]["s"] - round(V[t]["sc"])) <= 1 for t in V), "Score stimmt (Rundung)")
        check(order.index("TOPA") < 10 and order.index("TOPB") < 10 and order.index("DOWN") > len(order) * 0.9, "TOPA/TOPB in den Top 10, DOWN im letzten Zehntel: Rang %d, %d, %d" % (order.index("TOPA") + 1, order.index("TOPB") + 1, order.index("DOWN") + 1))
        st = r.js("() => ({jump:xinfo(BY.JUMP).gapHit, belo:xinfo(BY.BELO).below100, topa:xinfo(BY.TOPA).gapHit||xinfo(BY.TOPA).below100})")
        check(st["jump"] and st["belo"] and not st["topa"], "Kurslücke bei JUMP, 100-Tage-Linie bei BELO, TOPA sauber")
        mx = r.js("() => JSON.parse(JSON.stringify(MX))")
        mk = ref_market(normal, DEF)
        check(mx["block"] == mk["block"] and mx["level"] == mk["level"], "Marktfilter normal: block=%s level=%s" % (mx["block"], mx["level"]))
        check(not r.errors, "keine JavaScript-Fehler: %s" % r.errors[:2])
        r.close()

        # 2 Marktfilter im Crash
        r = Run(pw, crash, cfg={"cur": "USD"})
        mx = r.js("() => JSON.parse(JSON.stringify(MX))")
        mk = ref_market(crash, DEF)
        check(mx["block"] == mk["block"] and mx["level"] == mk["level"] and mx["brakeNow"] == mk["brake"], "Marktfilter Crash: block=%s level=%s bremse=%s" % (mx["block"], mx["level"], mx["brakeNow"]))
        check(mx["block"] and r.js("() => PLAN.buys.length") == 0 and "gesperrt" in r.page.inner_text("#mkt"), "Crash: keine Käufe im Plan, Marktkarte meldet Sperre")
        r.close()

        # 3 Wochenplan gegen Referenz (ohne und mit Depot, verschiedene Einstellungen)
        cases = [
            ("leeres Depot", {"fp": 0}, []),
            ("Standard mit Frog in the Pan", {}, []),
            ("Sektorgrenze 1", {"fp": 0, "sx": 1}, []),
            ("5 Positionen, r=0,5 %", {"fp": 0, "maxPos": 5, "rp": 0.5, "cap": 10}, []),
            ("kleiner Investitionsgrad", {"fp": 0, "eq": 3000}, []),
            ("Depot mit Verkaufssignalen", {"fp": 0}, [
                {"id": "a", "t": "DOWN", "q": 10, "p": 280, "d": "2026-09-01"},
                {"id": "b", "t": "BELO", "q": 20, "p": 50, "d": "2026-09-01"},
                {"id": "c", "t": "JUMP", "q": 20, "p": 60, "d": "2026-09-01"},
                {"id": "d", "t": "TOPA", "q": 30, "p": 100, "d": "2026-09-01"}]),
            ("Stop-Loss-Verkauf", {"fp": 0}, [{"id": "e", "t": "TOPB", "q": 10, "p": 10000, "d": "2026-09-01"}]),
        ]
        for name, over, pos in cases:
            cfg = dict(DEF, **over)
            r = Run(pw, normal, cfg=dict(over, cur="USD"), pos=pos)
            V, order = ref_rank(normal, cfg)
            sells, buys = ref_plan(normal, cfg, pos, V, order, ref_market(normal, cfg))
            got = r.js("() => ({s:PLAN.sells.map(e=>e.t).sort(),b:PLAN.buys.map(b=>[b.t,b.q])})")
            check(got["s"] == sells and [tuple(x) for x in got["b"]] == buys, "Plan '%s': %d Verkäufe, %d Käufe stimmen mit der Referenz überein" % (name, len(sells), len(buys)))
            check(not r.errors, "  keine JavaScript-Fehler (%s)" % (r.errors[:1],))
            r.close()

        # 4 Anzeige: Texte, Handy-Breite, Eingabe
        r = Run(pw, normal, cfg={"cur": "EUR"}, width=390)
        check(r.js("() => document.documentElement.scrollWidth <= 392"), "Handy 390 px: kein seitliches Scrollen")
        txt = r.page.inner_text("#plan")
        check("Kaufen" in txt and "Kauf eintragen" in txt, "Wochenplan zeigt Käufe mit Knopf")
        r.page.fill("#q", "topa")
        check("TOPA" in r.page.inner_text("#qres"), "Suche findet TOPA")
        r.page.click("[data-buy]")
        check(r.page.input_value("#ht") != "" and float(r.page.input_value("#hq")) > 0, "„Kauf eintragen“ füllt das Formular vor")
        r.page.click("#hsave")
        check("im Depot" in r.page.inner_text("#ranks") or r.js("() => S.pos.length") == 1, "Kauf landet im Depot")
        r.page.click("text=Als Text kopieren oder einfügen")
        r.page.click("#bkc")
        bk = json.loads(r.page.input_value("#bkt"))
        check(bk["app"] == "mo-screener" and len(bk["pos"]) == 1, "Sicherungstext enthält das Depot")
        check(not r.errors, "keine JavaScript-Fehler (Handy)")
        if os.environ.get("SHOT"):
            r.page.screenshot(path=os.environ["SHOT"], full_page=True)
        r.close()
    print("\n%d Prüfungen fehlgeschlagen" % len(fails) if fails else "\nalle Prüfungen bestanden")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
