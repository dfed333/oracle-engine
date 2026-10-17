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
           "curve": {k: mappa_isotonica(cal["tab"][k]) for k in ("O25", "GG", "1", "X", "2")},
           "esatto1": round(esatti1, 4), "esatto3": round(esatti3, 4)}
    out.update(deriva(partite, leghe))
    return out


# ------------------------------------------------------------------
# FUNZIONI COMUNI CON L'APP (stesso cervello): correzione, allineamento, mercati delle combinazioni
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


def p1x2(curve, p):
    """1, X, 2 corretti con la verifica sul passato e riportati a somma 1 (copia di p1x2() dell'app)."""
    v = [calib(curve.get(k), p[k]) for k in ("1", "X", "2")]
    t = sum(v)
    return [x / t for x in v] if t > 0 else [p["1"], p["X"], p["2"]]


def _classe(i, j):
    return (0 if i > j else (1 if i == j else 2)) * 4 + (2 if i + j > 2 else 0) + (1 if i and j else 0)


CLASSI = [[_classe(i, j) for j in range(11)] for i in range(11)]


def allinea(P0, t1x2, tO, tG):
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
    t1 = [tot * x for x in t1x2]
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


SOGLIE_SICURO = (0.55, 0.60, 0.65, 0.70)
MG_TOT = [(1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (2, 3), (2, 4), (2, 5), (2, 6), (3, 4), (3, 5), (3, 6), (4, 5), (4, 6)]
MG_SQ = [(0, 1), (1, 2), (1, 3), (2, 3), (1, 4), (2, 4)]


def _mercati_gen():
    m = {"1": lambda i, j: i > j, "X": lambda i, j: i == j, "2": lambda i, j: i < j,
         "1X": lambda i, j: i >= j, "X2": lambda i, j: i <= j, "12": lambda i, j: i != j,
         "GG": lambda i, j: i > 0 and j > 0, "NG": lambda i, j: not (i > 0 and j > 0)}
    for L in (0.5, 1.5, 2.5, 3.5, 4.5):
        m[f"O{L}"] = (lambda L: lambda i, j: i + j > L)(L)
        m[f"U{L}"] = (lambda L: lambda i, j: i + j < L)(L)
    for a, b in MG_TOT:
        m[f"MG{a}-{b}"] = (lambda a, b: lambda i, j: a <= i + j <= b)(a, b)
    for a, b in MG_SQ:
        m[f"MGC{a}-{b}"] = (lambda a, b: lambda i, j: a <= i <= b)(a, b)
        m[f"MGO{a}-{b}"] = (lambda a, b: lambda i, j: a <= j <= b)(a, b)
    return m


MERCATI_GEN = _mercati_gen()


def probabilita_mercati(P):
    """Probabilità di ogni mercato delle combinazioni dalla matrice (allineata) dei risultati."""
    tot, casa, osp = [0.0] * 21, [0.0] * 11, [0.0] * 11
    p1 = px = p2 = gg = 0.0
    for i in range(11):
        for j in range(11):
            v = P[i][j]
            tot[i + j] += v; casa[i] += v; osp[j] += v
            if i > j:
                p1 += v
            elif i == j:
                px += v
            else:
                p2 += v
            if i and j:
                gg += v
    out = {"1": p1, "X": px, "2": p2, "1X": p1 + px, "X2": px + p2, "12": p1 + p2, "GG": gg, "NG": 1 - gg}
    s = sum(tot)
    for L in (0.5, 1.5, 2.5, 3.5, 4.5):
        u = sum(tot[: int(L) + 1])
        out[f"U{L}"] = u; out[f"O{L}"] = s - u
    for a, b in MG_TOT:
        out[f"MG{a}-{b}"] = sum(tot[a:b + 1])
    for a, b in MG_SQ:
        out[f"MGC{a}-{b}"] = sum(casa[a:b + 1]); out[f"MGO{a}-{b}"] = sum(osp[a:b + 1])
    return out


def numeri_campionati(partite, oggi):
    """
    Gol, Over, Gol/Gol, 0-0, vittorie in casa e i risultati esatti più frequenti di ogni campionato
    su tre periodi: ultimi 10 anni (tutto l'archivio), ultimi 3 anni, ultimo anno (365 giorni).
    """
    periodi = {"10": None, "3": oggi - datetime.timedelta(days=3 * 365), "1": oggi - datetime.timedelta(days=365)}
    acc = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    ris = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for m in partite:
        t = m["gc"] + m["go"]
        for per, da in periodi.items():
            if da and m["data"] < da:
                continue
            a = acc[m["lega"]][per]
            a["n"] += 1; a["gol"] += t; a["o15"] += t > 1; a["o25"] += t > 2; a["o35"] += t > 3
            a["gg"] += m["gc"] > 0 and m["go"] > 0; a["zero"] += t == 0; a["casa"] += m["gc"] > m["go"]
            a["x"] += m["gc"] == m["go"]
            ris[m["lega"]][per][f"{m['gc']}-{m['go']}"] += 1
    out = {}
    for l, per in acc.items():
        out[l] = {}
        for k, a in per.items():
            n = a["n"]
            top = sorted(ris[l][k].items(), key=lambda x: -x[1])[:8]
            out[l][k] = {"n": int(n), "gol": round(a["gol"] / n, 2), "o15": round(100 * a["o15"] / n, 1),
                         "o25": round(100 * a["o25"] / n, 1), "o35": round(100 * a["o35"] / n, 1),
                         "gg": round(100 * a["gg"] / n, 1), "zero": round(100 * a["zero"] / n, 1),
                         "casa": round(100 * a["casa"] / n, 1), "x": round(100 * a["x"] / n, 1),
                         "ris": [[r, round(100 * c / n, 1)] for r, c in top]}
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


# ------------------------------------------------------------------
# VERIFICA DEL NUOVO MOTORE (attese del mercato) — è quella che l'app usa
# ------------------------------------------------------------------

TETTI_GIOCABILI = (0.80, 0.75, 0.70, 0.65)     # combinazioni: tetto alla probabilità di ogni scelta
ESCLUSE_COMB = {"O0.5", "U4.5", "MG1-5", "MG1-6", "MG2-6"}   # troppo scontate: come ESCLUSE_COMB dell'app


def _curva(punti, ampiezza=0.05, minimo=40):
    acc = defaultdict(lambda: [0, 0])
    for p, y in punti:
        f = min(int(p / ampiezza), int(1 / ampiezza) - 1)
        acc[f][0] += 1; acc[f][1] += y
    fasce = [[round(f * ampiezza, 2), n, h / n] for f, (n, h) in sorted(acc.items()) if n >= minimo]
    return mappa_isotonica(fasce, ampiezza)


def _grezze_da(P):
    p = probabilita(P)
    return p["1"], p["X"], p["2"], p["O25"], p["GG"]


def _curve(righe):
    """righe: (p1, px, p2, o25, gg, gc, go) → curve 'probabilità → frequenza reale' per 1, X, 2, O25, GG."""
    return {"1": _curva([(r[0], r[5] > r[6]) for r in righe]), "X": _curva([(r[1], r[5] == r[6]) for r in righe]),
            "2": _curva([(r[2], r[5] < r[6]) for r in righe]), "O25": _curva([(r[3], r[5] + r[6] > 2) for r in righe]),
            "GG": _curva([(r[4], r[5] > 0 and r[6] > 0) for r in righe])}


def finali(P0, grezze, curve):
    """Matrice finale: la stessa operazione dell'app (1X2 corretto e riportato a 100, Over 2.5 e Gol/Gol corretti)."""
    q1, qx, q2 = p1x2(curve, {"1": grezze[0], "X": grezze[1], "2": grezze[2]})
    return allinea(P0, (q1, qx, q2), calib(curve.get("O25"), grezze[3]), calib(curve.get("GG"), grezze[4]))


def verifica_mercato(partite, leghe, mostrate, squadre_ora, stagioni_squadre=3, minimo_sq=30):
    """
    Verifica del motore dell'app su tutte le partite con quote dei campionati (anche quelli solo-storico):
      - fonte "q": le quote della partita (raccolte prima della partita), tolto il margine → gol attesi → matrice;
      - fonte "r": la forza dalle quote delle partite PRECEDENTI (per le partite che le quote non le hanno ancora).
    Per ognuna: curve di correzione (quando dice 70%, quante volte esce davvero), tabelle, risultati esatti.
    Con la fonte "q" si calcola anche il Confronto (prevedibilità di campionati e squadre, combinazioni).
    Ritorna (V, PV).
    """
    from mercato import matrice as mat, rho_di
    prime = {}
    for m in partite:
        k = m["lega"]
        if k not in prime or m["stagione"] < prime[k]:
            prime[k] = m["stagione"]
    rq, rr = [], []
    for m in partite:
        if not m.get("lk"):
            continue
        rho = rho_di(leghe, m["lega"])
        q = m["q"]
        gg = probabilita(mat(m["lk"][0], m["lk"][1], rho))["GG"]
        rq.append((q[0], q[1], q[2], q[3], gg, m["gc"], m["go"]))
        if m.get("mr") and m["stagione"] != prime[m["lega"]]:
            rr.append(_grezze_da(mat(m["mr"][0], m["mr"][1], rho)) + (m["gc"], m["go"]))
    cq, cr = _curve(rq), _curve(rr)

    def riassunto(righe, curve):
        """Numeri della fonte con le probabilità corrette (quelle che l'app mostra)."""
        acc = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        fav = ou = ggh = 0
        for r in righe:
            q1, qx, q2 = p1x2(curve, {"1": r[0], "X": r[1], "2": r[2]})
            o, g = calib(curve["O25"], r[3]), calib(curve["GG"], r[4])
            e = esiti(r[5], r[6])
            pp = {"1": q1, "X": qx, "2": q2, "O25": o, "U25": 1 - o, "GG": g, "NG": 1 - g}
            for k, v in pp.items():
                f = min(int(v / .05), 19); a = acc[k][f]; a[0] += 1; a[1] += e[k]
            fav += e[max(("1", "X", "2"), key=lambda k: pp[k])]
            ou += (o > .5) == e["O25"]; ggh += (g > .5) == e["GG"]
        n = len(righe)
        tab = {k: [[round(f * .05, 2), v[0], round(v[1] / v[0], 4)] for f, v in sorted(fa.items()) if v[0] >= 40]
               for k, fa in acc.items()}
        return {"n": n, "acc1x2": round(fav / n, 4), "ou": round(ou / n, 4), "gg": round(ggh / n, 4), "curve": curve, "tab": tab}

    V = {"q": riassunto(rq, cq), "r": riassunto(rr, cr)}

    # ---- passata finale con le matrici dell'app (fonte q): risultati esatti + Confronto ----
    codici = sorted({m["stagione"] for m in partite if m.get("lk")})
    recenti = set(codici[-stagioni_squadre:])
    acc_l = defaultdict(lambda: defaultdict(float))
    acc_s = defaultdict(lambda: defaultdict(float))
    acc_m = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    ver_scelte = {c: defaultdict(lambda: [0, 0, 0.0]) for c in TETTI_GIOCABILI}
    ver_esatti = {K: defaultdict(lambda: [0, 0, 0.0]) for K in (3, 4, 5)}
    ex1 = ex3 = cop1 = cop3 = 0.0
    n_tot = 0
    stag_lega = defaultdict(set)
    for m in partite:
        if not m.get("lk"):
            continue
        rho = rho_di(leghe, m["lega"])
        P0 = mat(m["lk"][0], m["lk"][1], rho)
        gg0 = probabilita(P0)["GG"]
        P = finali(P0, (m["q"][0], m["q"][1], m["q"][2], m["q"][3], gg0), cq)
        gc, go = m["gc"], m["go"]
        celle = sorted(((P[i][j], i, j) for i in range(11) for j in range(11)), reverse=True)
        n_tot += 1
        ex1 += (celle[0][1], celle[0][2]) == (gc, go)
        ex3 += any((i, j) == (gc, go) for _, i, j in celle[:3])
        cop1 += celle[0][0]; cop3 += sum(c[0] for c in celle[:3])
        if m["lega"] not in mostrate:
            continue
        stag_lega[m["lega"]].add(m["stagione"])
        pm = probabilita_mercati(P)
        q1, qx, q2, o25, gg = pm["1"], pm["X"], pm["2"], pm["O2.5"], pm["GG"]
        mc = sum(i * P[i][j] for i in range(11) for j in range(11))
        mo = sum(j * P[i][j] for i in range(11) for j in range(11))
        pc_ = {"1": q1, "X": qx, "2": q2}
        esito = max(("1", "X", "2"), key=lambda k: pc_[k])
        vero = "1" if gc > go else ("X" if gc == go else "2")
        h = {"esito": esito == vero, "ou": (o25 > .5) == (gc + go > 2), "gg": (gg > .5) == (gc > 0 and go > 0),
             "ex": any((i, j) == (gc, go) for _, i, j in celle[:3])}
        mk = acc_m[m["lega"]]
        for chiave, prob, uscito in (("1", q1, gc > go), ("X", qx, gc == go), ("2", q2, gc < go),
                                     ("O25", o25, gc + go > 2), ("U25", 1 - o25, gc + go <= 2),
                                     ("GG", gg, gc > 0 and go > 0), ("NG", 1 - gg, not (gc > 0 and go > 0))):
            for soglia in SOGLIE_SICURO:
                if prob >= soglia:
                    v = mk[(chiave, soglia)]; v[0] += 1; v[1] += uscito
        mk[("tot", 0)][0] += 1
        for cap in TETTI_GIOCABILI:
            k = max((k for k in pm if pm[k] <= cap and k not in ESCLUSE_COMB), key=lambda k: pm[k])
            v = ver_scelte[cap][int(min(pm[k], .999) / .05)]; v[0] += 1; v[1] += MERCATI_GEN[k](gc, go); v[2] += pm[k]
        for K in (3, 4, 5):
            cop = sum(c[0] for c in celle[:K])
            v = ver_esatti[K][int(min(cop, .999) / .05)]; v[0] += 1
            v[1] += any((i, j) == (gc, go) for _, i, j in celle[:K]); v[2] += cop
        a = acc_l[m["lega"]]
        a["n"] += 1
        for k, v in h.items():
            a[k] += v
        a["gol_att"] += mc + mo; a["gol"] += gc + go
        if m["stagione"] in recenti:
            for t, gf, gs, af, as_ in ((m["casa"], gc, go, mc, mo), (m["ospite"], go, gc, mo, mc)):
                if squadre_ora.get(t) != m["lega"]:
                    continue
                b = acc_s[t]
                b["n"] += 1
                for k, v in h.items():
                    b[k] += v
                b["gf"] += gf; b["gs"] += gs; b["gf_att"] += af; b["gs_att"] += as_
    V["q"].update(esatto1=round(ex1 / n_tot, 4), esatto3=round(ex3 / n_tot, 4),
                  cop1=round(cop1 / n_tot, 4), cop3=round(cop3 / n_tot, 4))
    V["stagioni"] = [f"20{c[:2]}/{c[2:]}" for c in codici]
    pc = lambda a, k: round(100 * a[k] / a["n"], 1)
    leghe_pv = {l: {"n": int(a["n"]), "st": len(stag_lega[l]), "esito": pc(a, "esito"), "ou": pc(a, "ou"), "gg": pc(a, "gg"),
                    "ex": pc(a, "ex"), "gol": round(a["gol"] / a["n"], 2), "gol_att": round(a["gol_att"] / a["n"], 2)}
                for l, a in acc_l.items()}
    squadre = {t: {"l": squadre_ora[t], "n": int(b["n"]), "esito": pc(b, "esito"), "ou": pc(b, "ou"), "gg": pc(b, "gg"),
                   "ex": pc(b, "ex"), "gf": round(b["gf"] / b["n"], 2), "gs": round(b["gs"] / b["n"], 2),
                   "dgf": round((b["gf"] - b["gf_att"]) / b["n"], 2), "dgs": round((b["gs"] - b["gs_att"]) / b["n"], 2)}
               for t, b in acc_s.items() if b["n"] >= minimo_sq}
    mercati = {}
    for l, mk in acc_m.items():
        tot = mk[("tot", 0)][0]
        mercati[l] = {f"{k}|{int(sg * 100)}": [v[0], round(100 * v[1] / v[0], 1), round(100 * v[0] / tot, 1)]
                      for (k, sg), v in mk.items() if k != "tot" and v[0]}
    fasce = lambda acc: [[f * 5, v[0], round(100 * v[2] / v[0], 1), round(100 * v[1] / v[0], 1)]
                         for f, v in sorted(acc.items()) if v[0] >= 100]
    PV = {"leghe": leghe_pv, "squadre": squadre, "mercati": mercati,
          "ver_scelte": {str(int(round(c * 100))): fasce(a) for c, a in ver_scelte.items()},
          "ver_esatti": {str(K): fasce(a) for K, a in ver_esatti.items()},
          "stag_l": V["stagioni"], "stag_s": [f"20{c[:2]}/{c[2:]}" for c in sorted(recenti)]}
    return V, PV
