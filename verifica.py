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
                                  "tot_lega": Lc + Lt, "rho": rho, "gc": m["gc"], "go": m["go"],
                                  "casa": m["casa"], "ospite": m["ospite"]})
    return righe


def smorza(lc, lo, tot_lega, gamma):
    """
    Riporta il totale gol atteso verso la media del campionato (gamma < 1),
    lasciando invariato il rapporto tra le due squadre (quindi chi è favorito).
    """
    tot = lc + lo
    nuovo = tot_lega * (tot / tot_lega) ** gamma
    return lc * nuovo / tot, lo * nuovo / tot


def con_probabilita(righe, gamma, con_esatti=False):
    out = []
    for r in righe:
        lc, lo = smorza(r["lc"], r["lo"], r["tot_lega"], gamma)
        P = matrice(lc, lo, r["rho"])
        e = esiti(r["gc"], r["go"])
        if con_esatti:
            celle = sorted(((P[i][j], i, j) for i in range(len(P)) for j in range(len(P))), reverse=True)
            e["_top1"] = (r["gc"], r["go"]) == celle[0][1:]
            e["_top3"] = (r["gc"], r["go"]) in [c[1:] for c in celle[:3]]
        out.append((r["lega"], r["cod"], probabilita(P), e))
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
    righe = con_probabilita(grezze, gamma, con_esatti=True)
    cal = tabelle_calibrazione(righe)
    esatti1 = sum(e["_top1"] for _, _, _, e in righe) / len(righe)
    esatti3 = sum(e["_top3"] for _, _, _, e in righe) / len(righe)
    out = {"gamma": gamma, "n": cal["n"], "acc1x2": cal["acc1x2"], "brier": cal["brier"],
           "stagioni": [f"20{c[:2]}/{c[2:]}" for c in cal["stagioni"]],
           "tab": cal["tab"],
           "curve": {k: mappa_isotonica(cal["tab"][k]) for k in ("O25", "GG")},
           "esatto1": round(esatti1, 4), "esatto3": round(esatti3, 4)}
    out.update(deriva(partite, leghe))
    out["_grezze"] = grezze          # servono a prevedibilita(); build.py le toglie prima di pubblicare
    return out


# ------------------------------------------------------------------
# PREVEDIBILITÀ: chi rispetta di più i pronostici (stesso cervello dell'app)
# ------------------------------------------------------------------

def calib(curva, p):
    """Copia esatta di calib() dell'app: probabilità del modello → frequenza reale."""
    c = curva
    if not c:
        return p
    cl = lambda x: min(max(x, .01), .99)
    if p <= c[0][0]:
        return cl(p + (c[0][1] - c[0][0]))
    for i in range(1, len(c)):
        if p <= c[i][0]:
            a, b = c[i - 1], c[i]
            t = (p - a[0]) / (b[0] - a[0])
            return a[1] + t * (b[1] - a[1])
    z = c[-1]
    return cl(p + (z[1] - z[0]))


def _classe(i, j):
    return (0 if i > j else (1 if i == j else 2)) * 4 + (2 if i + j > 2 else 0) + (1 if i and j else 0)


CLASSI = [[_classe(i, j) for j in range(11)] for i in range(11)]


def allinea(P0, tO, tG):
    """
    Come allinea() dell'app (raking su 1X2, Over 2.5, Gol/Gol). Le celle con lo stesso esito, lo stesso
    Over/Under e lo stesso Gol/No Gol ricevono sempre lo stesso fattore: basta lavorare sui 12 totali.
    """
    T = [0.0] * 12
    for i in range(11):
        for j in range(11):
            T[CLASSI[i][j]] += P0[i][j]
    f = [1.0] * 12
    tot = sum(T)
    t1 = [sum(T[k] for k in range(12) if k // 4 == e) for e in range(3)]
    obiettivi = [(lambda k: k // 4, t1), (lambda k: (k >> 1) & 1, [tot * (1 - tO), tot * tO]),
                 (lambda k: k & 1, [tot * (1 - tG), tot * tG])]
    for _ in range(40):
        err = 0.0
        for gruppo, tg in obiettivi:
            sm = [0.0] * len(tg)
            for k in range(12):
                sm[gruppo(k)] += T[k] * f[k]
            fc = [tg[g] / v if v > 1e-12 else 1.0 for g, v in enumerate(sm)]
            err = max([err] + [abs(x - 1) for x in fc])
            for k in range(12):
                f[k] *= fc[gruppo(k)]
        if err < 1e-7:
            break
    return [[P0[i][j] * f[CLASSI[i][j]] for j in range(11)] for i in range(11)]


def prevedibilita(grezze, gamma, curve, squadre_ora, stagioni_squadre=3, minimo=30):
    """
    Su ogni partita della verifica (pronostico fatto con le sole partite precedenti) si guarda se il
    modello ci ha preso: esito 1X2 più probabile, Over/Under 2.5, Gol/No Gol, risultato esatto tra i primi 3,
    e quanti gol ha fatto e subito ogni squadra rispetto a quelli attesi. Campionati: tutte le stagioni
    verificate. Squadre: ultime `stagioni_squadre` stagioni, solo quelle che giocano ora nei campionati coperti.
    """
    codici = sorted({r["cod"] for r in grezze})
    recenti = set(codici[-stagioni_squadre:])
    acc_l = defaultdict(lambda: defaultdict(float))
    acc_s = defaultdict(lambda: defaultdict(float))
    for r in grezze:
        lc, lo = smorza(r["lc"], r["lo"], r["tot_lega"], gamma)
        P0 = matrice(lc, lo, r["rho"])
        p = probabilita(P0)
        o25 = calib(curve.get("O25"), p["O25"])
        gg = calib(curve.get("GG"), p["GG"])
        P = allinea(P0, o25, gg)
        mc = sum(i * P[i][j] for i in range(11) for j in range(11))
        mo = sum(j * P[i][j] for i in range(11) for j in range(11))
        celle = sorted(((P[i][j], i, j) for i in range(11) for j in range(11)), reverse=True)[:3]
        gc, go = r["gc"], r["go"]
        esito = max(("1", "X", "2"), key=lambda k: p[k])
        vero = "1" if gc > go else ("X" if gc == go else "2")
        h = {"esito": esito == vero, "ou": (o25 > .5) == (gc + go > 2), "gg": (gg > .5) == (gc > 0 and go > 0),
             "ex": any((i, j) == (gc, go) for _, i, j in celle)}
        a = acc_l[r["lega"]]
        a["n"] += 1
        for k, v in h.items():
            a[k] += v
        a["gol_att"] += mc + mo; a["gol"] += gc + go
        if r["cod"] in recenti:
            for t, gf, gs, af, as_ in ((r["casa"], gc, go, mc, mo), (r["ospite"], go, gc, mo, mc)):
                if squadre_ora.get(t) != r["lega"]:
                    continue
                b = acc_s[t]
                b["n"] += 1
                for k, v in h.items():
                    b[k] += v
                b["gf"] += gf; b["gs"] += gs; b["gf_att"] += af; b["gs_att"] += as_
    pc = lambda a, k: round(100 * a[k] / a["n"], 1)
    leghe = {l: {"n": int(a["n"]), "esito": pc(a, "esito"), "ou": pc(a, "ou"), "gg": pc(a, "gg"), "ex": pc(a, "ex"),
                 "gol": round(a["gol"] / a["n"], 2), "gol_att": round(a["gol_att"] / a["n"], 2)}
             for l, a in acc_l.items()}
    squadre = {t: {"l": squadre_ora[t], "n": int(b["n"]), "esito": pc(b, "esito"), "ou": pc(b, "ou"), "gg": pc(b, "gg"),
                   "ex": pc(b, "ex"), "gf": round(b["gf"] / b["n"], 2), "gs": round(b["gs"] / b["n"], 2),
                   "dgf": round((b["gf"] - b["gf_att"]) / b["n"], 2), "dgs": round((b["gs"] - b["gs_att"]) / b["n"], 2)}
               for t, b in acc_s.items() if b["n"] >= minimo}
    return {"leghe": leghe, "squadre": squadre,
            "stag_l": [f"20{c[:2]}/{c[2:]}" for c in codici], "stag_s": [f"20{c[:2]}/{c[2:]}" for c in sorted(recenti)]}


def numeri_campionati(partite, cod_corr, n_prec=3):
    """Gol, Over, Gol/Gol, 0-0, vittorie in casa: stagione in corso e ultime n_prec stagioni concluse."""
    codici = sorted({m["stagione"] for m in partite})
    prec = set(c for c in codici if c != cod_corr)
    prec = set(sorted(prec)[-n_prec:])
    acc = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for m in partite:
        per = "ora" if m["stagione"] == cod_corr else ("prima" if m["stagione"] in prec else None)
        if not per:
            continue
        a = acc[m["lega"]][per]
        t = m["gc"] + m["go"]
        a["n"] += 1; a["gol"] += t; a["o15"] += t > 1; a["o25"] += t > 2; a["o35"] += t > 3
        a["gg"] += m["gc"] > 0 and m["go"] > 0; a["zero"] += t == 0; a["casa"] += m["gc"] > m["go"]
        a["x"] += m["gc"] == m["go"]
    out = {}
    for l, per in acc.items():
        out[l] = {}
        for k, a in per.items():
            n = a["n"]
            out[l][k] = {"n": int(n), "gol": round(a["gol"] / n, 2), "o15": round(100 * a["o15"] / n, 1),
                         "o25": round(100 * a["o25"] / n, 1), "o35": round(100 * a["o35"] / n, 1),
                         "gg": round(100 * a["gg"] / n, 1), "zero": round(100 * a["zero"] / n, 1),
                         "casa": round(100 * a["casa"] / n, 1), "x": round(100 * a["x"] / n, 1)}
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
