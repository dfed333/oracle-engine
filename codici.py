# -*- coding: utf-8 -*-
"""
Oracle Engine — codici di sblocco della versione completa.

    python codici.py crea --nome "Marco"            # nuovo codice
    python codici.py crea --nome "Federico" --admin # codice amministratore
    python codici.py lista                          # chi ha un codice
    python codici.py revoca --nome "Marco"          # toglie l'accesso

Nel progetto pubblico (codici.json) finiscono solo le "impronte" dei codici,
mai i codici in chiaro né i nomi: quelli restano sul tuo PC in
codici_privati.csv (escluso da GitHub). Dopo ogni modifica va pubblicato
(git commit + push): l'app online si aggiorna da sola in pochi minuti.
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
import secrets
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
PUBBLICO = os.path.join(QUI, "codici.json")
PRIVATO = os.path.join(QUI, "codici_privati.csv")
ALFABETO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"     # niente 0/O, 1/I/L: si leggono senza errori


def normalizza(codice):
    return "".join(c for c in codice.upper() if c.isalnum())


def impronta(sale, codice):
    return hashlib.sha256((sale + normalizza(codice)).encode("utf-8")).hexdigest()


def carica():
    if os.path.exists(PUBBLICO):
        with open(PUBBLICO, encoding="utf-8") as f:
            pub = json.load(f)
    else:
        pub = {"sale": secrets.token_hex(16), "codici": []}
    righe = []
    if os.path.exists(PRIVATO):
        with open(PRIVATO, encoding="utf-8", newline="") as f:
            righe = list(csv.DictReader(f))
    return pub, righe


def salva(pub, righe):
    with open(PUBBLICO, "w", encoding="utf-8") as f:
        json.dump(pub, f, ensure_ascii=False, indent=1)
    with open(PRIVATO, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "nome", "codice", "admin", "creato", "stato"])
        w.writeheader()
        w.writerows(righe)


def crea(nome, admin=False):
    pub, righe = carica()
    blocchi = ["".join(secrets.choice(ALFABETO) for _ in range(4)) for _ in range(2)]
    codice = "ORCL-" + "-".join(blocchi)
    ident = secrets.token_hex(4)
    oggi = datetime.date.today().isoformat()
    pub["codici"].append({"id": ident, "h": impronta(pub["sale"], codice), "admin": bool(admin), "creato": oggi})
    righe.append({"id": ident, "nome": nome, "codice": codice, "admin": "sì" if admin else "", "creato": oggi, "stato": "attivo"})
    salva(pub, righe)
    return codice


def revoca(nome):
    pub, righe = carica()
    tolti = [r for r in righe if r["nome"].lower() == nome.lower() and r["stato"] == "attivo"]
    ids = {r["id"] for r in tolti}
    pub["codici"] = [c for c in pub["codici"] if c["id"] not in ids]
    for r in tolti:
        r["stato"] = "revocato " + datetime.date.today().isoformat()
    salva(pub, righe)
    return [r["codice"] for r in tolti]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Codici di sblocco di Oracle Engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crea"); c.add_argument("--nome", required=True); c.add_argument("--admin", action="store_true")
    r = sub.add_parser("revoca"); r.add_argument("--nome", required=True)
    sub.add_parser("lista")
    a = ap.parse_args()
    if a.cmd == "crea":
        codice = crea(a.nome, a.admin)
        print(f"Codice per {a.nome}{' (amministratore)' if a.admin else ''}: {codice}")
        print(f"Link di sblocco: https://dfed333.github.io/oracle-engine/#sblocca={codice}")
    elif a.cmd == "revoca":
        tolti = revoca(a.nome)
        print(f"Revocati {len(tolti)} codici di {a.nome}." if tolti else f"Nessun codice attivo per {a.nome}.")
    else:
        _, righe = carica()
        for x in righe:
            print(f"{x['nome']:<28} {x['codice']}  {'admin ' if x['admin'] else ''}{x['stato']} (dal {x['creato']})")


if __name__ == "__main__":
    main()
