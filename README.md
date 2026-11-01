# MO-Screener (Trend-Momentum)

Eigenständiger Momentum-Screener für US-Aktien. GitHub holt jeden Börsentag nach US-Börsenschluss die Kurse von
**S&P 500 und Nasdaq-100**, die App rechnet daraus eine Rangliste und einen Wochenplan und wird zusammen mit den Daten
als Webseite veröffentlicht. Du öffnest nur den Link.

Die Regeln stammen aus dem Dokument „Trend-Momentum-Strategie für Aktien“ (Clenow, Gray und Vogel, Jegadeesh und Titman,
Faber, Daniel und Moskowitz). **Der Screener arbeitet ohne Minervini:** Den Trendfilter übernehmen Clenows 100-Tage-Linie
und sein Kurslückenfilter. Das Trend Template gibt es im MN-Screener.

Was die App zeigt:

- **Marktfilter:** S&P 500 gegen die 200-Tage-Linie und gegen den 10-Monats-Durchschnitt, dazu die Volatilitätsbremse
  (Abstand zum Hoch und VIX). Ergebnis: Neukäufe erlaubt oder gesperrt, empfohlener Investitionsgrad.
- **Wochenplan:** was du verkaufen und kaufen sollst, mit Stückzahl nach ATR, Sektorgrenze, Positionszahl und Investitionsgrad.
- **Depot:** deine Positionen mit Rang, 100-Tage-Linie, Verkaufssignalen und Sektorübersicht.
- **Rangliste:** die besten 30 nach Momentum-Score, mit Status je Aktie. Dazu eine Suche für jede Aktie.

## Die Regeln in Kürze

| Baustein | Regel |
| --- | --- |
| Universum | S&P 500 und Nasdaq-100 ohne Dubletten, Kurs mindestens 10 $, Tagesumsatz mindestens 20 Mio. $ |
| Score | Durchschnitt der Prozentränge aus 12-1-Rendite und Clenow-Wert (90-Tage-Steigung × R²) |
| Kauf | nur aus den besten 20 % im Rang, Kurs über der 100-Tage-Linie, keine Tagesbewegung über 15 % in 90 Tagen |
| Frog in the Pan | streicht standardmäßig die sprunghaftere Hälfte der Kaufkandidaten (einstellbar, 0 = aus) |
| Marktfilter | keine Neukäufe, wenn der S&P 500 unter seiner 200-Tage-Linie oder am Monatsende unter dem 10-Monats-Durchschnitt liegt |
| Volatilitätsbremse | Markt mehr als 10 % unter dem Hoch und VIX über 30: Investitionsgrad halbiert, danach pro Woche ein Drittel der Lücke zurück |
| Portfolio | 10 Positionen, höchstens 15 % je Position, höchstens 3 je Sektor |
| Größe | Stück = Depot × r ÷ ATR(20), Standard r = 0,25 % |
| Verkauf | Schluss unter der 100-Tage-Linie, Rang schlechter als Top 30 %, Kurslücke über 15 %, 9 % unter dem Einstand |
| Rhythmus | einmal pro Woche an einem festen Tag |

Werte mit „Annahme“ im Dokument (Schwellen der Bremse, r, Grenzen, Stufen des Wiedereinstiegs) sind in der App
einstellbar. Was Quelle und was Annahme ist, steht in der App unter „So rechnet die App“.

## Einrichtung (einmalig, ca. 5 Minuten)

Die Dateien liegen schon im Repository. Du musst nur noch die Veröffentlichung einschalten und den ersten Lauf starten:

1. **Veröffentlichung einschalten:** im Repository „Settings“ → „Pages“ → bei „Source“ **GitHub Actions** wählen.
2. **Ersten Lauf starten:** Reiter „Actions“ → „Kurse aktualisieren und Seite veröffentlichen“ → „Run workflow“.
   Der erste Lauf dauert etwa 10 bis 25 Minuten. Danach läuft die Automatik Montag bis Freitag von selbst
   (22:30 UTC, also 23:30 oder 00:30 Uhr österreichischer Zeit).
3. **App öffnen:** `https://cashbullone.github.io/MO-Screener/`. Auf dem Handy kannst du die Seite
   über das Teilen-Menü zum Home-Bildschirm hinzufügen.

## Was wo gespeichert wird

- Im Repository liegen nur App, Skript und Tests. Die Kursdaten entstehen bei jedem Lauf neu und gehen direkt auf die Webseite.
- Dein Depot und deine Einstellungen bleiben **nur in deinem Browser**. Auf einem zweiten Gerät übertragst du sie mit
  „Depot exportieren“ und „Depot importieren“.
- Die Webseite ist öffentlich erreichbar, wer den Link kennt, sieht die Kurse (aber nicht dein Depot).
  Die Kursdaten stammen von Yahoo Finance und sind für den privaten Gebrauch gedacht. Gib den Link deshalb nicht weiter.

## Einstellungen der Automatik

In `update.yml` unter „Kursdaten holen“ kannst du die auskommentierten Zeilen aktivieren:

- `MIN_PRICE` Mindestkurs in USD, mit dem das Skript vorfiltert (Standard 5). Die App filtert zusätzlich mit ihren eigenen Einstellungen.
- `MIN_AVG_VOL` Mindest-Durchschnittsvolumen der letzten 50 Tage in Aktien (Standard 100000)
- `INDEXES` Standard ist `SP500,NDX`. Mit `SP500,NDX,R2000` kommt der Russell 2000 dazu (der Abruf dauert dann deutlich länger)

Den Sektor liest das Skript aus den Indexlisten. Fehlt er, ergänzt es ihn aus `universe/sectors.csv` und sonst von Yahoo
(Zeile in der Datei: `TICKER,Sektor`).

## Was das Skript an die App liefert

Für jede Aktie: Schlusskurse der letzten 260 Handelstage, ATR(20), Sektor, Index, Durchschnittsvolumen. Dazu S&P 500 und
VIX der letzten rund zwei Jahre und den Wechselkurs. Alle Kennzahlen (12-1, Clenow, Rang, Marktfilter, Plan) rechnet die
App im Browser, damit du die Schwellen verstellen kannst.

## Tests

- `python tests/test_assemble.py` prüft Datenaufbereitung, ATR und Hauptablauf mit künstlichen Daten ohne Netzwerk. Die
  Automatik führt diesen Test vor jedem Datenabruf aus.
- `python tests/check_app.py` (braucht Playwright) lädt die App mit künstlichen Daten und vergleicht 12-1-Rendite,
  Clenow-Wert, Frog-in-the-Pan-Wert, Rang, Marktfilter und den Wochenplan mit einer getrennt geschriebenen
  Python-Rechnung. Außerdem testet es die Handy-Ansicht und das Eintragen eines Kaufs.
- `python tests/make_fake.py ORDNER` erzeugt eine künstliche `prices.json` zum Ausprobieren der App.

## Wenn etwas nicht klappt

- **Lauf schlägt fehl (roter Haken unter „Actions“):** den Lauf öffnen und die Meldung bei „Kursdaten holen“ ansehen.
  Der Lauf bricht absichtlich ab, wenn weniger als 300 Aktien herauskommen. Die Seite zeigt dann weiter die Daten vom letzten
  erfolgreichen Lauf.
- **Yahoo blockiert Abrufe:** passiert gelegentlich. Einfach „Run workflow“ erneut starten.
- **Nach 60 Tagen ohne Änderung im Repository** pausiert GitHub geplante Läufe. Dann unter „Actions“ wieder aktivieren.

Das ist ein Regelrahmen aus der Literatur und keine Anlageberatung. Die Zahlen aus den Studien sind Backtests, meist vor
Kosten und Steuern. Die App macht keinen Backtest. Das Universum besteht aus den heutigen Mitgliedern der Indizes
(Survivorship Bias), und Momentum hatte lange Durststrecken und seltene, heftige Einbrüche.
