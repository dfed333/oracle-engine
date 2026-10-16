# -*- coding: utf-8 -*-
"""
Oracle Engine — arbitri.

Storico: transfermarkt-datasets (archivio pubblico con i dati di Transfermarkt):
arbitro, cartellini e rigori di ogni partita dal 2012 per 11 campionati e le 3
coppe europee. I falli fischiati vengono dalla stessa partita di football-data.co.uk.
Stagione in corso e arbitri designati: football-data.co.uk (Inghilterra e
Scozia) e, se c'è la chiave gratuita FOOTBALL_DATA_KEY, football-data.org
(Serie A, Premier, Liga, Bundesliga, Ligue 1, Eredivisie, Primeira Liga, Champions).

Effetto sul pronostico, verificato giorno per giorno su 41.557 partite:
fattore cartellini = (somma dei rapporti "cartellini / media del campionato"
delle sue partite, con memoria di un anno, + K) / (peso + K), K = 10.
Un arbitro con 3 partite conta poco, uno con 60 partite recenti conta molto.
I rigori dell'arbitro invece NON aiutano a prevedere quelli futuri (verificato):
si mostrano, ma non entrano nel calcolo.
"""

import csv
import datetime
import difflib
import gzip
import io
import json
import os
import urllib.request
from collections import Counter, defaultdict

import engine
import sorgenti
from sorgenti import norm

URL_TM = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/{}.csv.gz"
COMP_TM = {
    "IT1": "Serie A", "ES1": "La Liga", "GB1": "Premier League", "L1": "Bundesliga", "FR1": "Ligue 1",
    "NL1": "Eredivisie", "PO1": "Primeira Liga", "TR1": "Süper Lig (Tur)", "SC1": "Premiership (Sco)",
    "BE1": "Pro League (Bel)", "GR1": "Super League (Gre)",
    "CL": "Champions League", "EL": "Europa League", "UCOL": "Conference League",
}
FDORG = {"PL": "Premier League", "PD": "La Liga", "SA": "Serie A", "BL1": "Bundesliga", "FL1": "Ligue 1",
         "DED": "Eredivisie", "PPL": "Primeira Liga", "CL": "Champions League"}
K_ARB = 10.0           # partite "neutre" virtuali (scelto sulla verifica: tra 5 e 80, il migliore)
EMIVITA_ARB = 365      # memoria dell'arbitro: dopo un anno una partita vale metà (la più precisa tra 1, 2 e 4 anni)
STAGIONI_TABELLA = 6


def _stagione(d):
    return d.year if d.month >= 7 else d.year - 1


def _gz_righe(dati):
    return csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(dati)), encoding="utf-8"))


def _riassunto_tm():
    """Una riga per partita: campionato, data, squadre, arbitro, cartellini, rossi, rigori segnati."""
    g = sorgenti.scarica(URL_TM.format("games"), sorgenti._cartella("arbitri", "games.csv.gz"), max_ore=24 * 7, timeout=120)
    e = sorgenti.scarica(URL_TM.format("game_events"), sorgenti._cartella("arbitri", "game_events.csv.gz"),
                         max_ore=24 * 7, timeout=300)
    if not g or not e:
        return []
    firma = [len(g), len(e)]
    cache = sorgenti._cartella("arbitri", "riassunto_tm.json")
    try:
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("firma") == firma:
            return d["partite"]
    except (OSError, ValueError):
        pass
    giochi = {}
    for r in _gz_righe(g):
        comp = COMP_TM.get(r["competition_id"])
        arb = (r.get("referee") or "").strip()
        if not comp or not arb:
            continue
        try:
            gc, go = int(r["home_club_goals"]), int(r["away_club_goals"])
        except (TypeError, ValueError):
            continue
        giochi[r["game_id"]] = {"l": comp, "d": r["date"][:10], "c": r["home_club_name"], "o": r["away_club_name"],
                                "a": arb, "gc": gc, "go": go, "h": r["home_club_id"],
                                "kc": 0, "ko": 0, "rc": 0, "ro": 0, "pc": 0, "po": 0, "ev": 0}
    for r in _gz_righe(e):
        x = giochi.get(r["game_id"])
        if not x:
            continue
        casa = r["club_id"] == x["h"]
        x["ev"] = 1                      # la partita ha gli eventi (altrimenti 0 cartellini vorrebbe dire "non so")
        if r["type"] == "Cards":
            x["kc" if casa else "ko"] += 1
            if "Red card" in r["description"] or "Second yellow" in r["description"]:
                x["rc" if casa else "ro"] += 1
        elif r["type"] == "Goals":
            parti = [p.strip() for p in r["description"].split(",")]
            if len(parti) > 1 and parti[1] == "Penalty":
                x["pc" if casa else "po"] += 1
    partite = sorted(giochi.values(), key=lambda x: x["d"])
    for x in partite:
        del x["h"]
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"firma": firma, "partite": partite}, f, ensure_ascii=False)
    return partite


class Nomi:
    """Unisce i nomi degli arbitri delle diverse fonti ("M Oliver" ↔ "Michael Oliver")."""

    def __init__(self, nomi_per_lega):
        self.esatti = {}
        self.chiavi = defaultdict(set)
        for lega, nomi in nomi_per_lega.items():
            for n in nomi:
                self.esatti[norm(n)] = n
                t = norm(n).split()
                if len(t) >= 2:
                    for cognome in t[1:]:
                        self.chiavi[(lega, cognome, t[0][0])].add(n)
                        self.chiavi[(None, cognome, t[0][0])].add(n)

    def trova(self, nome, lega=None):
        if not nome:
            return None
        n = norm(nome)
        if n in self.esatti:
            return self.esatti[n]
        t = n.split()
        if len(t) >= 2:
            for chiave in ((lega, t[-1], t[0][0]), (None, t[-1], t[0][0])):
                c = self.chiavi.get(chiave)
                if c and len(c) == 1:
                    return next(iter(c))
        return None


def _simile(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def _abbina_partita(indice, comp, d, casa, osp, soglia=0.7):
    """Trova nella lista del giorno (±1) la partita con i nomi più simili (somma delle due somiglianze)."""
    migliore, punti = None, soglia
    for dd in (d, d - datetime.timedelta(days=1), d + datetime.timedelta(days=1)):
        for x in indice.get((comp, dd), []):
            s = _simile(casa, x[0]) + _simile(osp, x[1])
            if s > punti:
                migliore, punti = x, s
    return migliore


def _stessa_partita(per_risultato, lega, d, gc, go, casa, osp):
    """Partita football-data con stessa data (±1) e stesso risultato; se sono più d'una, la più simile nei nomi."""
    cand = []
    for dd in (d, d - datetime.timedelta(days=1), d + datetime.timedelta(days=1)):
        cand += per_risultato.get((lega, dd, gc, go), [])
    if len(cand) <= 1:
        return cand[0] if cand else None
    return max(cand, key=lambda m: _simile(casa, m["casa"]) + _simile(osp, m["ospite"]))


def _fdorg(chiave, anno, log):
    """Partite della stagione da football-data.org (serve la chiave gratuita). [(comp, data, casa, osp, arbitro)]"""
    out = []
    for codice, comp in FDORG.items():
        url = f"https://api.football-data.org/v4/competitions/{codice}/matches?season={anno}"
        try:
            req = urllib.request.Request(url, headers={"X-Auth-Token": chiave, "User-Agent": sorgenti.UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                dati = json.loads(r.read().decode("utf-8"))
        except Exception as e:      # chiave sbagliata, limite di richieste, rete: si va avanti senza
            log(f"    football-data.org {codice}: {type(e).__name__} {getattr(e, 'code', '')}")
            continue
        n = 0
        for m in dati.get("matches", []):
            arb = next((x.get("name") for x in m.get("referees") or [] if x.get("type") == "REFEREE"), None)
            if not arb or not m.get("utcDate"):
                continue
            h, a = m.get("homeTeam") or {}, m.get("awayTeam") or {}
            out.append((comp, datetime.date.fromisoformat(m["utcDate"][:10]),
                        h.get("shortName") or h.get("name") or "", a.get("shortName") or a.get("name") or "", arb))
            n += 1
        log(f"    football-data.org {codice}: {n} partite con l'arbitro")
    return out


def costruisci(partite_fd, finestra, oggi, log=print):
    """
    Ritorna (AR, designati):
      AR = {arbitro: profilo} per gli arbitri attivi negli ultimi 3 anni (e quelli designati)
      designati = {(data, casa, ospite): arbitro} per le partite della finestra
    """
    tm = _riassunto_tm()
    log(f"    storico arbitri: {len(tm)} partite (transfermarkt-datasets)")
    per_lega = defaultdict(set)
    for x in tm:
        per_lega[x["l"]].add(x["a"])
    nomi = Nomi(per_lega)

    # indici: partite football-data (per i falli e la stagione in corso) e partite della finestra (per i designati)
    per_giorno, per_risultato, per_fin = defaultdict(list), defaultdict(list), defaultdict(list)
    for m in partite_fd:
        per_giorno[(m["lega"], m["data"])].append((m["casa"], m["ospite"], m))
        per_risultato[(m["lega"], m["data"], m["gc"], m["go"])].append(m)
    for f in finestra:
        per_fin[(f["comp"], datetime.date.fromisoformat(f["t"][:10]))].append((f["c"], f["o"], f["t"][:10]))

    # 1) storico transfermarkt, con i falli dalla partita football-data corrispondente
    righe = []
    ultima_tm = {}
    for x in tm:
        d = datetime.date.fromisoformat(x["d"])
        r = {"a": x["a"], "l": x["l"], "d": d, "gol": x["gc"] + x["go"], "casa": x["gc"] > x["go"],
             "k": x["kc"] + x["ko"] if x["ev"] else None, "ros": x["rc"] + x["ro"] if x["ev"] else None,
             "rig": x["pc"] + x["po"] if x["ev"] else None, "fal": None, "fonte": "tm"}
        if x["l"] in engine.LEGHE_FD.values():
            m = _stessa_partita(per_risultato, x["l"], d, x["gc"], x["go"], x["c"], x["o"])
            if m and m.get("fal_c") is not None and m.get("fal_o") is not None:
                r["fal"] = m["fal_c"] + m["fal_o"]
        righe.append(r)
        ultima_tm[x["l"]] = max(ultima_tm.get(x["l"], d), d)

    # 2) stagione in corso dove l'archivio non arriva: football-data.co.uk (Inghilterra, Scozia)
    for m in partite_fd:
        if not m.get("arb") or m["data"] <= ultima_tm.get(m["lega"], datetime.date.min):
            continue
        nome = nomi.trova(m["arb"], m["lega"]) or m["arb"]
        righe.append({"a": nome, "l": m["lega"], "d": m["data"], "gol": m["gc"] + m["go"], "casa": m["gc"] > m["go"],
                      "k": None if m["cart_c"] is None else m["cart_c"] + m["cart_o"],
                      "ros": None if m["ros_c"] is None else m["ros_c"] + m["ros_o"], "rig": None,
                      "fal": None if m["fal_c"] is None else m["fal_c"] + m["fal_o"], "fonte": "fd"})

    # 3) football-data.org (solo con la chiave): arbitri della stagione in corso e designati
    designati = {}
    chiave = os.environ.get("FOOTBALL_DATA_KEY", "").strip()
    fdorg = _fdorg(chiave, sorgenti.anno_stagione(oggi), log) if chiave else []
    for comp, d, casa, osp, arb in fdorg:
        nome = nomi.trova(arb, comp) or arb
        if d < oggi and d > ultima_tm.get(comp, datetime.date.min) and comp in engine.LEGHE_FD.values():
            g = _abbina_partita(per_giorno, comp, d, casa, osp)
            if g:
                p = g[2]
                righe.append({"a": nome, "l": comp, "d": p["data"], "gol": p["gc"] + p["go"], "casa": p["gc"] > p["go"],
                              "k": None if p["cart_c"] is None else p["cart_c"] + p["cart_o"],
                              "ros": None if p["ros_c"] is None else p["ros_c"] + p["ros_o"], "rig": None,
                              "fal": None if p["fal_c"] is None else p["fal_c"] + p["fal_o"], "fonte": "fd"})
        f = _abbina_partita(per_fin, comp, d, casa, osp)
        if f:
            designati[(f[2], f[0], f[1])] = nome

    # designati dal calendario di football-data.co.uk (colonna Referee) e dalle partite già giocate
    fx = sorgenti.scarica("https://football-data.co.uk/fixtures.csv", sorgenti._cartella("calendari", "fixtures.csv"), max_ore=3)
    if fx:
        for r in csv.DictReader(io.StringIO(fx.decode("utf-8-sig", errors="replace"))):
            lega = engine.LEGHE_FD.get((r.get("Div") or "").strip())
            d = engine._parse_data(r.get("Date") or "")
            arb = (r.get("Referee") or "").strip()
            if lega and d and arb:
                casa = engine.FD_RENAME.get(r["HomeTeam"].strip(), r["HomeTeam"].strip())
                osp = engine.FD_RENAME.get(r["AwayTeam"].strip(), r["AwayTeam"].strip())
                f = _abbina_partita(per_fin, lega, d, casa, osp, soglia=1.6)
                if f:
                    designati[(f[2], f[0], f[1])] = nomi.trova(arb, lega) or arb
    for m in partite_fd:
        if m.get("arb") and m["data"] >= oggi - datetime.timedelta(days=7):
            f = _abbina_partita(per_fin, m["lega"], m["data"], m["casa"], m["ospite"], soglia=1.6)
            if f:
                designati[(f[2], f[0], f[1])] = nomi.trova(m["arb"], m["lega"]) or m["arb"]

    # medie per campionato e stagione, separate per fonte (le fonti contano i cartellini in modo un po' diverso)
    medie = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for r in righe:
        ch = (r["l"], _stagione(r["d"]), r["fonte"])
        for k in ("k", "ros", "rig", "fal", "gol"):
            if r[k] is not None:
                medie[ch][k][0] += r[k]; medie[ch][k][1] += 1

    def media(r, k):
        s, n = medie[(r["l"], _stagione(r["d"]), r["fonte"])][k]
        return s / n if n >= 20 else None

    # profili
    per_arb = defaultdict(list)
    for r in righe:
        per_arb[r["a"]].append(r)
    voluti = set(designati.values())
    limite = oggi - datetime.timedelta(days=3 * 365)
    AR = {}
    for nome, lst in per_arb.items():
        lst.sort(key=lambda r: r["d"])
        if lst[-1]["d"] < limite and nome not in voluti:
            continue
        # fattore cartellini per il pronostico (memoria 1 anno, K partite neutre)
        w_tot = s_tot = 0.0
        for r in lst:
            mk = media(r, "k")
            if r["k"] is None or not mk:
                continue
            w = 0.5 ** (max(0, (oggi - r["d"]).days) / EMIVITA_ARB)
            w_tot += w; s_tot += w * r["k"] / mk
        fattore = (s_tot + K_ARB) / (w_tot + K_ARB)
        # numeri di carriera e confronto con la media dei campionati che ha arbitrato
        tot = defaultdict(lambda: [0.0, 0, 0.0])           # somma, partite, somma delle medie di riferimento
        for r in lst:
            for k in ("k", "ros", "rig", "fal", "gol"):
                mk = media(r, k)
                if r[k] is not None and mk is not None:
                    t = tot[k]; t[0] += r[k]; t[1] += 1; t[2] += mk

        def am(k, cifre=2):
            t = tot[k]
            return [round(t[0] / t[1], cifre), round(t[2] / t[1], cifre), t[1]] if t[1] >= 10 else None   # sotto 10 partite la media non dice niente
        stag = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
        for r in lst:
            s = stag[_stagione(r["d"])]
            s["n"][1] += 1
            for k in ("k", "ros", "rig", "fal"):
                if r[k] is not None:
                    s[k][0] += r[k]; s[k][1] += 1
        tab = []
        for a in sorted(stag, reverse=True)[:STAGIONI_TABELLA]:
            s = stag[a]
            tab.append([f"{a}/{(a + 1) % 100:02d}", s["n"][1]] +
                       [round(s[k][0] / s[k][1], 2) if s[k][1] else None for k in ("k", "ros", "rig", "fal")])
        leghe = Counter(r["l"] for r in lst)
        corr = sum(1 for r in lst if _stagione(r["d"]) == sorgenti.anno_stagione(oggi))
        n_gol = [r for r in lst if r["gol"] is not None]
        AR[nome] = {
            "n": len(lst), "da": lst[0]["d"].isoformat(), "a": lst[-1]["d"].isoformat(), "corr": corr,
            "f": round(fattore, 3), "pf": round(w_tot, 1),
            "k": am("k"), "ros": am("ros", 3), "rig": am("rig", 3), "fal": am("fal", 1), "gol": am("gol"),
            "o25": round(100 * sum(1 for r in n_gol if r["gol"] > 2) / len(n_gol), 1) if n_gol else None,
            "v1": round(100 * sum(1 for r in lst if r["casa"]) / len(lst), 1),
            "leghe": [[l, c] for l, c in leghe.most_common(4)], "st": tab,
        }
    log(f"    arbitri con scheda: {len(AR)} · designati nella finestra: "
        f"{sum(1 for f in finestra if (f['t'][:10], f['c'], f['o']) in designati)} su {len(finestra)}"
        + ("" if chiave else " (senza chiave football-data.org: solo Inghilterra e Scozia)"))
    return AR, designati
