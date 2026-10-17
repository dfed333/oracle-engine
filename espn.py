# -*- coding: utf-8 -*-
"""
Oracle Engine — risultati e quote aggiornate dalle pagine pubbliche dei risultati di ESPN (nessuna chiave).

Serve a due cose:
1. RISULTATI SUBITO: una partita finita compare già all'aggiornamento successivo (football-data pubblica i
   risultati una o due volte a settimana, il calendario di fixturedownload a volte in ritardo).
2. QUOTE FRESCHE: le quote di un bookmaker aggiornate fino al calcio d'inizio, anche per le coppe europee
   (football-data le pubblica il martedì e il venerdì, e mai per le coppe). Verificato sul passato su 39.700
   partite: le quote di chiusura indovinano più di quelle di 1-2 giorni prima (favorito 51,4% contro 51,1%,
   Over/Under 2.5 58,4% contro 57,9%), anche quelle di un solo bookmaker. Le quote non si mostrano mai.

Se ESPN non risponde, l'app usa le altre fonti come prima.
"""

import datetime
import json
import os
import time
import urllib.request

import engine

SLUG = {
    "Serie A": "ita.1", "Premier League": "eng.1", "La Liga": "esp.1", "Bundesliga": "ger.1", "Ligue 1": "fra.1",
    "Primeira Liga": "por.1", "Eredivisie": "ned.1", "Pro League (Bel)": "bel.1", "Süper Lig (Tur)": "tur.1",
    "Super League (Gre)": "gre.1", "Premiership (Sco)": "sco.1", "Liga 2": "esp.2", "Ligue 2": "fra.2",
    "Champions League": "uefa.champions", "Europa League": "uefa.europa", "Conference League": "uefa.europa.conf",
}
DIAG = {"richieste": 0, "errori": 0, "partite": 0, "con_quote": 0, "finite": 0}


def _scarica(slug, giorno, ttl_ore):
    cartella = os.path.join(engine.CARTELLA_CACHE, "espn")
    os.makedirs(cartella, exist_ok=True)
    percorso = os.path.join(cartella, f"{slug}_{giorno:%Y%m%d}.json")
    if os.path.exists(percorso) and (time.time() - os.path.getmtime(percorso)) / 3600 < ttl_ore:
        with open(percorso, encoding="utf-8") as f:
            return json.load(f)
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={giorno:%Y%m%d}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
    DIAG["richieste"] += 1
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            dati = json.loads(r.read().decode("utf-8"))
        time.sleep(0.15)
    except Exception:
        DIAG["errori"] += 1
        if os.path.exists(percorso):          # meglio l'ultima copia che niente
            with open(percorso, encoding="utf-8") as f:
                return json.load(f)
        return {}
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(dati, f)
    return dati


def _decimale(americana):
    """Quota americana ("+125", "-160") → decimale (2.25, 1.625)."""
    try:
        x = float(str(americana).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if x >= 100:
        return 1 + x / 100
    if x <= -100:
        return 1 + 100 / -x
    return None


def _quote(c):
    """Attese del mercato dalla quota più recente: (p1, pX, p2, pOver, linea) senza margine, o None."""
    od = (c.get("odds") or [None])[0]
    if not od:
        return None
    ml, tot = od.get("moneyline") or {}, od.get("total") or {}
    def ultima(x):
        x = x or {}
        return (x.get("close") or {}).get("odds") or (x.get("open") or {}).get("odds")
    x12 = engine._devig([_decimale(ultima(ml.get(k))) for k in ("home", "draw", "away")])
    ov = tot.get("over") or {}
    linea_txt = ((ov.get("close") or {}).get("line") or (ov.get("open") or {}).get("line") or "")
    try:
        linea = float(linea_txt.lstrip("ou"))
    except ValueError:
        linea = None
    ou = engine._devig([_decimale(ultima(tot.get(k))) for k in ("over", "under")])
    if not x12 or not ou or linea is None or linea % 1 != 0.5:
        return None
    return [round(x12[0], 5), round(x12[1], 5), round(x12[2], 5), round(ou[0], 5), linea]


def partite(oggi=None, giorni_prima=3, giorni_dopo=6):
    """Partite di campionati e coppe da giorni_prima giorni fa a giorni_dopo giorni avanti."""
    oggi = oggi or datetime.date.today()
    out = []
    for comp, slug in SLUG.items():
        for d in range(-giorni_prima, giorni_dopo + 1):
            giorno = oggi + datetime.timedelta(days=d)
            ttl = 24 if d < -1 else (0.75 if d <= 1 else 6)        # ieri, oggi e domani a ogni aggiornamento
            for e in _scarica(slug, giorno, ttl).get("events", []):
                try:
                    c = e["competitions"][0]
                    casa = next(x for x in c["competitors"] if x["homeAway"] == "home")
                    osp = next(x for x in c["competitors"] if x["homeAway"] == "away")
                    stato = c["status"]["type"]
                except (KeyError, IndexError, StopIteration):
                    continue
                p = {"comp": comp, "t": e.get("date", "")[:16] + ":00Z" if len(e.get("date", "")) >= 16 else None,
                     "casa": casa["team"].get("displayName", ""), "ospite": osp["team"].get("displayName", ""),
                     "finita": bool(stato.get("completed")) and stato.get("name") != "STATUS_POSTPONED",
                     "q": _quote(c)}
                if p["finita"]:
                    try:
                        p["r"] = [int(casa.get("score")), int(osp.get("score"))]
                    except (TypeError, ValueError):
                        p["finita"] = False
                if not p["t"]:
                    continue
                out.append(p)
    DIAG["partite"] = len(out)
    DIAG["con_quote"] = sum(1 for p in out if p["q"])
    DIAG["finite"] = sum(1 for p in out if p.get("finita"))
    return out
