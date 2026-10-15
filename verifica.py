# -*- coding: utf-8 -*-
"""
Oracle Engine — verifica del modello sul passato e misura dell'incertezza.

1. VERIFICA STORICA: per ogni stagione (dalla terza in poi) e per ogni quarto di
   stagione, i rating vengono calcolati SOLO con le partite giocate prima; il
   modello fa il pronostico e lo si confronta con il risultato vero. Ne esce la
   tabella "quando il modello dice 70%, quante volte è uscito davvero".
2. DERIVA: quanto cambia la forza vera di una squadra da una stagione all'altra
   (al netto del rumore delle singole partite). È l'incertezza che resta quando
   la stagione è appena iniziata o l'allenatore è nuovo.
"""

import datetime
import math
from collections import defaultdict

import engine

MERCATI = ("1", "X", "2", "O25", "U25", "GG", "NG")
K_BASE = 6.0
PRIOR_NUOVA = (0.85, 1.15)        # squadra senza storia nel campionato (di solito neopromossa)


def matrice(lc, lo, rho, n=11):
    def pmf(k, l):
        return math.exp(-l) * l ** k / math.factorial(k)
    pc = [pmf(i, lc) for i in range(n)]
    po = [pmf(j, lo) for j in range(n)]
    P = [[pc[i] * po[j] for j in range(n)] for i in range(n)]
    P[0][0] *= max(1 - lc * lo * rho, .05)
    P[0][1] *= max(1 + lc * rho, .05)
    P[1][0] *= max(1 + lo * rho, .05)
    P[1][1] *= max(1 - rho, .05)
    t = sum(map(sum, P))
    return [[v / t for v in r] for r in P]


def probabilita(P):
    p1 = px = p2 = o25 = gg = 0.0
    n = len(P)
    for i in range(n):
        for j in range(n):
            v = P[i][j]
            if i > j:
                p1 += v
            elif i == j:
                px += v
            else:
                p2 += v
            if i + j > 2:
                o25 += v
            if i and j:
                gg += v
    return {"1": p1, "X": px, "2": p2, "O25": o25, "U25": 1 - o25, "GG": gg, "NG": 1 - gg}


def esiti(gc, go):
    return {"1": gc > go, "X": gc == go, "2": gc < go, "O25": gc + go > 2, "U25": gc + go <= 2,
            "GG": gc > 0 and go > 0, "NG": not (gc > 0 and go > 0)}


def _rating(storia, rif):
    """Medie di lega e rating attacco/difesa con le sole partite prima di `rif`."""
    s = defaultdict(lambda: [0.0, 0.0, 0.0])      # team -> [w, att, dif]
    wl = gc = go = 0.0
    for m in storia:
        w = engine.DECADIMENTO ** max(0.0, (rif - m["data"]).days / 365.25)
        wl += w; gc += w * m["gc"]; go += w * m["go"]
    if not wl:
        return None
    Lc, Lt = gc / wl, go / wl
    for m in storia:
        w = engine.DECADIMENTO ** max(0.0, (rif - m["data"]).days / 365.25)
        a = s[m["casa"]]; a[0] += w; a[1] += w * m["gc"] / Lc; a[2] += w * m["go"] / Lt
        b = s[m["ospite"]]; b[0] += w; b[1] += w * m["go"] / Lt; b[2] += w * m["gc"] / Lc
    rat = {t: ((v[1] + K_BASE) / (v[0] + K_BASE), (v[2] + K_BASE) / (v[0] + K_BASE)) for t, v in s.items()}
    return Lc, Lt, rat


def verifica_storica(partite, leghe, stagioni_min=2, blocchi=4):
    """Pronostici 'come se fosse quel giorno' per tutte le partite delle stagioni verificabili."""
    per_lega = defaultdict(list)
    for m in partite:
        per_lega[m["lega"]].append(m)
    righe = []
    for lega, lst in per_lega.items():
        lst.sort(key=lambda m: m["data"])
        stagioni = sorted({m["stagione"] for m in lst})
        rho = leghe.get(lega, {}).get("rho_emp", -0.05)
        for idx, cod in enumerate(stagioni):
            if idx < stagioni_min:
                continue
            stag = [m for m in lst if m["stagione"] == cod]
            passo = max(1, math.ceil(len(stag) / blocchi))
            for b in range(0, len(stag), passo):
                blocco = stag[b:b + passo]
                rif = blocco[0]["data"]
                r = _rating([m for m in lst if m["data"] < rif], rif)
                if not r:
                    continue
                Lc, Lt, rat = r
                for m in blocco:
                    ac, dc = rat.get(m["casa"], PRIOR_NUOVA)
                    ao, do = rat.get(m["ospite"], PRIOR_NUOVA)
                    righe.append({"lega": lega, "cod": cod, "lc": Lc * ac * do, "lo": Lt * ao * dc,
                                  "tot_lega": Lc + Lt, "rho": rho, "gc": m["gc"], "go": m["go"]})
    return righe


def smorza(lc, lo, tot_lega, gamma):
    """
    Riporta il totale gol atteso verso la media del campionato (gamma < 1),
    lasciando invariato il rapporto tra le due squadre (quindi chi è favorito).
    """
    tot = lc + lo
    nuovo = tot_lega * (tot / tot_lega) ** gamma
    return lc * nuovo / tot, lo * nuovo / tot


def con_probabilita(righe, gamma):
    out = []
    for r in righe:
        lc, lo = smorza(r["lc"], r["lo"], r["tot_lega"], gamma)
        out.append((r["lega"], r["cod"], probabilita(matrice(lc, lo, r["rho"])), esiti(r["gc"], r["go"])))
    return out


def stima_gamma(righe):
    """Il valore di smorzamento che rende i pronostici più fedeli ai risultati reali (log-loss)."""
    def perdita(g):
        tot = 0.0
        for _, _, p, e in con_probabilita(righe, g):
            for k in ("1", "X", "2", "O25", "GG"):
                q = min(max(p[k], 1e-6), 1 - 1e-6)
                tot -= math.log(q if e[k] else 1 - q)
        return tot
    griglia = {g: perdita(g) for g in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)}
    g0 = min(griglia, key=griglia.get)
    for g in (g0 - 0.05, g0 + 0.05):
        if 0.3 <= g <= 1.0:
            griglia[round(g, 2)] = perdita(g)
    return min(griglia, key=griglia.get), griglia


def tabelle_calibrazione(righe, ampiezza=0.05, minimo=40):
    """Per ogni mercato e per 'uscita principale': fascia di probabilità → quante volte è uscito."""
    acc = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    giuste_1x2 = 0
    brier = 0.0
    for _, _, p, e in righe:
        for k in MERCATI:
            f = min(int(p[k] / ampiezza), int(1 / ampiezza) - 1)
            v = acc[k][f]; v[0] += 1; v[1] += e[k]
        top = max(MERCATI, key=lambda k: p[k])
        f = min(int(p[top] / ampiezza), int(1 / ampiezza) - 1)
        v = acc["best"][f]; v[0] += 1; v[1] += e[top]
        fav = max(("1", "X", "2"), key=lambda k: p[k])
        giuste_1x2 += e[fav]
        brier += sum((p[k] - e[k]) ** 2 for k in ("1", "X", "2"))
    tab = {}
    for k, fasce in acc.items():
        out = []
        for f in sorted(fasce):
            n, h = fasce[f]
            if n >= minimo:
                out.append([round(f * ampiezza, 2), n, round(h / n, 4)])
        tab[k] = out
    n = len(righe)
    return {"tab": tab, "n": n, "acc1x2": round(giuste_1x2 / n, 4) if n else None,
            "brier": round(brier / n, 4) if n else None,
            "stagioni": sorted({c for _, c, _, _ in righe})}


def mappa_isotonica(fasce, ampiezza=0.05):
    """
    Trasforma la tabella (fascia, partite, uscito) in una curva crescente
    "probabilità del modello → frequenza reale" (regressione isotonica pesata).
    """
    blocchi = [[lo + ampiezza / 2, n, fr * n] for lo, n, fr in fasce]   # centro, peso, successi
    i = 0
    while i < len(blocchi) - 1:
        a, b = blocchi[i], blocchi[i + 1]
        if a[2] / a[1] > b[2] / b[1]:
            peso = a[1] + b[1]
            blocchi[i] = [(a[0] * a[1] + b[0] * b[1]) / peso, peso, a[2] + b[2]]
            del blocchi[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    return [[round(c, 4), round(s / n, 4), n] for c, n, s in blocchi]


def riassunto_verifica(partite, leghe):
    """Tutto quello che serve all'app: smorzamento, curve di calibrazione, tabelle, deriva."""
    grezze = verifica_storica(partite, leghe)
    gamma, _ = stima_gamma(grezze)
    righe = con_probabilita(grezze, gamma)
    cal = tabelle_calibrazione(righe)
    out = {"gamma": gamma, "n": cal["n"], "acc1x2": cal["acc1x2"], "brier": cal["brier"],
           "stagioni": [f"20{c[:2]}/{c[2:]}" for c in cal["stagioni"]],
           "tab": cal["tab"],
           "curve": {k: mappa_isotonica(cal["tab"][k]) for k in ("O25", "GG")}}
    out.update(deriva(partite, leghe))
    return out


def deriva(partite, leghe):
    """
    Variazione della forza vera di una squadra tra due stagioni (scala log),
    tolto il rumore dovuto al numero di partite. Ritorna tau e il rumore per partita.
    """
    st = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])   # (team, lega, stagione) -> n, Σatt, Σatt², Σdif, Σdif²
    for m in partite:
        L = leghe[m["lega"]]
        for t, f, s, mf, ms in ((m["casa"], m["gc"], m["go"], L["gol_casa"], L["gol_trasferta"]),
                                (m["ospite"], m["go"], m["gc"], L["gol_trasferta"], L["gol_casa"])):
            v = st[(t, m["lega"], m["stagione"])]
            a, d = f / mf, s / ms
            v[0] += 1; v[1] += a; v[2] += a * a; v[3] += d; v[4] += d * d
    # rumore per partita (coefficiente di variazione del rapporto gol/media)
    cv = {}
    for i, k in ((1, "att"), (3, "dif")):
        num = den = 0.0
        for v in st.values():
            if v[0] >= 10:
                mu = v[i] / v[0]
                var = max(v[i + 1] / v[0] - mu * mu, 0)
                if mu > 0:
                    num += v[0] * var / (mu * mu)
                    den += v[0]
        cv[k] = math.sqrt(num / den)
    codici = engine._codici_stagioni()
    pos = {c: i for i, c in enumerate(codici)}
    tau = {}
    for i, k in ((1, "att"), (3, "dif")):
        diffs, rumore = [], []
        for (t, l, c), v in st.items():
            if v[0] < 15 or pos.get(c, 0) == 0:
                continue
            prev = st.get((t, l, codici[pos[c] - 1]))
            if not prev or prev[0] < 15:
                continue
            m1, m0 = v[i] / v[0], prev[i] / prev[0]
            if m1 <= 0 or m0 <= 0:
                continue
            diffs.append(math.log(m1) - math.log(m0))
            rumore.append(cv[k] ** 2 / v[0] + cv[k] ** 2 / prev[0])
        mu = sum(diffs) / len(diffs)
        var = sum((x - mu) ** 2 for x in diffs) / (len(diffs) - 1)
        tau[k] = math.sqrt(max(var - sum(rumore) / len(rumore), 0.0005))
    return {"tau_att": round(tau["att"], 4), "tau_dif": round(tau["dif"], 4),
            "cv_att": round(cv["att"], 4), "cv_dif": round(cv["dif"], 4)}
