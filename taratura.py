# -*- coding: utf-8 -*-
"""
Oracle Engine — taratura del modello sulle partite passate.

Verifica "come se fosse quel giorno": le partite di ogni campionato vengono
scorse in ordine di data; prima di ogni partita il modello fa il pronostico
con quello che sapeva fino al giorno prima, poi la partita entra nei dati.
Si provano diverse velocità di memoria e si tiene quella che sbaglia meno
(log-verosimiglianza del risultato esatto: premia chi dà alta probabilità
al punteggio che è uscito davvero).

  emivita squadre : dopo quanti giorni una partita vale metà (forma vs storia)
  emivita lega    : idem per il livello di gol del campionato
  gamma           : smorzamento del totale gol verso la media di lega
"""

import math
from collections import defaultdict

LN2 = math.log(2)
PRIOR_NUOVA = (0.85, 1.15)


def _logpois(k, l):
    return k * math.log(l) - l - math.lgamma(k + 1)


def _tau(i, j, lc, lo, rho):
    if i == 0 and j == 0:
        return max(1 - lc * lo * rho, .05)
    if i == 0 and j == 1:
        return max(1 + lc * rho, .05)
    if i == 1 and j == 0:
        return max(1 + lo * rho, .05)
    if i == 1 and j == 1:
        return max(1 - rho, .05)
    return 1.0


class _Acc:
    """Somma pesata che "invecchia" nel tempo (decadimento esponenziale)."""
    __slots__ = ("v", "giorno")

    def __init__(self, n):
        self.v = [0.0] * n
        self.giorno = None

    def leggi(self, giorno, xi):
        if self.giorno is not None and giorno != self.giorno:
            f = math.exp(-xi * (giorno - self.giorno))
            self.v = [x * f for x in self.v]
        self.giorno = giorno
        return self.v


def scorri(partite_lega, emivita_sq, emivita_lega, gamma=1.0, k_base=6.0, rho=-0.05,
           stagioni_min=2, raccogli=None):
    """
    Ritorna (somma log-verosimiglianza, numero partite valutate).
    raccogli: se è una lista, ci finiscono (lc, lo, gc, go, tot_lega) per ogni pronostico.
    """
    xs, xl = LN2 / emivita_sq, LN2 / emivita_lega
    stagioni = sorted({m["stagione"] for m in partite_lega})
    da_valutare = set(stagioni[stagioni_min:])
    lega = _Acc(3)                      # peso, gol casa, gol trasferta
    sq = defaultdict(lambda: _Acc(3))   # peso, attacco, difesa (rapporti con la media)
    ll, n = 0.0, 0
    for m in partite_lega:
        g = m["data"].toordinal()
        L = lega.leggi(g, xl)
        if L[0] > 20:
            Lc, Lt = L[1] / L[0], L[2] / L[0]
            if m["stagione"] in da_valutare:
                a = sq[m["casa"]].leggi(g, xs); b = sq[m["ospite"]].leggi(g, xs)
                ac, dc = ((a[1] + k_base) / (a[0] + k_base), (a[2] + k_base) / (a[0] + k_base)) if a[0] else PRIOR_NUOVA
                ao, do = ((b[1] + k_base) / (b[0] + k_base), (b[2] + k_base) / (b[0] + k_base)) if b[0] else PRIOR_NUOVA
                lc, lo = Lc * ac * do, Lt * ao * dc
                tot_l = Lc + Lt
                if gamma != 1.0:
                    t = lc + lo
                    nuovo = tot_l * (t / tot_l) ** gamma
                    lc, lo = lc * nuovo / t, lo * nuovo / t
                gc, go = m["gc"], m["go"]
                ll += _logpois(gc, lc) + _logpois(go, lo) + math.log(_tau(gc, go, lc, lo, rho))
                n += 1
                if raccogli is not None:
                    raccogli.append((lc, lo, gc, go, tot_l, m))
            # aggiornamento squadre con le medie di lega del momento
            a = sq[m["casa"]].leggi(g, xs); b = sq[m["ospite"]].leggi(g, xs)
            a[0] += 1; a[1] += m["gc"] / Lc; a[2] += m["go"] / Lt
            b[0] += 1; b[1] += m["go"] / Lt; b[2] += m["gc"] / Lc
        L[0] += 1; L[1] += m["gc"]; L[2] += m["go"]
    return ll, n


def tara(partite, griglia_sq=(90, 150, 240, 365, 540, 800, 1130), griglia_lega=(90, 180, 365, 730, 1460),
         griglia_gamma=(0.7, 0.8, 0.9, 1.0), log=print):
    per_lega = defaultdict(list)
    for m in partite:
        per_lega[m["lega"]].append(m)
    for l in per_lega.values():
        l.sort(key=lambda m: m["data"])
    risultati = {}
    for es in griglia_sq:
        for el in griglia_lega:
            for g in griglia_gamma:
                tot, n = 0.0, 0
                for lst in per_lega.values():
                    a, b = scorri(lst, es, el, g)
                    tot += a; n += b
                risultati[(es, el, g)] = tot / n
    migliore = max(risultati, key=risultati.get)
    return migliore, risultati, per_lega
