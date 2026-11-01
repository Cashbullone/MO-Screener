#!/usr/bin/env python3
"""Holt Kursdaten für Nasdaq-100, S&P 500 und Russell 2000 und schreibt
public/data/prices.json und public/data/meta.json für den MO-Screener.

Quellen:
  S&P 500      Wikipedia (Tabelle "List of S&P 500 companies")
  Nasdaq-100   Wikipedia (Tabelle "Nasdaq-100")
  Russell 2000 iShares IWM Holdings (CSV). Ersatzweise universe/russell2000.txt
  Kurse        Yahoo Finance über die Python-Bibliothek yfinance

Einstellungen über Umgebungsvariablen (alle optional):
  OUT_DIR        Zielordner (Standard: public/data)
  MIN_PRICE      Mindestkurs in USD (Standard: 5)
  MIN_AVG_VOL    Mindest-Durchschnittsvolumen, 50 Tage, in Aktien (Standard: 100000)
  INDEXES        Komma-Liste aus SP500,NDX,R2000 (Standard: SP500,NDX)
                 Jede Aktie wird nur einmal geführt: Wer im S&P 500 steht, gilt als S&P 500,
                 "NDX" enthält dann nur die Nasdaq-100-Werte, die nicht im S&P 500 sind.
  R2000_URL      eigene Adresse für die Russell-2000-Liste
"""
import datetime as dt
import io
import json
import math
import os
import re
import sys
import time

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; mo-screener/1.0)"}
OUT_DIR = os.environ.get("OUT_DIR", "public/data")
MIN_PRICE = float(os.environ.get("MIN_PRICE", "5"))
MIN_AVG_VOL = float(os.environ.get("MIN_AVG_VOL", "100000"))
INDEXES = [x.strip() for x in os.environ.get("INDEXES", "SP500,NDX").split(",") if x.strip()]
R2000_URL = os.environ.get(
    "R2000_URL",
    "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund",
)
KEEP = 260          # Handelstage, die gespeichert werden (die App braucht mindestens 253)
BATCH = 100         # Ticker pro Yahoo-Abruf
MIN_STOCKS = 300    # darunter wird der Lauf abgebrochen, damit keine kaputten Daten veröffentlicht werden
TICKER_RE = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")


def log(*a):
    print(*a, flush=True)


def notice(msg, level="notice"):
    """Erscheint als Hinweis oben auf der Lauf-Seite in GitHub (Annotations)."""
    print("::%s title=MO-Screener::%s" % (level, msg.replace("\n", " ")), flush=True)


# ---------------------------------------------------------------- Indexlisten
def norm_ticker(t):
    t = str(t).strip().upper().replace(".", "-")
    return t if TICKER_RE.match(t) else None


def wiki_tables(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))


SECTOR_MAP = {                      # abweichende Schreibweisen auf die GICS-Namen bringen
    "technology": "Information Technology", "information technology": "Information Technology",
    "healthcare": "Health Care", "health care": "Health Care",
    "telecommunications": "Communication Services", "communication": "Communication Services",
    "communication services": "Communication Services", "basic materials": "Materials", "materials": "Materials",
    "consumer discretionary": "Consumer Discretionary", "consumer staples": "Consumer Staples",
    "financials": "Financials", "financial": "Financials", "financial services": "Financials",
    "industrials": "Industrials", "real estate": "Real Estate", "energy": "Energy", "utilities": "Utilities",
    "consumer cyclical": "Consumer Discretionary", "consumer defensive": "Consumer Staples",   # Yahoo-Namen
}


def norm_sector(x):
    if not isinstance(x, str):
        return ""
    x = x.strip()
    return SECTOR_MAP.get(x.lower(), x)


def pairs(df, tcol, ncol, scol=None):
    """Liste aus (Ticker, Name) oder, wenn eine Sektor-Spalte da ist, (Ticker, Name, Sektor)."""
    names = df[ncol] if ncol in df.columns else [""] * len(df)
    out = [(norm_ticker(t), str(n).strip() if isinstance(n, str) else "") for t, n in zip(df[tcol], names)]
    if scol is None or scol not in df.columns:
        return out
    return [(t, n, norm_sector(sec)) for (t, n), sec in zip(out, df[scol])]


def universe_sp500():
    for t in wiki_tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"):
        if "Symbol" in t.columns and len(t) > 400:
            return pairs(t, "Symbol", "Security", "GICS Sector")
    raise RuntimeError("Keine S&P-500-Tabelle gefunden")


def _col(t, names, contains=()):
    cols = {c: " ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns}
    for c, n in cols.items():
        if n.strip().lower() in names:
            return c
    for c, n in cols.items():
        if any(x in n.lower() for x in contains):
            return c
    return None


def _sector_col(t):
    cols = {c: (" ".join(map(str, c)) if isinstance(c, tuple) else str(c)).strip().lower() for c in t.columns}
    for key in ("gics sector", "sector", "icb industry", "industry"):
        for c, n in cols.items():
            if n == key:
                return c
    return None


def ndx_html(url):
    seen = []
    for t in wiki_tables(url):
        tc = _col(t, ("ticker", "symbol", "ticker symbol"))
        seen.append("%dx%s:%s" % (len(t), len(t.columns), "/".join(str(c)[:12] for c in t.columns)[:60]))
        if tc is not None and 80 <= len(t) <= 130:
            return pairs(t, tc, _col(t, ("company", "security", "name"), ("company", "security", "name")) or tc,
                         _sector_col(t))
    raise RuntimeError("Keine Tabelle mit Ticker-Spalte. Gefunden: " + "; ".join(seen[:6]))


def ndx_wikipedia():
    return ndx_html("https://en.wikipedia.org/wiki/Nasdaq-100")


def ndx_wikipedia_list():
    return ndx_html("https://en.wikipedia.org/wiki/List_of_Nasdaq-100_companies")


def ndx_stockanalysis():
    return ndx_html("https://stockanalysis.com/list/nasdaq-100-stocks/")


def ndx_slickcharts():
    return ndx_html("https://www.slickcharts.com/nasdaq100")


def ndx_nasdaq_api():
    r = requests.get("https://api.nasdaq.com/api/quote/list-type/nasdaq100",
                     headers=dict(UA, Accept="application/json, text/plain, */*", Origin="https://www.nasdaq.com",
                                  Referer="https://www.nasdaq.com/"), timeout=20)
    r.raise_for_status()
    rows = r.json()["data"]["data"]["rows"]
    out = []
    for x in rows:
        n = re.sub(r"\s+(Class [A-Z]\s+)?(Common Stock|Ordinary Shares|American Depositary Shares|Capital Stock).*$", "",
                   str(x.get("companyName", "")).strip())
        out.append((norm_ticker(x["symbol"]), n))
    if len(out) < 80:
        raise RuntimeError("Nasdaq-API lieferte nur %d Zeilen" % len(out))
    return out


def ndx_file():
    path = os.path.join(os.path.dirname(__file__), "..", "universe", "nasdaq100.txt")
    if not os.path.exists(path):
        raise RuntimeError("universe/nasdaq100.txt fehlt")
    with open(path, encoding="utf-8") as f:
        return [(norm_ticker(x), "") for x in f.read().split()]


def universe_ndx():
    errs = []
    for fn in (ndx_wikipedia_list, ndx_wikipedia, ndx_stockanalysis, ndx_slickcharts, ndx_nasdaq_api, ndx_file):
        try:
            out = fn()
            log("  Nasdaq-100 aus %s" % fn.__name__)
            return out
        except Exception as e:
            errs.append("%s: %s" % (fn.__name__, str(e)[:160]))
            notice("Nasdaq-100 Quelle %s: %s" % (fn.__name__, str(e)[:230]), "warning")
    raise RuntimeError(" | ".join(errs))


def parse_ishares_csv(text):
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.lower().startswith("ticker,")), None)
    if start is None:
        raise RuntimeError("Kopfzeile 'Ticker' nicht gefunden")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), on_bad_lines="skip")
    if "Asset Class" in df.columns:
        df = df[df["Asset Class"].astype(str).str.strip().str.lower() == "equity"]
    df = df.dropna(subset=["Ticker"])
    secs = df["Sector"] if "Sector" in df.columns else [""] * len(df)
    return [(norm_ticker(t), str(n).strip().title() if isinstance(n, str) else "", norm_sector(sec))
            for t, n, sec in zip(df["Ticker"], df["Name"] if "Name" in df.columns else [""] * len(df), secs)]


def universe_r2000():
    try:
        r = requests.get(R2000_URL, headers=UA, timeout=90)
        r.raise_for_status()
        out = parse_ishares_csv(r.text)
        if len([x for x in out if x[0]]) < 1000:
            raise RuntimeError("zu wenige Zeilen in der iShares-Datei")
        return out
    except Exception as e:  # Ersatz: eigene Liste im Repository
        path = os.path.join(os.path.dirname(__file__), "..", "universe", "russell2000.txt")
        if os.path.exists(path):
            log("  iShares nicht lesbar (%s), nutze universe/russell2000.txt" % e)
            with open(path, encoding="utf-8") as f:
                return [(norm_ticker(x), "") for x in f.read().split()]
        raise


SOURCES = {"SP500": universe_sp500, "NDX": universe_ndx, "R2000": universe_r2000}


def build_universe():
    ix_map, status, names, sectors = {}, {}, {}, {}
    for key in INDEXES:
        try:
            rows = [(r[0], r[1], norm_sector(r[2]) if len(r) > 2 else "") for r in SOURCES[key]() if r[0]]
            new = 0
            for t, n, sec in rows:
                if t in ix_map:               # schon in einem vorrangigen Index: keine Doppelung
                    continue
                ix_map[t] = {key}
                new += 1
                if n:
                    names[t] = n
                if sec:
                    sectors[t] = sec
            status[key] = {"ok": True, "n": len(set(r[0] for r in rows)), "new": new}
            log("  %s: %d Ticker in der Liste, %d davon neu" % (key, status[key]["n"], new))
            notice("%s: %d Ticker in der Liste, %d davon neu" % (key, status[key]["n"], new))
        except Exception as e:
            status[key] = {"ok": False, "error": str(e)[:200]}
            log("  %s: FEHLER %s" % (key, e))
            notice("%s: Liste nicht lesbar: %s" % (key, str(e)[:150]), "warning")
    return ix_map, status, names, sectors


def fetch_fx():
    """USD je 1 EUR (Yahoo-Symbol EURUSD=X). Bei Fehler None, die App nutzt dann ihren eigenen Wert."""
    try:
        import yfinance as yf
        h = yf.Ticker("EURUSD=X").history(period="5d")["Close"].dropna()
        v = num(h.iloc[-1])
        return round(v, 4) if v and 0.5 < v < 2 else None
    except Exception as e:
        log("  Wechselkurs nicht abrufbar:", str(e)[:100])
        return None


# --------------------------------------------------------------------- Kurse
def split_batch(df, batch):
    """Teilt das Ergebnis von yf.download in ein Dict {Ticker: DataFrame}."""
    out = {}
    if df is None or df.empty:
        return out
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = set(df.columns.get_level_values(0))
        for t in batch:
            if t in lvl0:
                sub = df[t].dropna(how="all")
                if not sub.empty:
                    out[t] = sub
    elif len(batch) == 1:
        out[batch[0]] = df.dropna(how="all")
    return out


def download(tickers):
    import yfinance as yf

    raw, failed = {}, []
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i:i + BATCH]
        got = {}
        for attempt in range(3):
            try:
                df = yf.download(batch, period="16mo", interval="1d", group_by="ticker",
                                 auto_adjust=False, threads=True, progress=False, timeout=30)
                got = split_batch(df, batch)
                if got:
                    break
            except Exception as e:
                log("  Abruf %d/%d fehlgeschlagen (%s)" % (attempt + 1, 3, str(e)[:80]))
            time.sleep(5 * (attempt + 1))
        raw.update(got)
        failed += [t for t in batch if t not in got]
        log("  %d/%d Ticker abgerufen" % (min(i + BATCH, len(tickers)), len(tickers)))
        time.sleep(1.5)
    return raw, failed


# ------------------------------------------------------------- Aufbereitung
def to_unix_day(ts):
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return int(ts.normalize().value // 86_400_000_000_000)


def num(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


ATR_N = 20


def atr20(d, n=ATR_N):
    """ATR(20): einfacher Durchschnitt der True Range der letzten 20 Tage (Clenow).
    True Range = max(Hoch-Tief, |Hoch-Vortagesschluss|, |Tief-Vortagesschluss|)."""
    try:
        hi, lo, cl = d["High"].astype(float), d["Low"].astype(float), d["Close"].astype(float)
        pc = cl.shift(1)
        tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1, skipna=False)
        t = tr.iloc[-n:].dropna()
        if len(t) < n - 3:
            return None
        v = num(t.mean())
        return round(v, 3) if v and v > 0 else None
    except Exception:
        return None


def assemble(raw, ix_map, names=None, min_price=MIN_PRICE, min_avg_vol=MIN_AVG_VOL, keep=KEEP, drop_after=None,
             sectors=None):
    """Baut das Ausgabeformat. raw: {Ticker: DataFrame mit Close, High, Low, Volume}."""
    frames = {}
    for t, df in raw.items():
        if not {"Close", "High", "Low", "Volume"} <= set(df.columns):
            continue
        d = df.copy()
        d.index = [pd.Timestamp(x).tz_localize(None) if pd.Timestamp(x).tzinfo else pd.Timestamp(x) for x in d.index]
        d = d[~d.index.duplicated(keep="last")].sort_index()
        d = d.dropna(subset=["Close"])
        if drop_after is not None:                  # unfertiger Börsentag (Markt noch offen) gehört nicht in die Daten
            d = d[d.index <= drop_after]
        if len(d) >= 200:
            frames[t] = d
    if not frames:
        return None
    # gemeinsame Handelstage: die am häufigsten vorkommenden der letzten Zeit
    counts = {}
    for d in frames.values():
        for x in d.index[-keep - 5:]:
            counts[x] = counts.get(x, 0) + 1
    need = max(counts.values()) * 0.3
    dates = sorted(x for x, n in counts.items() if n >= need)[-keep:]
    last_day = dates[-1]
    stocks = []
    for t in sorted(frames):
        d = frames[t]
        if (last_day - d.index[-1]).days > 5:      # seit Tagen kein Kurs: ausgelistet oder Datenfehler
            continue
        close = d["Close"].reindex(dates)
        p = num(d["Close"].iloc[-1])
        w = d.iloc[-252:]
        vol_series = w["Volume"].dropna()
        av = num(d["Volume"].dropna().iloc[-50:].mean()) if len(vol_series) else None
        if p is None or p < min_price or av is None or av < min_avg_vol:
            continue
        if close.notna().sum() < 200:
            continue
        stocks.append({
            "t": t,
            "n": (names or {}).get(t, ""),
            "ix": sorted(ix_map.get(t, [])),
            "sec": (sectors or {}).get(t, ""),
            "c": [None if num(v) is None else round(float(v), 2) for v in close],
            "p": round(p, 2),
            "hi": round(float(w["High"].max()), 2),
            "lo": round(float(w["Low"].min()), 2),
            "vol": int(num(d["Volume"].iloc[-1]) or 0),
            "av": int(av),
            "atr": atr20(d),
            "pe": None,
        })
    return {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": last_day.strftime("%Y-%m-%d"),
        "dates": [to_unix_day(x) for x in dates],
        "stocks": stocks,
    }


MKT_KEEP = 520          # ca. 2 Jahre Handelstage für S&P 500 und VIX


def market_series(raw, drop_after=None, keep=MKT_KEEP):
    """Baut {"sp": {"d": [...], "c": [...]}, "vix": {...}} aus rohen Yahoo-Daten (^GSPC, ^VIX)."""
    out = {}
    for key, sym in (("sp", "^GSPC"), ("vix", "^VIX")):
        df = raw.get(sym)
        if df is None or "Close" not in df.columns:
            continue
        c = df["Close"].dropna()
        c.index = [pd.Timestamp(x).tz_localize(None) if pd.Timestamp(x).tzinfo else pd.Timestamp(x) for x in c.index]
        c = c[~c.index.duplicated(keep="last")].sort_index()
        if drop_after is not None:
            c = c[c.index <= drop_after]
        c = c.iloc[-keep:]
        if len(c) < 120:
            continue
        out[key] = {"d": [to_unix_day(x) for x in c.index], "c": [round(float(v), 2) for v in c]}
    return out if "sp" in out else None


def fetch_market(drop_after=None):
    """S&P 500 und VIX für Marktfilter und Volatilitätsbremse. Bei Fehler None: die App zeigt dann nur die Marktbreite."""
    try:
        import yfinance as yf
        syms = ["^GSPC", "^VIX"]
        df = yf.download(syms, period="2y", interval="1d", group_by="ticker", auto_adjust=False,
                         threads=False, progress=False, timeout=30)
        res = market_series(split_batch(df, syms), drop_after)
        if res is None:
            raise RuntimeError("keine Daten für ^GSPC")
        return res
    except Exception as e:
        log("  Marktdaten nicht abrufbar:", str(e)[:120])
        notice("S&P 500 / VIX nicht abrufbar: %s" % str(e)[:120], "warning")
        return None


SECTOR_FILE = os.path.join(os.path.dirname(__file__), "..", "universe", "sectors.csv")
SECTOR_BUDGET_S = 120       # so lange darf der Yahoo-Ersatzabruf höchstens dauern


def load_sector_file(path=None):
    """universe/sectors.csv: eine Zeile je Aktie, 'TICKER,Sektor'. Für Werte, die weder die Indexliste noch Yahoo kennen."""
    path = path or SECTOR_FILE
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if "," not in line:
                continue
            t, sec = [x.strip() for x in line.split(",", 1)]
            t = norm_ticker(t)
            if t and sec:
                out[t] = norm_sector(sec)
    return out


def yahoo_sector(t):
    """Sektor einer Aktie von Yahoo (Namen werden auf GICS-Namen angeglichen). Leer, wenn nicht abrufbar."""
    import yfinance as yf
    for attempt in range(2):
        try:
            sec = norm_sector((yf.Ticker(t).info or {}).get("sector"))
            if sec:
                return sec
        except Exception as e:
            log("  Sektor %s: %s" % (t, str(e)[:80]))
        time.sleep(1.5)
    return ""


def fill_sectors(stocks, budget=SECTOR_BUDGET_S, path=None):
    """Ergänzt fehlende Sektoren: zuerst aus universe/sectors.csv, dann einzeln von Yahoo. Gibt die Anzahl ergänzter Aktien zurück."""
    miss = [s for s in stocks if not s.get("sec")]
    if not miss:
        return 0
    fixed, got, t0 = load_sector_file(path), 0, time.time()
    for s in miss:                                   # zuerst die eigene Datei, die kostet keine Zeit
        if s["t"] in fixed:
            s["sec"] = fixed[s["t"]]
            got += 1
    for s in [x for x in miss if not x["sec"]]:
        if time.time() - t0 > budget:
            log("  Zeitbudget für Sektorabruf erreicht")
            break
        v = yahoo_sector(s["t"])
        if v:
            s["sec"] = v
            got += 1
        time.sleep(0.5)
    return got


def last_complete_day():
    """Letzter abgeschlossener US-Börsentag: Ist es in New York noch vor 16:30 Uhr, zählt der heutige Tag nicht."""
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    day = now.date() if (now.hour, now.minute) >= (16, 30) else now.date() - dt.timedelta(days=1)
    return pd.Timestamp(day)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    log("Indexlisten holen")
    ix_map, status, names, sectors = build_universe()
    tickers = sorted(ix_map)
    if not tickers:
        log("Keine Ticker gefunden, Abbruch.")
        notice("Keine Ticker gefunden, Abbruch.", "error")
        return 1
    log("%d verschiedene Ticker, lade Kurse" % len(tickers))
    raw, failed = download(tickers)
    payload = assemble(raw, ix_map, names, drop_after=last_complete_day(), sectors=sectors)
    if not payload or len(payload["stocks"]) < MIN_STOCKS:
        log("Nur %d Aktien aufbereitet (Minimum %d), Abbruch." % (len(payload["stocks"]) if payload else 0, MIN_STOCKS))
        notice("Nur %d Aktien aufbereitet, Minimum %d. Abgerufen: %d von %d Ticker." % (len(payload["stocks"]) if payload else 0, MIN_STOCKS, len(raw), len(tickers)), "error")
        return 1
    n_extra = fill_sectors(payload["stocks"])
    n_sec = sum(1 for x in payload["stocks"] if x.get("sec"))
    unknown = [x["t"] for x in payload["stocks"] if not x.get("sec")]
    log("  Sektor bei %d von %d Aktien bekannt (%d nachträglich ergänzt)" % (n_sec, len(payload["stocks"]), n_extra))
    if unknown:
        notice("Sektor unbekannt bei %d Aktien: %s. Trage sie in universe/sectors.csv ein (Zeile: TICKER,Sektor)." % (len(unknown), ", ".join(unknown[:15]) + (" …" if len(unknown) > 15 else "")), "warning")
    payload["failed"] = failed[:300]
    payload["fx"] = fetch_fx()
    payload["mkt"] = fetch_market(last_complete_day())
    with open(os.path.join(OUT_DIR, "prices.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    per_ix = {k: sum(1 for s in payload["stocks"] if k in s["ix"]) for k in INDEXES}
    meta = {"generated": payload["generated"], "asof": payload["asof"], "stocks": len(payload["stocks"]),
            "per_index": per_ix, "fx": payload["fx"], "market": bool(payload["mkt"]), "sources": status, "failed": len(failed),
            "filters": {"min_price": MIN_PRICE, "min_avg_volume": MIN_AVG_VOL}}
    with open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    log("Fertig: %d Aktien, Stand %s, %s" % (len(payload["stocks"]), payload["asof"], per_ix))
    notice("Fertig: %d Aktien, Stand %s, je Index %s, Kurs nicht abrufbar: %d, Wechselkurs %s" % (len(payload["stocks"]), payload["asof"], per_ix, len(failed), payload["fx"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
