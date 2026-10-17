# -*- coding: utf-8 -*-
"""
Oracle Engine — le attese del mercato delle scommesse.

Perché: sulle 30.895 partite della verifica (2019-2026, pronostici fatti solo con
il passato) le quote, tolto il margine del bookmaker, indovinano più del nostro
modello statistico su tutto: favorito 52,3% contro 50,9%, Over/Under 2.5 58,5%
contro 56,9%, Gol/No Gol 55,3% contro 54,4%, risultato esatto più probabile 13,5%
contro 13,2%. Mescolare le due cose non aiuta: il mercato da solo è il migliore.
L'app quindi parte dalle quote (che NON mostra) e le controlla sul passato.

1. QUOTE → GOL ATTESI: per ogni partita con quote si cercano i gol attesi delle due
   squadre (Poisson + Dixon-Coles) che riproducono 1, 2 e Over 2.5 del mercato.
   Da lì escono tutti gli altri numeri (risultati esatti, multigol, ecc.).
2. FORZA DALLE QUOTE: per le partite che le quote non le hanno ancora (coppe europee,
   giornate lontane) la forza di attacco e difesa di ogni squadra si impara dalle
   attese del mercato delle sue partite precedenti (aggiornamento partita per partita).
   Verificato: favorito 52,1%, Over/Under 58,2%, quasi come le quote vere.
"""

import bisect
import json
import math
import os
from collections import defaultdict

import engine

ALFA = 0.3            # quanto si sposta la forza di una squadra a ogni partita (scelto sulla verifica)
PASSO_LEGA = 0.02     # quanto si sposta il livello di gol del campionato
NUOVA = (-0.12, 0.12) # squadra appena arrivata nel campionato: attacco un po' sotto, difesa un po' sopra la media


def matrice(lc, lo, rho, n=11):
    pc = [math.exp(-lc)]; po = [math.exp(-lo)]
    for k in range(1, n):
        pc.append(pc[-1] * lc / k); po.append(po[-1] * lo / k)
    P = [[pc[i] * po[j] for j in range(n)] for i in range(n)]
    P[0][0] *= max(1 - lc * lo * rho, .05)
    P[0][1] *= max(1 + lc * rho, .05)
    P[1][0] *= max(1 + lo * rho, .05)
    P[1][1] *= max(1 - rho, .05)
    t = sum(map(sum, P))
    return [[v / t for v in r] for r in P]


def _p12o(lc, lo, rho):
    P = matrice(lc, lo, rho)
    p1 = p2 = o = 0.0
    for i in range(11):
        for j in range(11):
            v = P[i][j]
            if i > j:
                p1 += v
            elif i < j:
                p2 += v
            if i + j > 2:
                o += v
    return p1, p2, o


def gol_attesi(q, rho, partenza=(1.4, 1.1)):
    """
    Gol attesi (casa, ospite) che riproducono le attese del mercato q = [p1, pX, p2, pOver2.5]
    (minimi quadrati su 1, 2 e Over 2.5, Gauss-Newton in scala logaritmica).
    """
    t1, t2, to = q[0], q[2], q[3]
    a, b = math.log(max(partenza[0], .2)), math.log(max(partenza[1], .2))
    h = 1e-4
    for _ in range(30):
        r0 = [x - y for x, y in zip(_p12o(math.exp(a), math.exp(b), rho), (t1, t2, to))]
        ra = [x - y for x, y in zip(_p12o(math.exp(a + h), math.exp(b), rho), (t1, t2, to))]
        rb = [x - y for x, y in zip(_p12o(math.exp(a), math.exp(b + h), rho), (t1, t2, to))]
        J = [[(ra[i] - r0[i]) / h, (rb[i] - r0[i]) / h] for i in range(3)]
        A00 = sum(J[i][0] ** 2 for i in range(3)); A11 = sum(J[i][1] ** 2 for i in range(3))
        A01 = sum(J[i][0] * J[i][1] for i in range(3))
        g0 = sum(J[i][0] * r0[i] for i in range(3)); g1 = sum(J[i][1] * r0[i] for i in range(3))
        det = A00 * A11 - A01 * A01
        if abs(det) < 1e-16:
            break
        da = -(A11 * g0 - A01 * g1) / det
        db = -(-A01 * g0 + A00 * g1) / det
        a += max(-1.0, min(1.0, da)); b += max(-1.0, min(1.0, db))
        a = min(max(a, math.log(.08)), math.log(6)); b = min(max(b, math.log(.08)), math.log(6))
        if abs(da) + abs(db) < 1e-7:
            break
    return math.exp(a), math.exp(b)


class CacheGol:
    """I gol attesi delle partite passate non cambiano: si calcolano una volta e restano in cache."""

    def __init__(self):
        self.percorso = os.path.join(engine.CARTELLA_CACHE, "gol_attesi_mercato.json")
        try:
            with open(self.percorso, encoding="utf-8") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}
        self.nuovi = 0

    def get(self, q, rho):
        k = "%.5f|%.5f|%.5f|%.5f|%.3f" % (q[0], q[1], q[2], q[3], rho)
        v = self.d.get(k)
        if v is None:
            v = [round(x, 5) for x in gol_attesi(q, rho)]
            self.d[k] = v
            self.nuovi += 1
        return v

    def salva(self):
        if self.nuovi:
            os.makedirs(engine.CARTELLA_CACHE, exist_ok=True)
            with open(self.percorso, "w", encoding="utf-8") as f:
                json.dump(self.d, f, separators=(",", ":"))


def rho_di(leghe, lega):
    return leghe.get(lega, {}).get("rho_emp", engine.RHO_LEGA.get(lega, engine.RHO_DEFAULT))


def aggiungi_gol_attesi(partite, leghe, cache=None):
    """m["lk"] = gol attesi dal mercato per ogni partita con quote."""
    cache = cache or CacheGol()
    for m in partite:
        if m.get("q"):
            m["lk"] = cache.get(m["q"], rho_di(leghe, m["lega"]))
    cache.salva()
    return cache


def forza_dalle_quote(partite, leghe):
    """
    Forza di attacco e difesa di ogni squadra imparata dalle attese del mercato, partita per partita,
    campionato per campionato. Ogni partita viene prima PREVISTA con la forza di quel momento
    (serve alla verifica: m["mr"] = gol attesi senza guardare le quote di quella partita) e poi usata
    per aggiornare la forza.
    Ritorna (squadre, leghe_m, storia): squadre = {team: (lega, att, dif, partite_con_quote_ultimo_anno, ultima_data)},
    leghe_m = {lega: (gol casa, gol ospite)} con att e dif relativi alla media delle squadre del campionato,
    storia = {team: [(data, lega, a, d)]} dopo ogni partita (serve al livello di gol delle coppe).
    """
    storia = defaultdict(list)
    per_lega = defaultdict(list)
    for m in partite:
        per_lega[m["lega"]].append(m)
    stato = {}
    leghe_m = {}
    for lega, lst in per_lega.items():
        lst.sort(key=lambda m: m["data"])
        L = leghe.get(lega, {})
        lc = math.log(L.get("gol_casa", 1.45)); lt = math.log(L.get("gol_trasferta", 1.15))
        a, d, n, ultima = {}, {}, defaultdict(list), {}
        for m in lst:
            h, o = m["casa"], m["ospite"]
            for t in (h, o):
                if t not in a:
                    a[t], d[t] = NUOVA
            m["mr"] = (math.exp(lc + a[h] + d[o]), math.exp(lt + a[o] + d[h]))
            if not m.get("lk"):
                continue
            eh = math.log(m["lk"][0]) - (lc + a[h] + d[o])
            ea = math.log(m["lk"][1]) - (lt + a[o] + d[h])
            a[h] += ALFA * eh; d[o] += ALFA * eh
            a[o] += ALFA * ea; d[h] += ALFA * ea
            lc += PASSO_LEGA * eh; lt += PASSO_LEGA * ea
            for t in (h, o):
                n[t].append(m["data"]); ultima[t] = m["data"]
                storia[t].append((m["data"], lega, a[t], d[t]))
        # squadre del campionato oggi (ultima stagione): att e dif relativi alla loro media
        if not lst:
            continue
        ult_stag = lst[-1]["stagione"]
        attuali = {t for m in lst if m["stagione"] == ult_stag for t in (m["casa"], m["ospite"])}
        if not attuali:
            continue
        ma = sum(a[t] for t in attuali) / len(attuali); md = sum(d[t] for t in attuali) / len(attuali)
        leghe_m[lega] = (math.exp(lc + ma + md), math.exp(lt + ma + md))
        fine = lst[-1]["data"]
        for t in a:
            recenti = sum(1 for x in n[t] if (fine - x).days <= 365)
            prec = stato.get(t)
            # una squadra che ha cambiato campionato tiene la forza del campionato in cui ha giocato per ultimo
            if prec and prec[4] and ultima.get(t) and prec[4] > ultima[t]:
                continue
            if t in ultima:
                stato[t] = (lega, math.exp(a[t] - ma), math.exp(d[t] - md), recenti, ultima[t])
    return stato, leghe_m, storia


def livello_coppe(coppe, storia, forza, solo, oggi, emivita=365):
    """
    Livello di gol di ogni coppa europea per la "forza dalle quote": gol veri / gol attesi dalla forza delle due
    squadre COM'ERA il giorno della partita (× forza del campionato), con memoria di un anno.
    Verificato sulle 2.758 partite di coppa (livello stimato solo con le partite precedenti): memoria 1 anno
    la migliore (Over 2.5 logloss 0,6636 contro 0,6701 del livello usato prima, che prevedeva 3,27 gol contro 2,99 veri).
    """
    date = {t: [x[0] for x in v] for t, v in storia.items()}
    squadre_lega = defaultdict(set)
    for t, v in storia.items():
        for x in v:
            squadre_lega[x[1]].add(t)

    def stato(t, D):
        v = storia.get(t)
        if not v:
            return None
        i = bisect.bisect_left(date[t], D) - 1
        if i < 0 or (D - v[i][0]).days > 200:
            return None
        return v[i]

    medie = {}

    def media(lega, D):
        if (lega, D) not in medie:
            xs = [stato(t, D) for t in squadre_lega[lega]]
            xs = [x for x in xs if x and x[1] == lega]
            medie[(lega, D)] = (sum(x[2] for x in xs) / len(xs), sum(x[3] for x in xs) / len(xs)) if xs else (0.0, 0.0)
        return medie[(lega, D)]

    def ad(t, D):
        x = stato(t, D)
        if x:
            ma, md = media(x[1], D)
            f = forza.get(x[1], 1.0)
            return math.exp(x[2] - ma) * f, math.exp(x[3] - md) / f
        if t in solo:
            return solo[t][0], solo[t][1]
        return None

    xi = math.log(2) / emivita
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for m in coppe:
        c, o = ad(m["casa"], m["data"]), ad(m["ospite"], m["data"])
        if not c or not o:
            continue
        w = math.exp(-xi * max(0, (oggi - m["data"]).days))
        a = acc[m["comp"]]
        a[0] += w * m["gc"]; a[1] += w * c[0] * o[1]; a[2] += w * m["go"]; a[3] += w * o[0] * c[1]
    return {comp: [round(a[0] / a[1], 3), round(a[2] / a[3], 3)] for comp, a in acc.items() if a[1] and a[3]}
