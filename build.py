# -*- coding: utf-8 -*-
"""
Oracle Engine — costruisce l'app pronta da pubblicare nella cartella dist/.

    python build.py

Scarica i dati freschi (partite, calendari, allenatori), calcola i parametri
del modello e scrive dist/data.json + i file dell'app. Pensato per girare ogni
notte in automatico (GitHub Actions), ma funziona anche a mano.
"""

import datetime
import json
import math
import os
import shutil
import sys
import time
from collections import defaultdict

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)

import engine      # noqa: E402
import modello     # noqa: E402
import sorgenti    # noqa: E402
import verifica    # noqa: E402

DIST = os.path.join(QUI, "dist")
APP = os.path.join(QUI, "app")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def r3(x):
    return round(x, 3)


def rho_coppe(coppe, AD, B, fallback):
    """rho di Dixon-Coles per ogni coppa, calibrato partita per partita."""
    acc = defaultdict(lambda: defaultdict(float))
    for m in coppe:
        bc, bo = B[m["comp"]]
        ac, dc = AD(m["casa"]); ao, do = AD(m["ospite"])
        lc, lo = bc * ac * do, bo * ao * dc
        p00 = math.exp(-lc - lo)
        a = acc[m["comp"]]
        a["e00"] += p00; a["e11"] += lc * lo * p00; a["w00"] += p00 * lc * lo
        a["o00"] += m["gc"] == 0 and m["go"] == 0
        a["o11"] += m["gc"] == 1 and m["go"] == 1
    out = {}
    for c, a in acc.items():
        try:
            out[c] = round(max(-0.25, min(0.08, ((a["e00"] - a["o00"]) / a["w00"] + 1 - a["o11"] / a["e11"]) / 2)), 3)
        except ZeroDivisionError:
            out[c] = fallback
    return out


def main():
    t0 = time.time()
    oggi = datetime.date.today()
    anno = sorgenti.anno_stagione()
    anni = list(range(anno - engine.N_STAGIONI + 1, anno + 1))

    log("1/7 partite dei campionati (football-data.co.uk)…")
    partite, conteggi = engine.carica_partite()
    leghe, squadre_eng = engine.costruisci_da_dati(partite)
    if len(partite) < 5000:
        raise SystemExit("Troppe poche partite scaricate: aggiornamento annullato, resta online la versione precedente.")

    leghe_sq, presenze, ultima = defaultdict(set), {}, {}
    for m in partite:
        y = m["data"].year if m["data"].month >= 7 else m["data"].year - 1
        for t in (m["casa"], m["ospite"]):
            leghe_sq[t].add(m["lega"])
            presenze[(t, y)] = m["lega"]
            if t not in ultima or m["data"] > ultima[t][0]:
                ultima[t] = (m["data"], m["lega"])
    ab = sorgenti.Abbinatore(leghe_sq)

    log("2/7 storico panchine (Wikipedia, %d stagioni × %d campionati)…" % (len(anni), len(sorgenti.PAGINE_WIKI)))
    storico = modello.StoricoAllenatori(ab, anni, presenze)
    log("    pagine lette:", len(storico.pagine_ok))

    log("3/7 statistiche allenatori e ponderazione per credibilità…")
    stats_all = modello.statistiche_allenatori(partite, storico)
    seconde, det_sec = modello.forza_seconde(partite, leghe)
    log("    forza seconde divisioni rispetto alla prima (squadre promosse/retrocesse):",
        {k: f"{v} su {det_sec.get(k)} cambi di categoria" for k, v in seconde.items()})
    lega_ora = {t: ultima[t][1] for t in ultima}
    base, previsione, carriera_tutta, R_res = modello.costruisci_parametri(
        partite, leghe, squadre_eng, storico, scala=seconde, lega_ora=lega_ora)

    cap, det_tr = modello.stima_trasferimento(partite, storico, R_res)
    modello.CAP_CAR.update(cap)
    log("    carriera allenatore che si ripete nella squadra nuova (dai dati):",
        {k: f"{v['pendenza']:+.2f} su {v['casi']} cambi" for k, v in det_tr.items()})

    log("4/7 coppe europee e forza dei campionati…")
    coppe = sorgenti.partite_coppe(ab, anni)
    lega_di = {t: ultima[t][1] for t in base if t in ultima}
    forza, solo, B = modello.forza_campionati(
        coppe, {t: {"att": base[t]["att"], "dif": base[t]["dif"]} for t in lega_di}, lega_di)

    # le seconde divisioni non giocano le coppe: la loro forza è quella della prima divisione
    # del paese moltiplicata per il fattore misurato sulle promosse/retrocesse
    for d2, d1 in engine.SECONDE.items():
        if d2 in seconde and d1 in forza:
            forza[d2] = round(forza[d1] * seconde[d2], 3)

    def AD(t):
        if t in lega_di:
            s = forza.get(lega_di[t], 1.0)
            return base[t]["att"] * s, base[t]["dif"] / s
        v = solo.get(t, [0.85, 1.2, 0])
        return v[0], v[1]
    dna_coppe = engine.carica_coppe()
    rho_c = rho_coppe(coppe, AD, B, -0.05)

    log("5/7 calendario e risultati della finestra…")
    finestra = sorgenti.partite_finestra(ab, partite)
    log("    partite in finestra:", len(finestra))

    eu_all = modello.allenatori_in_coppa(coppe, storico)

    log("6/7 classifiche, forma, precedenti, tiri…")
    classif = modello.classifiche(partite)
    forma, prec = modello.forma_e_precedenti(partite, coppe, [(f["c"], f["o"]) for f in finestra])
    tiri = modello.profili_tiri(partite)
    extra = modello.medie_lega_extra(partite)
    mv = modello.medie_venue(partite)

    log("    verifica sul passato e misura dell'incertezza…")
    VER = verifica.riassunto_verifica(partite, leghe)
    log(f"    {VER['n']} partite verificate · smorzamento gol {VER['gamma']} · favorito indovinato {VER['acc1x2']:.1%}")
    # quante informazioni ha ogni squadra: campione effettivo (pesato) e partite di questa stagione
    cod_corr = engine._codici_stagioni()[-1]
    info = defaultdict(lambda: [0.0, 0.0, 0])
    for m in partite:
        w = engine.DECADIMENTO ** max(0.0, (oggi - m["data"]).days / 365.25)
        for t in (m["casa"], m["ospite"]):
            v = info[t]
            v[0] += w; v[1] += w * w
            if m.get("stagione") == cod_corr:
                v[2] += 1

    log("7/7 scrivo dist/…")
    # ---- campionati ----
    L = {}
    for nome, v in leghe.items():
        V = mv.get(nome, {})
        L[nome] = {
            "gc": r3(v["gol_casa"]), "gt": r3(v["gol_trasferta"]), "cor": round(v["corner"], 2), "cart": round(v["cart"], 2),
            "vcc": r3(V.get("cor_c", v["corner"] / 2)), "vco": r3(V.get("cor_o", v["corner"] / 2)),
            "vkc": r3(V.get("cart_c", v["cart"] / 2)), "vko": r3(V.get("cart_o", v["cart"] / 2)),
            "rho": v.get("rho_emp", engine.RHO_LEGA.get(nome, engine.RHO_DEFAULT)),
            "p1": v.get("p1"), "px": v.get("px"), "p2": v.get("p2"), "ov": v.get("ov"), "gg": v.get("gg"),
            "top": v.get("top"), "s": forza.get(nome, 1.0), "x": extra.get(nome, {}),
        }
    DEF = {k: r3(sum(l[k] for l in L.values()) / len(L)) for k in ("vcc", "vco", "vkc", "vko")}

    # ---- coppe ----
    # livello di gol attuale di ogni coppa (stessa memoria corta usata per B): è il riferimento
    # verso cui si smorzano i gol attesi, non la media di 10 anni
    livello = defaultdict(lambda: [0.0, 0.0])
    for m in coppe:
        w = 0.5 ** (max(0, (oggi - m["data"]).days) / 240)
        livello[m["comp"]][0] += w; livello[m["comp"]][1] += w * (m["gc"] + m["go"])
    CUP = {}
    for nome, b in B.items():
        d = dna_coppe.get(nome, {})
        lv = livello.get(nome)
        tot_attuale = lv[1] / lv[0] if lv and lv[0] > 20 else d.get("gc", 1.5) + d.get("gt", 1.2)
        CUP[nome] = {"B": b, "rho": rho_c.get(nome, -0.05), "tot": r3(tot_attuale),
                     "p1": d.get("p1"), "px": d.get("px"), "p2": d.get("p2"),
                     "ov": d.get("ov"), "gg": d.get("gg"), "n": d.get("n"), "anni": d.get("anni")}

    # ---- squadre ----
    in_finestra = {f["c"] for f in finestra} | {f["o"] for f in finestra}
    attive = {t for t, (d, _) in ultima.items() if (oggi - d).days < 3 * 365} | (in_finestra & set(base))
    Q, allenatori_attuali = {}, {}
    for t in sorted(attive):
        if t not in base or t not in squadre_eng:
            continue
        coach, nota = storico.attuale(t) if (oggi - ultima[t][0]).days < 200 else (None, None)
        prev = previsione(t, coach)
        se = squadre_eng[t]
        pr = dict(se.get("prof") or {})
        pr.update(cor=round(se["cor_pro"], 2), cor_s=round(se["cor_con"], 2))
        if pr.get("gialli") is not None:
            pr["gia"] = pr.pop("gialli"); pr["ros"] = pr.pop("rossi")
        q = {"l": ultima[t][1], "b": [r3(base[t][k]) for k in modello.METRICHE],
             "p": [r3(prev["p"][k]) for k in modello.METRICHE], "pr": pr}
        if se.get("cor_stima"):
            q["cs"] = 1
        v = info[t]
        q["u"] = [round(v[0] ** 2 / v[1], 1) if v[1] else 0, v[2]]
        if coach:
            q["all"] = coach
            allenatori_attuali[coach] = t
            dal = storico.inizio_incarico(t, coach)
            if dal:
                q["dal"] = dal.isoformat()
            sp = prev["spieg"]
            q["sp"] = {k: sp[k] for k in ("att", "dif", "corF", "cart") if k in sp}
            q["sp"]["n_qui"] = sp.get("n_qui", 0)
            q["sp"]["n_car"] = sp.get("n_car", 0)
        if nota:
            q["nota"] = nota
        if t in tiri:
            q["t"] = tiri[t]
        Q[t] = q
    tre_anni_fa = oggi - datetime.timedelta(days=3 * 365)
    recenti_coppa = defaultdict(int)
    for m in coppe:
        if m["data"] >= tre_anni_fa:
            recenti_coppa[m["casa"]] += 1; recenti_coppa[m["ospite"]] += 1
    for t, (a, d, n) in solo.items():
        if t in Q:
            continue
        if t in in_finestra or recenti_coppa[t] >= 6:
            Q[t] = {"solo": [a, d, n]}

    # ---- allenatori ----
    C = {}
    for nome, s in stats_all.items():
        if s["n"] < 5 and nome not in allenatori_attuali:
            continue
        car, n_car = carriera_tutta(sorgenti.norm(nome))
        s = dict(s)
        s["car"] = [car[k] for k in modello.METRICHE]
        st = modello.stile_allenatore(nome)
        if st:
            s["st"] = st
        if nome in eu_all:
            s["eu"] = eu_all[nome]
        C[nome] = s
    for nome in allenatori_attuali:
        if nome not in C:
            C[nome] = {"n": 0, "squadre": []}
            st = modello.stile_allenatore(nome)
            if st:
                C[nome]["st"] = st

    # ---- partite, forma, precedenti ----
    rilevanti = in_finestra | {r[0] for rows in classif.values() for r in rows}
    FO = {t: v for t, v in forma.items() if t in rilevanti}
    derby = [[*sorted(k), v[0], v[1]] for k, v in engine.DERBIES.items()]

    # codici di sblocco (solo impronte) e impostazioni del canale
    K = {"sale": "", "h": [], "adm": []}
    if os.path.exists(os.path.join(QUI, "codici.json")):
        with open(os.path.join(QUI, "codici.json"), encoding="utf-8") as f:
            cj = json.load(f)
        K = {"sale": cj["sale"], "h": [c["h"] for c in cj["codici"]],
             "adm": [c["h"] for c in cj["codici"] if c.get("admin")]}
    S = {}
    if os.path.exists(os.path.join(QUI, "impostazioni.json")):
        with open(os.path.join(QUI, "impostazioni.json"), encoding="utf-8") as f:
            S = json.load(f)

    codici = engine._codici_stagioni()
    dati = {
        "meta": {
            "gen": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "partite": len(partite), "coppe": len(coppe), "pagine_wiki": len(storico.pagine_ok),
            "stagioni": f"20{codici[0][:2]}/{codici[0][2:]} → 20{codici[-1][:2]}/{codici[-1][2:]}",
            "allenatori": len(C), "squadre": len(Q),
        },
        "L": L, "CUP": CUP, "DEF": DEF, "Q": Q, "C": C, "F": finestra, "H": prec, "FO": FO, "CL": classif,
        "D": derby, "STILI": engine.STYLES, "V": VER, "K": K, "S": S, "CAP": modello.CAP_CAR,
    }

    os.makedirs(DIST, exist_ok=True)
    with open(os.path.join(DIST, "data.json"), "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, separators=(",", ":"))
    for nome in ("index.html", "manifest.webmanifest", "sw.js", "icon-192.png", "icon-512.png", "icon-maskable-512.png"):
        shutil.copy2(os.path.join(APP, nome), os.path.join(DIST, nome))
    # il service worker cambia nome alla cache a ogni build: l'app sul telefono si aggiorna da sola
    sw = os.path.join(DIST, "sw.js")
    with open(sw, encoding="utf-8") as f:
        testo = f.read().replace("__VERSIONE__", dati["meta"]["gen"])
    with open(sw, "w", encoding="utf-8") as f:
        f.write(testo)
    kb = os.path.getsize(os.path.join(DIST, "data.json")) // 1024
    log(f"FATTO in {time.time() - t0:.0f}s — {len(partite)} partite, {len(coppe)} di coppa, {len(finestra)} in calendario, "
        f"{len(Q)} squadre, {len(C)} allenatori, data.json {kb} KB")
    nb = {k: sorted(v)[:15] for k, v in ab.non_abbinate.items() if v and k != "coppe"}
    if nb:
        log("nomi non abbinati (campionati):", nb)


if __name__ == "__main__":
    main()
