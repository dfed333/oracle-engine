# -*- coding: utf-8 -*-
"""
Oracle Engine — modello dell'app.

Per ogni squadra il pronostico unisce tre fonti, ognuna pesata per quanto è
CREDIBILE (cioè quante partite reali la sostengono):

  1. BASE SQUADRA: 10 stagioni di partite vere, le recenti contano di più,
     corrette per la forza degli avversari, gol mischiati agli xG quando la
     fonte li pubblica.
  2. ALLENATORE IN QUESTA SQUADRA: come gioca la squadra da quando c'è lui.
     Peso = partite / (partite + K): 3 partite pesano poco, 9 anni quasi tutto.
  3. CARRIERA DELL'ALLENATORE ALTROVE: come cambiano le sue squadre rispetto
     al loro standard. Conta soprattutto quando è appena arrivato, con un tetto
     perché la rosa è diversa.

Più la forza dei campionati (dalle coppe europee), così una squadra che domina
un campionato debole non viene scambiata per una big europea.
"""

import datetime
import json
from collections import defaultdict

import engine
import sorgenti
from sorgenti import norm, anno_stagione

METRICHE = ("att", "dif", "corF", "corA", "cart")
K_BASE = 6.0                     # partite "neutre" virtuali che frenano la base squadra
PESO_XG = 0.5                    # quando ci sono gli xG: gol effettivi = metà gol, metà xG
# partite (effettive) perché il dato allenatore-squadra valga quanto la base
K_STINT = {"att": 25.0, "dif": 25.0, "corF": 12.0, "corA": 12.0, "cart": 15.0}
K_CAR = 40.0                     # partite di carriera per avere la piena fiducia
# quota massima dell'effetto-allenatore che si trasferisce da una squadra all'altra.
# Viene ricalcolata a ogni aggiornamento da stima_trasferimento() sui cambi di panchina reali;
# questi sono solo i valori di partenza (misurati a ottobre 2026 su 397 cambi).
CAP_CAR = {"att": 0.15, "dif": 0.05, "corF": 0.22, "corA": 0.31, "cart": 0.07}


def _peso(d, oggi):
    return engine.DECADIMENTO ** max(0.0, (oggi - d).days / 365.25)


def _cl(x, lo, hi):
    return max(lo, min(hi, x))


# ==================================================================
# STORICO PANCHINE
# ==================================================================

class StoricoAllenatori:
    """
    Ricostruisce, squadra per squadra e stagione per stagione, chi era in
    panchina e da quando, usando le tabelle di Wikipedia. Se una stagione non
    ha cambi registrati l'allenatore è quello dell'anno prima; se c'è un buco
    (squadra retrocessa in una lega non letta, pagina mancante) la catena si
    interrompe: meglio "non so" che un'attribuzione sbagliata.
    """

    def __init__(self, abbinatore, anni, presenze):
        # presenze: {(squadra, anno): lega} dalle partite reali
        self.seg = defaultdict(dict)        # team -> anno -> [(data|None, allenatore|None)]
        self.personale = defaultdict(dict)  # team -> anno -> allenatore
        self.ultimo_uscente = {}            # team -> (data, allenatore) ultimo esonero/addio
        pagine_ok = set()
        eventi = defaultdict(lambda: defaultdict(list))
        for lega in sorgenti.PAGINE_WIKI:
            for anno in anni:
                d = sorgenti.leggi_pagina_wiki(lega, anno)
                if d.get("errore"):
                    continue
                pagine_ok.add((lega, anno))
                for team, link, nome in d["personale"]:
                    t = abbinatore.trova(team, lega, link)
                    if t:
                        self.personale[t][anno] = nome
                visti = set()
                for c in d["cambi"]:
                    t = abbinatore.trova(c["team"], lega, c["link"])
                    if not t:
                        continue
                    if c["uscente"] and c["vacanza"]:
                        k = (t, c["vacanza"], "out", norm(c["uscente"]))
                        if k not in visti:
                            visti.add(k)
                            eventi[t][anno].append((datetime.date.fromisoformat(c["vacanza"]), 0, "out", c["uscente"]))
                    data_in = c["nomina"] or c["vacanza"]
                    if c["entrante"] and data_in:
                        k = (t, data_in, "in", norm(c["entrante"]))
                        if k not in visti:
                            visti.add(k)
                            eventi[t][anno].append((datetime.date.fromisoformat(data_in), 1, "in", c["entrante"]))
        self.pagine_ok = pagine_ok

        squadre = {t for (t, _) in presenze}
        for t in squadre:
            ultimo = None
            for anno in sorted(anni):
                lega = presenze.get((t, anno))
                if not lega or (lega, anno) not in pagine_ok:
                    ultimo = None
                    continue
                ev = sorted(eventi[t].get(anno, []))
                inizio = datetime.date(anno, 7, 1)
                pre = [e for e in ev if e[0] < inizio]
                dentro = [e for e in ev if e[0] >= inizio]
                pers = self.personale[t].get(anno)
                if pre and pre[-1][2] == "in":
                    partenza = pre[-1][3]
                elif pre:                          # vacante a inizio stagione
                    partenza = None
                elif dentro and dentro[0][2] == "out":
                    partenza = dentro[0][3]
                elif not ev:
                    partenza = pers or ultimo
                else:
                    partenza = ultimo
                s = [(None, partenza)] + [(e[0], e[3] if e[2] == "in" else None) for e in dentro]
                self.seg[t][anno] = s
                ultimo = s[-1][1]
                if anno == anno_stagione():
                    usciti = [e for e in ev if e[2] == "out"]
                    if usciti:
                        self.ultimo_uscente[t] = (usciti[-1][0], usciti[-1][3])

    def allenatore(self, team, d):
        segs = self.seg.get(team, {}).get(d.year if d.month >= 7 else d.year - 1)
        if not segs:
            return None
        attuale = segs[0][1]
        for data, nome in segs[1:]:
            if data <= d:
                attuale = nome
            else:
                break
        return attuale

    def attuale(self, team):
        """(allenatore, nota). Allenatore None = panchina vacante o sconosciuta."""
        oggi = datetime.date.today()
        nome = self.allenatore(team, oggi)
        if nome:
            return nome, None
        anno = anno_stagione()
        pers = self.personale.get(team, {}).get(anno)
        usc = self.ultimo_uscente.get(team)
        if usc:
            if pers and norm(pers) != norm(usc[1]):
                return pers, "ad interim"
            return None, f"panchina vacante: {usc[1]} ha lasciato il {usc[0].strftime('%d/%m/%Y')}"
        if pers:
            return pers, None
        return None, None

    def inizio_incarico(self, team, nome):
        """Data d'inizio dell'incarico in corso (None se precede le stagioni lette)."""
        inizio = None
        for anno in sorted(self.seg.get(team, {})):
            for data, chi in self.seg[team][anno]:
                if chi and norm(chi) == norm(nome):
                    if inizio is None:
                        inizio = data or datetime.date(anno, 7, 1)
                else:
                    if data is not None or chi is not None:
                        inizio = None
        return inizio


def stile_allenatore(nome):
    """Identità tattica dall'archivio (None = non ancora classificata)."""
    if not nome:
        return None
    n = norm(nome)
    for k, v in engine.COACHES.items():
        if norm(k) == n:
            return v
    parti = n.split()
    cand = [(k, v) for k, v in engine.COACHES.items() if norm(k).split()[-1] == parti[-1]]
    if len(cand) == 1 and norm(cand[0][0])[0] == n[0]:
        return cand[0][1]
    return None


# ==================================================================
# RAPPORTI PER PARTITA E BASI SQUADRA
# ==================================================================

def medie_venue(partite):
    """Medie di lega separate casa/trasferta per angoli e cartellini."""
    acc = defaultdict(lambda: defaultdict(float))
    for m in partite:
        a, w = acc[m["lega"]], m["peso"]
        if m["cor_c"] is not None and m["cor_o"] is not None:
            a["wc"] += w; a["cc"] += w * m["cor_c"]; a["co"] += w * m["cor_o"]
        if m["cart_c"] is not None and m["cart_o"] is not None:
            a["wk"] += w; a["kc"] += w * m["cart_c"]; a["ko"] += w * m["cart_o"]
    out = {}
    for l, a in acc.items():
        out[l] = {
            "cor_c": a["cc"] / a["wc"] if a["wc"] else 5.2, "cor_o": a["co"] / a["wc"] if a["wc"] else 4.5,
            "cart_c": a["kc"] / a["wk"] if a["wk"] else 2.2, "cart_o": a["ko"] / a["wk"] if a["wk"] else 2.4,
        }
    return out


def rapporti_partite(partite, leghe, squadre_eng, mv):
    """
    Per ogni partita e lato: rapporti rispetto alla media di lega, corretti per
    la forza dell'avversario (pass 1 = rating del motore).
    """
    out = []
    for m in partite:
        L, V = leghe[m["lega"]], mv[m["lega"]]
        tc, to = squadre_eng.get(m["casa"]), squadre_eng.get(m["ospite"])
        if not tc or not to:
            continue
        gc, go = m["gc"], m["go"]
        if m.get("xg_c") is not None and m.get("xg_o") is not None:
            gc = (1 - PESO_XG) * gc + PESO_XG * m["xg_c"]
            go = (1 - PESO_XG) * go + PESO_XG * m["xg_o"]
        cor_ok = m["cor_c"] is not None and m["cor_o"] is not None
        rc = {
            "att": _cl(gc / (L["gol_casa"] * to["dif"]), 0, 4), "dif": _cl(go / (L["gol_trasferta"] * to["att"]), 0, 4),
            "cart": m["cart_c"] / V["cart_c"] if m["cart_c"] is not None else None,
        }
        ro = {
            "att": _cl(go / (L["gol_trasferta"] * tc["dif"]), 0, 4), "dif": _cl(gc / (L["gol_casa"] * tc["att"]), 0, 4),
            "cart": m["cart_o"] / V["cart_o"] if m["cart_o"] is not None else None,
        }
        if cor_ok:
            cfa_c = to["cor_con"] / (L["corner"] / 2)
            cff_o = to["cor_pro"] / (L["corner"] / 2)
            cfa_o = tc["cor_con"] / (L["corner"] / 2)
            cff_c = tc["cor_pro"] / (L["corner"] / 2)
            rc["corF"] = _cl(m["cor_c"] / (V["cor_c"] * cfa_c), 0, 4)
            rc["corA"] = _cl(m["cor_o"] / (V["cor_o"] * cff_o), 0, 4)
            ro["corF"] = _cl(m["cor_o"] / (V["cor_o"] * cfa_o), 0, 4)
            ro["corA"] = _cl(m["cor_c"] / (V["cor_c"] * cff_c), 0, 4)
        else:
            for r in (rc, ro):
                r["corF"] = r["corA"] = None
        out.append((m, m["casa"], rc))
        out.append((m, m["ospite"], ro))
    return out


class Somme:
    __slots__ = ("s", "w", "n")

    def __init__(self):
        self.s = {k: 0.0 for k in METRICHE}
        self.w = {k: 0.0 for k in METRICHE}
        self.n = 0

    def add(self, r, w):
        self.n += 1
        for k in METRICHE:
            if r.get(k) is not None:
                self.s[k] += w * r[k]
                self.w[k] += w

    def media(self, k, shrink=0.0, prior=1.0):
        return (self.s[k] + shrink * prior) / (self.w[k] + shrink) if self.w[k] + shrink > 0 else prior


# ==================================================================
# EFFETTO ALLENATORE CON PONDERAZIONE PER CREDIBILITÀ
# ==================================================================

def costruisci_parametri(partite, leghe, squadre_eng, storico):
    oggi = datetime.date.today()
    mv = medie_venue(partite)
    righe = rapporti_partite(partite, leghe, squadre_eng, mv)

    S_team = defaultdict(Somme)               # team -> somme di tutte le partite
    S_ct = defaultdict(Somme)                 # (coach, team) -> somme
    coach_di = []                             # allenatore per riga
    for m, team, r in righe:
        w = _peso(m["data"], oggi)
        S_team[team].add(r, w)
        c = storico.allenatore(team, m["data"])
        coach_di.append(c)
        if c:
            S_ct[(norm(c), team)].add(r, w)

    def base_wo(team, ck):
        """Base squadra senza le partite dell'allenatore ck."""
        st, sc = S_team[team], S_ct.get((ck, team))
        out = {}
        for k in METRICHE:
            s_, w_ = st.s[k], st.w[k]
            if sc:
                s_ -= sc.s[k]; w_ -= sc.w[k]
            out[k] = (s_ + K_BASE) / (max(w_, 0) + K_BASE)
        return out

    # residui di carriera: quanto ogni allenatore sposta le sue squadre dalla loro base
    cache_wo = {}
    R = defaultdict(lambda: defaultdict(Somme))      # coach -> team -> somme dei residui
    for (m, team, r), c in zip(righe, coach_di):
        if not c:
            continue
        ck = norm(c)
        if (ck, team) not in cache_wo:
            cache_wo[(ck, team)] = base_wo(team, ck)
        b = cache_wo[(ck, team)]
        res = {k: (r[k] / b[k] if r.get(k) is not None and b[k] > 0 else None) for k in METRICHE}
        R[ck][team].add(res, _peso(m["data"], oggi))

    def carriera(ck, escludi=None):
        tot = Somme()
        for team, s in R.get(ck, {}).items():
            if team == escludi:
                continue
            for k in METRICHE:
                tot.s[k] += s.s[k]; tot.w[k] += s.w[k]
            tot.n += s.n
        return tot

    base_full = {t: {k: S_team[t].media(k, K_BASE) for k in METRICHE} for t in S_team}

    def previsione(team, coach):
        """Parametri della squadra con quell'allenatore + pesi per la spiegazione."""
        if team not in base_full:
            return None
        if not coach:
            return {"p": dict(base_full[team]), "spieg": {"senza_allenatore": True}}
        ck = norm(coach)
        sc = S_ct.get((ck, team))
        b = base_wo(team, ck) if sc else base_full[team]
        car = carriera(ck, escludi=team)
        p, sp = {}, {}
        for k in METRICHE:
            n_eff = sc.w[k] if sc else 0.0
            w_s = n_eff / (n_eff + K_STINT[k])
            stint = sc.media(k) if sc and sc.w[k] > 0 else b[k]
            w_c = car.w[k] / (car.w[k] + K_CAR) * CAP_CAR[k] if car.w[k] > 0 else 0.0
            r_c = car.media(k) if car.w[k] > 0 else 1.0
            e_c = 1 + w_c * (_cl(r_c, 0.5, 1.6) - 1)
            p[k] = w_s * stint + (1 - w_s) * b[k] * e_c
            sp[k] = [round(b[k], 3), round(stint, 3), round(w_s, 3), round(r_c, 3), round(w_c, 3), round(p[k], 3)]
        sp["n_qui"] = sc.n if sc else 0
        sp["n_car"] = car.n
        return {"p": p, "spieg": sp}

    def carriera_tutta(ck):
        car = carriera(ck)
        return {k: [round(car.media(k), 3) if car.w[k] > 0 else 1.0, round(car.w[k], 1)] for k in METRICHE}, car.n

    return base_full, previsione, carriera_tutta, R


# ==================================================================
# NUMERI VERI DEGLI ALLENATORI (per le schede)
# ==================================================================

def statistiche_allenatori(partite, storico):
    acc = defaultdict(lambda: defaultdict(float))
    per_team = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    ordine = defaultdict(list)
    nomi = defaultdict(lambda: defaultdict(int))
    for m in sorted(partite, key=lambda x: x["data"]):
        for lato in ("c", "o"):
            team = m["casa"] if lato == "c" else m["ospite"]
            nome = storico.allenatore(team, m["data"])
            if not nome:
                continue
            k = norm(nome)
            nomi[k][nome] += 1
            gf = m["gc"] if lato == "c" else m["go"]
            gs = m["go"] if lato == "c" else m["gc"]
            altro = "o" if lato == "c" else "c"
            for a in (acc[k], per_team[k][team]):
                a["n"] += 1
                a["v"] += gf > gs
                a["x"] += gf == gs
                a["gf"] += gf
                a["gs"] += gs
                a["ov"] += gf + gs > 2.5
                a["gg"] += gf > 0 and gs > 0
                if m["cor_" + lato] is not None:
                    a["nc"] += 1; a["cor"] += m["cor_" + lato]; a["cor_s"] += m["cor_" + altro]
                if m["cart_" + lato] is not None:
                    a["nk"] += 1; a["gia"] += m["cart_" + lato] - (m["ros_" + lato] or 0); a["ros"] += m["ros_" + lato] or 0
                if m.get("tiri_" + lato) is not None:
                    a["nt"] += 1; a["tiri"] += m["tiri_" + lato]; a["tip"] += m["tip_" + lato] or 0
                if m.get("xg_" + lato) is not None:
                    a["nx"] += 1; a["xg"] += m["xg_" + lato]; a["xg_s"] += m["xg_" + altro] or 0
                o = m["data"].toordinal()
                a["da"] = min(a["da"] or 10 ** 9, o)
                a["a"] = max(a["a"], o)
            if not ordine[k] or ordine[k][-1] != team:
                ordine[k].append(team)

    def riass(a):
        n = a["n"]
        r = {"n": int(n), "v": round(100 * a["v"] / n, 1), "x": round(100 * a["x"] / n, 1),
             "s": round(100 * (n - a["v"] - a["x"]) / n, 1),
             "gf": round(a["gf"] / n, 2), "gs": round(a["gs"] / n, 2),
             "ov": round(100 * a["ov"] / n, 1), "gg": round(100 * a["gg"] / n, 1),
             "da": datetime.date.fromordinal(int(a["da"])).isoformat(),
             "a": datetime.date.fromordinal(int(a["a"])).isoformat()}
        if a["nc"] >= 3:
            r["cor"] = round(a["cor"] / a["nc"], 2); r["cor_s"] = round(a["cor_s"] / a["nc"], 2)
        if a["nk"] >= 3:
            r["gia"] = round(a["gia"] / a["nk"], 2); r["ros"] = round(a["ros"] / a["nk"], 3)
        if a["nt"] >= 3:
            r["tiri"] = round(a["tiri"] / a["nt"], 1); r["tip"] = round(a["tip"] / a["nt"], 1)
        if a["nx"] >= 2:
            r["xg"] = round(a["xg"] / a["nx"], 2); r["xg_s"] = round(a["xg_s"] / a["nx"], 2)
        return r

    out = {}
    for k, a in acc.items():
        if a["n"] < 1:
            continue
        nome = max(nomi[k].items(), key=lambda x: x[1])[0]
        r = riass(a)
        r["squadre"] = [[t] + [riass(per_team[k][t])[x] for x in ("n", "v", "x", "s", "gf", "gs", "da", "a")]
                        for t in dict.fromkeys(ordine[k])]
        out[nome] = r
    return out


# ==================================================================
# FORZA DEI CAMPIONATI DALLE COPPE EUROPEE
# ==================================================================

def stima_trasferimento(partite, storico, R, minimo=20):
    """
    Quanto l'effetto di un allenatore su una squadra si ripete nella squadra
    successiva: regressione tra il residuo nella squadra A e quello nella B,
    per ogni metrica, su tutti i cambi di panchina con almeno `minimo` partite.
    Ritorna il tetto da usare (pendenza riportata al campione tipico) e i dettagli.
    """
    import math
    inizio = {}
    for m in partite:
        for t in (m["casa"], m["ospite"]):
            c = storico.allenatore(t, m["data"])
            if c:
                k = (norm(c), t)
                if k not in inizio or m["data"] < inizio[k]:
                    inizio[k] = m["data"]
    cap, dettagli = {}, {}
    for met in METRICHE:
        xs, ys, ns = [], [], []
        for ck, teams in R.items():
            lst = sorted((inizio[(ck, t)], t, sm) for t, sm in teams.items()
                         if sm.n >= minimo and sm.w[met] > 0 and (ck, t) in inizio)
            for (_, _, a), (_, _, b) in zip(lst, lst[1:]):
                xs.append(math.log(max(a.s[met] / a.w[met], 1e-3)))
                ys.append(math.log(max(b.s[met] / b.w[met], 1e-3)))
                ns.append(a.n)
        if len(xs) < 30:
            cap[met] = CAP_CAR[met]
            continue
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sxx = sum((x - mx) ** 2 for x in xs)
        pend = max(0.0, sxy / sxx)
        n_medio = sum(ns) / len(ns)
        cap[met] = round(min(0.6, max(0.02, pend * (n_medio + K_CAR) / n_medio)), 3)
        dettagli[met] = {"casi": len(xs), "pendenza": round(pend, 3), "partite_medie": round(n_medio)}
    return cap, dettagli


def forza_campionati(coppe, squadre, lega_di, k_lega=40.0, k_squadra=4.0, iterazioni=80, emivita_b=240):
    """
    gol_casa ~ B_comp × A_casa × D_ospite
      squadra di campionato: A = att × s_lega, D = dif / s_lega
      squadra solo-coppa:    A, D stimati dai suoi risultati europei
    s_lega: forza del campionato (media geometrica dei 5 grandi = 1).
    """
    oggi = datetime.date.today()
    righe = [(m, _peso(m["data"], oggi)) for m in coppe]
    s = defaultdict(lambda: 1.0)
    solo = {}
    for m, _ in righe:
        for t in (m["casa"], m["ospite"]):
            if t not in squadre:
                solo.setdefault(t, [0.85, 1.20])
    comps = sorted({m["comp"] for m, _ in righe})
    B = {c: [1.5, 1.2] for c in comps}
    A0, D0 = 0.85, 1.20

    def AD(t):
        if t in squadre:
            l = lega_di[t]
            return squadre[t]["att"] * s[l], squadre[t]["dif"] / s[l]
        return solo[t]

    for _ in range(iterazioni):
        for c in comps:
            oh = ph = oa = pa = 0.0
            for m, w in righe:
                if m["comp"] != c:
                    continue
                ac, dc = AD(m["casa"]); ao, do = AD(m["ospite"])
                oh += w * m["gc"]; ph += w * ac * do
                oa += w * m["go"]; pa += w * ao * dc
            if ph and pa:
                B[c] = [oh / ph, oa / pa]
        seg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for m, w in righe:
            bc, bo = B[m["comp"]]
            ac, dc = AD(m["casa"]); ao, do = AD(m["ospite"])
            lc, lo = bc * ac * do, bo * ao * dc
            for t, f, pf, sb, ps in ((m["casa"], m["gc"], lc, m["go"], lo), (m["ospite"], m["go"], lo, m["gc"], lc)):
                if t in squadre:
                    v = seg[lega_di[t]]
                else:
                    v = acc[t]
                v[0] += w * f; v[1] += w * pf; v[2] += w * sb; v[3] += w * ps
        for l, (fo, fp, so, sp) in seg.items():
            s[l] *= (((fo + k_lega) / (fp + k_lega)) / ((so + k_lega) / (sp + k_lega))) ** 0.5
        # livello medio delle squadre solo-coppa (stima "in blocco", base del prior)
        fo_t = sum(v[0] for v in acc.values())
        ea_t = sum(v[1] / solo[t][0] for t, v in acc.items() if solo[t][0])
        so_t = sum(v[2] for v in acc.values())
        ed_t = sum(v[3] / solo[t][1] for t, v in acc.items() if solo[t][1])
        if ea_t and ed_t:
            A0, D0 = fo_t / ea_t, so_t / ed_t
        for t, (fo, fp, so, sp) in acc.items():
            a, d = solo[t]
            # fp e sp sono proporzionali ad a e d: aggiornamento moltiplicativo con prior
            ea, ed = fp / a if a else 0, sp / d if d else 0
            solo[t] = [_cl((fo + k_squadra * A0) / (ea + k_squadra), 0.25, 2.5),
                       _cl((so + k_squadra * D0) / (ed + k_squadra), 0.35, 3.0)]
        grandi = [l for l in ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1") if l in s]
        g = 1.0
        for l in grandi:
            g *= s[l]
        g **= 1 / max(1, len(grandi))
        for l in list(s):
            s[l] /= g
        for t in solo:
            solo[t] = [solo[t][0] / g, solo[t][1] * g]

    # livello di gol di ogni coppa con memoria corta: le coppe cambiano in fretta (nuovo formato,
    # stagioni da tanti gol). Verificato sul passato: 6-12 mesi battono 10 anni.
    import math
    xi = math.log(2) / emivita_b
    for c in comps:
        oh = ph = oa = pa = 0.0
        for m, _ in righe:
            if m["comp"] != c:
                continue
            w = math.exp(-xi * max(0, (oggi - m["data"]).days))
            ac, dc = AD(m["casa"]); ao, do = AD(m["ospite"])
            oh += w * m["gc"]; ph += w * ac * do
            oa += w * m["go"]; pa += w * ao * dc
        if ph and pa:
            B[c] = [oh / ph, oa / pa]
    n_part = defaultdict(int)
    for m, _ in righe:
        for t in (m["casa"], m["ospite"]):
            n_part[t] += 1
    return ({l: round(v, 3) for l, v in s.items()},
            {t: [round(a, 3), round(d, 3), n_part[t]] for t, (a, d) in solo.items()},
            {c: [round(b[0], 3), round(b[1], 3)] for c, b in B.items()})


# ==================================================================
# CLASSIFICHE, FORMA, PRECEDENTI, TIRI
# ==================================================================

def allenatori_in_coppa(coppe, storico):
    """Rendimento in Europa di ogni allenatore (solo squadre dei campionati coperti)."""
    acc = defaultdict(lambda: [0, 0, 0, 0, 0, 0])   # n, v, x, gf, gs, nomi
    nomi = {}
    for m in coppe:
        for lato in ("c", "o"):
            team = m["casa"] if lato == "c" else m["ospite"]
            c = storico.allenatore(team, m["data"]) if team in storico.seg else None
            if not c:
                continue
            gf, gs = (m["gc"], m["go"]) if lato == "c" else (m["go"], m["gc"])
            a = acc[norm(c)]
            a[0] += 1; a[1] += gf > gs; a[2] += gf == gs; a[3] += gf; a[4] += gs
            nomi[norm(c)] = c
    return {nomi[k]: [a[0], round(100 * a[1] / a[0], 1), round(100 * a[2] / a[0], 1), round(a[3] / a[0], 2), round(a[4] / a[0], 2)]
            for k, a in acc.items() if a[0] >= 4}


def classifiche(partite):
    cod = engine._codici_stagioni()[-1]
    tab = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0, 0, []]))
    for m in sorted((m for m in partite if m.get("stagione") == cod), key=lambda m: m["data"]):
        for t, gf, gs in ((m["casa"], m["gc"], m["go"]), (m["ospite"], m["go"], m["gc"])):
            r = tab[m["lega"]][t]
            r[0] += 1; r[4] += gf; r[5] += gs
            e = "V" if gf > gs else ("N" if gf == gs else "P")
            r[1 if e == "V" else (2 if e == "N" else 3)] += 1
            r[6].append(e)
    out = {}
    for lega, sq in tab.items():
        righe = [[t, r[0], r[1], r[2], r[3], r[4], r[5], 3 * r[1] + r[2], "".join(r[6][-5:])] for t, r in sq.items()]
        righe.sort(key=lambda x: (-x[7], -(x[5] - x[6]), -x[5], x[0]))
        out[lega] = righe
    return out


def forma_e_precedenti(partite, coppe, coppie, n_forma=5, n_prec=6):
    oggi = datetime.date.today()
    tutte = [(m["data"], m["lega"], m["casa"], m["ospite"], m["gc"], m["go"]) for m in partite]
    tutte += [(m["data"], m["comp"], m["casa"], m["ospite"], m["gc"], m["go"]) for m in coppe]
    tutte.sort()
    per_team = defaultdict(list)
    for x in tutte:
        if x[0] < oggi:
            per_team[x[2]].append(x)
            per_team[x[3]].append(x)
    fmt = lambda x: [x[0].isoformat(), x[1], x[2], x[3], x[4], x[5]]
    forma = {t: [fmt(x) for x in lst[-n_forma:]] for t, lst in per_team.items()}
    prec = {}
    for a, b in coppie:
        k = "|".join(sorted([a, b]))
        if k not in prec:
            prec[k] = [fmt(x) for x in per_team.get(a, []) if {x[2], x[3]} == {a, b}][-n_prec:]
    return forma, prec


def profili_tiri(partite):
    acc = defaultdict(lambda: defaultdict(float))
    oggi = datetime.date.today()
    cod = engine._codici_stagioni()[-1]
    for m in partite:
        w = _peso(m["data"], oggi)
        for lato, altro, t in (("c", "o", m["casa"]), ("o", "c", m["ospite"])):
            a = acc[t]
            if m.get("tiri_" + lato) is not None and m.get("tiri_" + altro) is not None:
                a["wt"] += w
                a["t"] += w * m["tiri_" + lato]; a["ts"] += w * m["tiri_" + altro]
                a["p"] += w * (m["tip_" + lato] or 0); a["ps"] += w * (m["tip_" + altro] or 0)
            if m.get("fal_" + lato) is not None:
                a["wf"] += w; a["f"] += w * m["fal_" + lato]
            if m.get("stagione") == cod and m.get("xg_" + lato) is not None:
                a["nx"] += 1; a["x"] += m["xg_" + lato]; a["xs"] += m["xg_" + altro] or 0
    out = {}
    for t, a in acc.items():
        r = {}
        if a["wt"] > 3:
            r.update(t=round(a["t"] / a["wt"], 2), ts=round(a["ts"] / a["wt"], 2),
                     p=round(a["p"] / a["wt"], 2), ps=round(a["ps"] / a["wt"], 2))
        if a["wf"] > 3:
            r["f"] = round(a["f"] / a["wf"], 2)
        if a["nx"] >= 2:
            r.update(x=round(a["x"] / a["nx"], 2), xs=round(a["xs"] / a["nx"], 2), nx=int(a["nx"]))
        if r:
            out[t] = r
    return out


def medie_lega_extra(partite):
    acc = defaultdict(lambda: defaultdict(float))
    oggi = datetime.date.today()
    for m in partite:
        a, w = acc[m["lega"]], _peso(m["data"], oggi)
        a["w"] += w
        a["gol"] += w * (m["gc"] + m["go"])
        a["o15"] += w * (m["gc"] + m["go"] > 1.5)
        if m.get("tiri_c") is not None and m.get("tiri_o") is not None:
            a["wt"] += w; a["t"] += w * (m["tiri_c"] + m["tiri_o"])
            a["p"] += w * ((m["tip_c"] or 0) + (m["tip_o"] or 0))
        if m.get("fal_c") is not None and m.get("fal_o") is not None:
            a["wf"] += w; a["f"] += w * (m["fal_c"] + m["fal_o"])
    out = {}
    for l, a in acc.items():
        r = {"gol": round(a["gol"] / a["w"], 2), "o15": round(100 * a["o15"] / a["w"], 1)}
        if a["wt"] > 30:
            r.update(t=round(a["t"] / a["wt"], 2), p=round(a["p"] / a["wt"], 2))
        if a["wf"] > 30:
            r["f"] = round(a["f"] / a["wf"], 2)
        out[l] = r
    return out
