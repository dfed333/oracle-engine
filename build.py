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

import arbitri     # noqa: E402
import engine      # noqa: E402
import mercato     # noqa: E402
import modello     # noqa: E402
import sorgenti    # noqa: E402
import taratura    # noqa: E402
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
    # le tabelle Wikipedia lette con il vecchio difetto delle intestazioni ("Pre-season"): ora stanno in wiki2
    shutil.rmtree(os.path.join(engine.CARTELLA_CACHE, "wiki"), ignore_errors=True)

    log("1/7 partite dei campionati (football-data.co.uk)…")
    partite, conteggi = engine.carica_partite()
    leghe, squadre_eng = engine.costruisci_da_dati(partite)
    if len(partite) < 5000:
        raise SystemExit("Troppe poche partite scaricate: aggiornamento annullato, resta online la versione precedente.")
    mostrate = set(engine.LEGHE_FD.values())          # Serie B, Championship e 2. Bundesliga: solo storico
    log("    attese del mercato: gol attesi di ogni partita con quote e forza delle squadre…")
    cache_gol = mercato.aggiungi_gol_attesi(partite, leghe)
    forza_q, leghe_q, storia_q = mercato.forza_dalle_quote(partite, leghe)
    log(f"    {sum(1 for m in partite if m.get('lk'))} partite con quote ({cache_gol.nuovi} nuove), forza di {len(forza_q)} squadre")

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
    # livello di gol delle coppe per la forza dalle quote (verificato sulle partite di coppa passate)
    B_q = mercato.livello_coppe(coppe, storia_q, forza, solo, oggi)
    log("    livello di gol delle coppe (forza dalle quote):", B_q)
    dna_coppe = engine.carica_coppe()
    rho_c = rho_coppe(coppe, AD, B, -0.05)

    log("5/7 calendario e risultati della finestra…")
    finestra = sorgenti.partite_finestra(ab, partite)
    for f in finestra:
        rho = mercato.rho_di(leghe, f["comp"]) if f["comp"] in leghe else rho_c.get(f["comp"], -0.05)
        qe = f.pop("qe", None)
        if qe:                                   # quote più vicine al calcio d'inizio (ESPN): le più affidabili
            lh, la = cache_gol.get(qe[:4], rho, qe[4])
            o25 = qe[3] if qe[4] == 2.5 else verifica.probabilita(mercato.matrice(lh, la, rho))["O25"]
            f["q"] = [qe[0], qe[1], qe[2], round(o25, 5), lh, la]
        elif f.get("q"):
            lh, la = cache_gol.get(f["q"], rho)
            f["q"] = list(f["q"]) + [lh, la]
    cache_gol.salva()
    log("    partite in finestra:", len(finestra), "· con le attese del mercato:", sum(1 for f in finestra if f.get("q")),
        "· ESPN:", sorgenti.CONTROLLO.get("espn"))
    log("    arbitri: storico, stagione in corso e designati…")
    try:
        AR, designati, diag_arb = arbitri.costruisci(partite, finestra, oggi, log=log)
    except Exception as e:                     # gli arbitri sono un di più: se la fonte non risponde, l'app esce lo stesso
        log("    arbitri non disponibili:", type(e).__name__, e)
        AR, designati, diag_arb = {}, {}, {"errore": f"{type(e).__name__}: {e}"}
    for f in finestra:
        a = designati.get((f["t"][:10], f["c"], f["o"]))
        if a:
            f["ar"] = a

    eu_all = modello.allenatori_in_coppa(coppe, storico)

    log("6/7 classifiche, forma, precedenti, tiri…")
    classif = modello.classifiche(partite)
    forma, prec = modello.forma_e_precedenti(partite, coppe, [(f["c"], f["o"]) for f in finestra])
    tiri = modello.profili_tiri(partite)
    extra = modello.medie_lega_extra(partite)
    mv = modello.medie_venue(partite)
    # livello della stagione in corso (2026/27: più gol e tiri, meno cartellini dopo il Mondiale)
    FS, fs_comune, fs_n = taratura.fattori_stagione(partite, oggi)
    log("    livello della stagione in corso rispetto alla memoria di un anno (tutti i campionati):",
        {k: f"{(v - 1) * 100:+.1f}% su {fs_n.get(k, 0)} partite" for k, v in fs_comune.items()})

    log("    verifica sul passato (modello statistico, serve solo alle squadre senza quote)…")
    VER = verifica.riassunto_verifica(partite, leghe)
    log(f"    modello statistico: {VER['n']} partite · favorito indovinato {VER['acc1x2']:.1%}")
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

    log("    verifica del motore dell'app (attese del mercato) e Confronto…")
    squadre_ora = {t: ultima[t][1] for t in ultima if ultima[t][0] >= oggi - datetime.timedelta(days=200)}
    VQ, PV = verifica.verifica_mercato(partite, leghe, mostrate, squadre_ora)
    VV = {"gamma": VER["gamma"], "curve": VER["curve"], "q": VQ["q"], "r": VQ["r"], "fe": VQ["fe"], "stagioni": VQ["stagioni"], "n": VQ["q"]["n"],
         "vecchio": {"n": VER["n"], "acc1x2": VER["acc1x2"]}}
    log(f"    con le quote: {VQ['q']['n']} partite · favorito {VQ['q']['acc1x2']:.1%} · Over/Under {VQ['q']['ou']:.1%} · "
        f"Gol/No Gol {VQ['q']['gg']:.1%} · esatto {VQ['q']['esatto1']:.1%} (primi 3: {VQ['q']['esatto3']:.1%})")
    log(f"    forza dalle quote (partite senza quote): {VQ['r']['n']} partite · favorito {VQ['r']['acc1x2']:.1%} · "
        f"Over/Under {VQ['r']['ou']:.1%} · Gol/No Gol {VQ['r']['gg']:.1%}")
    PV["num"] = {l: v for l, v in verifica.numeri_campionati(partite, oggi).items() if l in mostrate}
    log(f"    prevedibilità: {len(PV['leghe'])} campionati, {len(PV['squadre'])} squadre")

    log("7/7 scrivo dist/…")
    # ---- campionati ----
    L = {}
    for nome, v in leghe.items():
        if nome not in mostrate:
            continue
        V = mv.get(nome, {})
        fs = FS.get(nome) or dict(fs_comune)
        fg, fc, fk = fs["gol"], fs["cor"], fs["cart"]
        x = dict(extra.get(nome, {}))
        if "gol" in x:
            x["gol"] = round(x["gol"] * fg, 2)
        if "t" in x:
            x["t"], x["p"] = round(x["t"] * fs["tiri"], 2), round(x["p"] * fs["tip"], 2)
        x["ft"], x["fp"] = fs["tiri"], fs["tip"]          # i tiri delle squadre sono medie assolute: il fattore si applica nell'app
        L[nome] = {
            "gc": r3(v["gol_casa"] * fg), "gt": r3(v["gol_trasferta"] * fg),
            "cor": round(v["corner"] * fc, 2), "cart": round(v["cart"] * fk, 2),
            "vcc": r3(V.get("cor_c", v["corner"] / 2) * fc), "vco": r3(V.get("cor_o", v["corner"] / 2) * fc),
            "vkc": r3(V.get("cart_c", v["cart"] / 2) * fk), "vko": r3(V.get("cart_o", v["cart"] / 2) * fk),
            "fs": fs,
            "rho": v.get("rho_emp", engine.RHO_LEGA.get(nome, engine.RHO_DEFAULT)),
            "p1": v.get("p1"), "px": v.get("px"), "p2": v.get("p2"), "ov": v.get("ov"), "gg": v.get("gg"),
            "top": v.get("top"), "s": forza.get(nome, 1.0), "x": x,
        }
        if nome in leghe_q:
            L[nome]["m"] = [r3(leghe_q[nome][0]), r3(leghe_q[nome][1])]
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
        CUP[nome] = {"B": b, "Bq": B_q.get(nome, b), "rho": rho_c.get(nome, -0.05), "tot": r3(tot_attuale),
                     "p1": d.get("p1"), "px": d.get("px"), "p2": d.get("p2"),
                     "ov": d.get("ov"), "gg": d.get("gg"), "n": d.get("n"), "anni": d.get("anni")}

    # ---- squadre ----
    in_finestra = {f["c"] for f in finestra} | {f["o"] for f in finestra}
    attive = {t for t, (d, l) in ultima.items() if (oggi - d).days < 3 * 365 and l in mostrate} | (in_finestra & set(base))
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
        fq = forza_q.get(t)
        if fq and fq[0] == q["l"]:
            q["m"] = [round(fq[1], 4), round(fq[2], 4), fq[3]]     # forza dalle quote: attacco, difesa, partite nell'ultimo anno
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
    classif = {l: v for l, v in classif.items() if l in mostrate}
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
            "allenatori": len(C), "squadre": len(Q), "arbitri": len(AR), "arb_k": bool(os.environ.get("FOOTBALL_DATA_KEY", "").strip()),
            # controllo delle fonti (pubblico, nessun dato riservato): serve a verificare che dicano la stessa cosa
            "controllo": {"arbitri": diag_arb, "calendario": sorgenti.CONTROLLO},
        },
        "L": L, "CUP": CUP, "DEF": DEF, "Q": Q, "C": C, "F": finestra, "H": prec, "FO": FO, "CL": classif,
        "D": derby, "STILI": engine.STYLES, "V": VV, "K": K, "S": S, "CAP": modello.CAP_CAR, "AR": AR, "PV": PV,
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
