# -*- coding: utf-8 -*-
"""
Oracle Engine — controllo automatico prima di pubblicare.

Apre l'app appena costruita (dist/) in un browser vero, con lo schermo di un
telefono, e la usa come una persona: lista partite, Da guardare con le
combinazioni, Classifiche e Confronto, Allenatori e Arbitri, Preferite, le schede
delle partite con tutte le loro sezioni, schede di allenatori e arbitri, sia in
versione gratuita sia completa. Se compare anche un solo errore, esce con
codice 1: su GitHub l'aggiornamento non viene pubblicato e resta online la
versione precedente, che funziona.

    python controllo.py            (controllo rapido: un campione di partite)
    python controllo.py --tutto    (tutte le partite in calendario)
"""

import functools
import http.server
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

QUI = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(QUI, "dist")


def sintassi():
    """node --check su ogni script dell'app (se node c'è: su GitHub sì)."""
    node = shutil.which("node")
    if not node:
        print("  (node non installato qui: salto il controllo di sintassi, lo fa comunque il browser)")
        return []
    errori = []
    html = open(os.path.join(DIST, "index.html"), encoding="utf-8").read()
    pezzi = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.S)
    cartella = tempfile.mkdtemp()
    file = [(f"script{i}.js", p) for i, p in enumerate(pezzi)]
    file.append(("sw.js", open(os.path.join(DIST, "sw.js"), encoding="utf-8").read()))
    for nome, testo in file:
        percorso = os.path.join(cartella, nome)
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(testo)
        r = subprocess.run([node, "--check", percorso], capture_output=True, text=True)
        if r.returncode:
            errori.append(f"sintassi {nome}: {r.stderr.strip()[:400]}")
    shutil.rmtree(cartella, ignore_errors=True)
    return errori


class _Zitto(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def browser(tutto=False):
    from playwright.sync_api import sync_playwright
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Zitto, directory=DIST))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    errori = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True,
                            device_scale_factor=2, service_workers="block")
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errori.append(f"errore: {e}"))
        pg.on("console", lambda m: m.type == "error" and errori.append(f"console: {m.text}"))
        t0 = time.time()
        pg.goto(url)
        try:
            pg.wait_for_function("document.querySelector('#lista') && document.querySelectorAll('#lista .match').length > 0",
                                 timeout=60000)
        except Exception:
            testo = pg.evaluate("(document.querySelector('#lista')||{}).innerText||''")[:200]
            errori.append(f"l'app non mostra le partite dopo 60 secondi (si vede: {testo!r})")
            b.close(); server.shutdown()
            return errori
        print(f"  l'app parte e mostra le partite in {time.time() - t0:.1f} s")

        info = pg.evaluate("""() => ({n: D.F.length, wiki: D.meta.pagine_wiki, arbitri: D.meta.arbitri||0,
            ok: D.F.filter(f => calcola(f).ok).length})""")
        print(f"  dati: {info['n']} partite in calendario ({info['ok']} con pronostico), {info['wiki']} pagine Wikipedia, {info['arbitri']} arbitri")
        if info["n"] == 0 or info["ok"] == 0:
            errori.append("nessuna partita con pronostico")
        numeri = pg.evaluate("""() => { const male = [];
            const ok = x => typeof x === 'number' && isFinite(x);
            for (const f of D.F) { const r = calcola(f); if (!r.ok) continue; conMC(r);
              const a = affid(r), pm = probMercati(r.P), nome = f.c + ' - ' + f.o;
              if (Math.abs(r.p1 + r.px + r.p2 - 1) > 1e-6) male.push(nome + ': 1+X+2 non fa 100%');
              for (const [k, v] of Object.entries({p1: r.p1, px: r.px, p2: r.p2, o25: r.o25, gg: r.ggc, gol: r.lamC + r.lamO,
                   angoli: r.corC + r.corO, cartellini: r.kar, affid: a.val, prob: a.pr.p, margine: a.margine}))
                if (!ok(v) || v < 0 || (k !== 'gol' && k !== 'angoli' && k !== 'cartellini' && v > 1 + 1e-9)) male.push(nome + ': ' + k + ' = ' + v);
              for (const [k, v] of Object.entries(pm)) if (!ok(v) || v < -1e-9 || v > 1 + 1e-9) male.push(nome + ': mercato ' + k + ' = ' + v);
              if (Math.abs(pm['O2.5'] - r.o25) > 1e-6 || Math.abs(pm['1'] - r.p1) > 1e-6) male.push(nome + ': numeri diversi tra le sezioni');
              if (r.picks[0][1] !== principale(r).p) male.push(nome + ': prima uscita diversa dalla stellina');
            }
            return male.slice(0, 20); }""")
        errori += [f"numeri: {x}" for x in numeri]
        if not numeri:
            print("  numeri: tutte le probabilità sono coerenti (1X2, Over, Gol/Gol, mercati, affidabilità)")

        indici = pg.evaluate("""(tutto) => {
            const ok = D.F.filter(f => calcola(f).ok);
            if (tutto) return ok.map(f => f.i);
            const per = {}; for (const f of ok) (per[f.comp] = per[f.comp] || []).push(f.i);
            return Object.values(per).flatMap(l => l.slice(0, 2)).concat(D.F.filter(f => !calcola(f).ok).slice(0, 2).map(f => f.i));
        }""", tutto)

        for premium in (False, True):
            nome = "completa" if premium else "gratuita"
            pg.evaluate(f"() => {{ ACC.premium = {str(premium).lower()}; location.hash = '#partite'; router(); }}")
            # tutte le schermate e le loro viste
            passi = [
                "location.hash='#partite'; router();",
                "STATO.giorno = D.F.length ? D.F[D.F.length-1].day : STATO.giorno; schermoPartite();",
                "location.hash='#top'; router();",
                "STATO.comb.vista='es'; schermoComb(); STATO.comb.giorno='3g'; schermoComb();",
                "STATO.comb.vista='co'; for (const c of [100,90,85]) for (const f of ['tutti','esito','ou','gg','mg']) { STATO.comb.cap=c; STATO.comb.fam=f; schermoComb(); }",
                "location.hash='#leghe'; router(); STATO.legheVista='conf'; vistaLeghe();",
                "for (const s of [55,60,65,70]) { STATO.soglia=s; schermoConfronto(); } for (const p of ['10','3','1']) { STATO.per=p; schermoConfronto(); }",
                "STATO.legheVista='cl'; vistaLeghe();",
                "location.hash='#all'; router(); STATO.vista='arb'; vistaAllenatori(); STATO.vista='all'; vistaAllenatori();",
                "location.hash='#pref'; router(); D.F.slice(0,3).forEach(f => PREF.add(chiaveP(f))); schermoPreferite();",
            ]
            for js in passi:
                try:
                    pg.evaluate(f"() => {{ {js} }}")
                    pg.wait_for_timeout(60)
                    m = pg.evaluate("() => { const x = document.querySelector('.screen:not([hidden])'); const t = x ? x.innerText : ''; const m = t.match(/NaN|undefined|\\bnull\\b|\\[object Object\\]|Infinity/); return m ? m[0] : null; }")
                    if m:
                        errori.append(f"[{nome}] {js[:60]}…: nella schermata compare «{m}»")
                except Exception as e:
                    errori.append(f"[{nome}] {js[:60]}…: {str(e)[:300]}")
            # schede partita, sezione per sezione
            for i in indici:
                try:
                    n = pg.evaluate("""async (i) => { location.hash = '#m/' + i; router();
                        const tabs = [...document.querySelectorAll('#sheet .tab')];
                        for (const t of tabs) { t.click(); await new Promise(r => setTimeout(r, 5)); }
                        const pb = document.getElementById('pref-b'); if (pb) { pb.click(); pb.click(); }
                        return tabs.length; }""", i)
                    if n and n < 7:
                        errori.append(f"[{nome}] partita {i}: solo {n} sezioni")
                    rotti = pg.evaluate("""async () => { const out = [];
                        for (const t of document.querySelectorAll('#sheet .tab')) { t.click(); await new Promise(r => setTimeout(r, 5));
                          const x = (document.getElementById('pane') || {}).innerText || '';
                          const m = x.match(/NaN|undefined|\\bnull\\b|\\[object Object\\]|Infinity/); if (m) out.push(t.innerText + ': ' + m[0]); }
                        return out; }""")
                    errori += [f"[{nome}] partita {i}, sezione {x}" for x in rotti]
                except Exception as e:
                    errori.append(f"[{nome}] partita {i}: {str(e)[:300]}")
            # schede di un allenatore e di un arbitro
            for js in ["const c = Object.keys(D.C).find(n => D.C[n].n); location.hash = '#a/' + encodeURIComponent(c); router();",
                       "const a = (D.F.find(f => f.ar)||{}).ar || Object.keys(D.AR||{})[0]; if (a) { location.hash = '#r/' + encodeURIComponent(a); router(); }",
                       "location.hash='#partite'; router();"]:
                try:
                    pg.evaluate(f"() => {{ {js} }}")
                except Exception as e:
                    errori.append(f"[{nome}] {js[:50]}…: {str(e)[:300]}")
            print(f"  versione {nome}: {len(indici)} partite aperte, sezione per sezione")
        b.close()
    server.shutdown()
    return errori


def main():
    tutto = "--tutto" in sys.argv
    print("Controllo dell'app prima di pubblicarla…")
    errori = sintassi() + browser(tutto)
    if errori:
        print(f"\nTROVATI {len(errori)} ERRORI: l'app NON va pubblicata.")
        for e in errori[:40]:
            print("  -", e)
        sys.exit(1)
    print("Tutto a posto: nessun errore.")


if __name__ == "__main__":
    main()
