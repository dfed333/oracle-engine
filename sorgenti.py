# -*- coding: utf-8 -*-
"""
Oracle Engine — fonti esterne per l'app.

  • Wikipedia: allenatori in carica e storico dei cambi panchina (10 stagioni,
    11 campionati) → statistiche VERE per ogni allenatore, aggiornate da sole.
  • fixturedownload.com: calendari e risultati della stagione (9 campionati +
    Champions, Europa e Conference League) e storico delle coppe.
  • football-data.co.uk: risultati con statistiche (tiri, angoli, cartellini,
    xG) e partite della settimana per i campionati non coperti sopra.

Ogni nome squadra delle fonti esterne viene ricondotto al nome usato nel
database (quello di football-data). Se un abbinamento non è sicuro, la squadra
resta non abbinata: meglio un dato mancante che un dato sbagliato.
"""

import datetime
import difflib
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from html.parser import HTMLParser

import engine

UA = "OracleEngine/2.0 (app statistiche calcio personale)"


# ==================================================================
# DOWNLOAD CON CACHE
# ==================================================================

def _cartella(*parti):
    p = os.path.join(engine.CARTELLA_CACHE, *parti)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def scarica(url, percorso, max_ore=None, timeout=40):
    """Ritorna i byte di url, dalla cache se abbastanza recente. None se fallisce."""
    if os.path.exists(percorso):
        eta_ore = (time.time() - os.path.getmtime(percorso)) / 3600
        if max_ore is None or eta_ore < max_ore:
            with open(percorso, "rb") as f:
                return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for tentativo in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                dati = r.read()
            with open(percorso, "wb") as f:
                f.write(dati)
            return dati
        except Exception:
            time.sleep(1.5 * (tentativo + 1))
    if os.path.exists(percorso):          # rete giù: meglio la copia vecchia di niente
        with open(percorso, "rb") as f:
            return f.read()
    return None


def anno_stagione(oggi=None):
    oggi = oggi or datetime.date.today()
    return oggi.year if oggi.month >= 7 else oggi.year - 1


# ==================================================================
# NOMI: NORMALIZZAZIONE E ABBINAMENTO SQUADRE
# ==================================================================

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ").replace("ø", "o").replace("ß", "ss").replace("ı", "i")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


_STOP = set("""fc cf ac afc sc ss ssc as us bc acf calcio club football futbol cd ud rcd sd ca rc fk sk nk
pfc bk kv kvc krc kaa rsc rfc sv tsg vfb vfl bv bsc osc ogc sco fco aj hsc cs sl gd fsv spvgg ssv
de del la le the and da do dos 1 04 05 07 96 98 1899 1900 1904 1907 1909 1913 1846 1848 1860 royal""".split())


def chiave(s):
    return " ".join(t for t in norm(s).split() if t not in _STOP)


# nomi esterni → nome nel database (chiavi già normalizzate con norm())
ALIAS_SQUADRE = {
    "internazionale": "Inter", "inter milan": "Inter", "fc internazionale milano": "Inter",
    "ac milan": "Milan", "hellas verona": "Verona", "ss lazio": "Lazio", "as roma": "Roma",
    "spurs": "Tottenham", "tottenham hotspur": "Tottenham",
    "man utd": "Manchester United", "man united": "Manchester United", "man city": "Manchester City",
    "nott m forest": "Nottingham Forest", "nottm forest": "Nottingham Forest",
    "wolves": "Wolverhampton", "wolverhampton wanderers": "Wolverhampton",
    "brighton and hove albion": "Brighton", "west ham united": "West Ham",
    "newcastle united": "Newcastle", "leeds united": "Leeds",
    "atleti": "Atletico Madrid", "atletico de madrid": "Atletico Madrid", "atletico madrid": "Atletico Madrid",
    "athletic club": "Athletic Bilbao", "real betis": "Betis", "sevilla": "Siviglia",
    "barcelona": "Barcellona", "fc barcelona": "Barcellona", "celta": "Celta Vigo", "rc celta": "Celta Vigo",
    "espanyol": "Espanyol", "rcd espanyol": "Espanyol",
    "b dortmund": "Borussia Dortmund", "dortmund": "Borussia Dortmund",
    "bayern munchen": "Bayern Monaco", "bayern munich": "Bayern Monaco", "fc bayern munchen": "Bayern Monaco",
    "leipzig": "Lipsia", "rb leipzig": "Lipsia", "rasenballsport leipzig": "Lipsia",
    "leverkusen": "Bayer Leverkusen", "eintracht frankfurt": "Eintracht Francoforte",
    "frankfurt": "Eintracht Francoforte", "stuttgart": "Stoccarda", "vfb stuttgart": "Stoccarda",
    "freiburg": "Friburgo", "sc freiburg": "Friburgo",
    "borussia monchengladbach": "Borussia M'gladbach", "monchengladbach": "Borussia M'gladbach",
    "gladbach": "Borussia M'gladbach", "koln": "Colonia", "1 fc koln": "Colonia", "cologne": "Colonia",
    "werder bremen": "Werder Brema", "hamburger sv": "Amburgo", "hamburg": "Amburgo",
    "paris": "PSG", "paris saint germain": "PSG", "paris sg": "PSG", "psg": "PSG",
    "marseille": "Marsiglia", "olympique de marseille": "Marsiglia", "olympique marseille": "Marsiglia",
    "lyon": "Lione", "olympique lyonnais": "Lione", "olympique lyon": "Lione",
    "nice": "Nizza", "ogc nice": "Nizza", "stade rennais": "Rennes", "stade rennais fc": "Rennes",
    "stade brestois 29": "Brest", "stade brestois": "Brest", "saint etienne": "Saint-Étienne",
    "as saint etienne": "Saint-Étienne", "st etienne": "Saint-Étienne",
    "sporting cp": "Sporting Lisbona", "sporting": "Sporting Lisbona", "sporting lisbon": "Sporting Lisbona",
    "sl benfica": "Benfica", "sporting braga": "Braga", "sc braga": "Braga", "sp braga": "Braga",
    "vitoria de guimaraes": "Vitória Guimarães", "vitoria sc": "Vitória Guimarães",
    "psv eindhoven": "PSV", "psv": "PSV", "az": "AZ Alkmaar", "az alkmaar": "AZ Alkmaar",
    "olympiacos": "Olympiakos", "olympiacos piraeus": "Olympiakos", "olympiakos piraeus": "Olympiakos",
    "olympiacos fc": "Olympiakos", "aek athens": "AEK", "paok": "PAOK", "paok fc": "PAOK",
    "heart of midlothian": "Hearts", "hearts": "Hearts",
    "galatasaray": "Galatasaray", "istanbul basaksehir": "Başakşehir", "basaksehir": "Başakşehir",
    "union saint gilloise": "Union Saint-Gilloise", "union st gilloise": "Union Saint-Gilloise",
    "royale union saint gilloise": "Union Saint-Gilloise", "club brugge": "Club Brugge",
    "standard liege": "Standard", "sint truidense": "Sint-Truiden", "sint truidense vv": "Sint-Truiden",
    "oud heverlee leuven": "Oud-Heverlee Leuven",
    "losc": "Lille", "losc lille": "Lille", "lille osc": "Lille",
    "union sg": "Union Saint-Gilloise", "st gilloise": "Union Saint-Gilloise",
    "n e c": "NEC Nijmegen", "nec": "NEC Nijmegen", "nec nijmegen": "NEC Nijmegen",
    "racing de santander": "Racing Santander", "deportivo de la coruna": "Deportivo La Coruña",
    "ado den haag": "ADO Den Haag", "pec zwolle": "PEC Zwolle",
    "west bromwich albion": "West Brom", "b sad": "Belenenses", "belenenses sad": "Belenenses",
    "oh leuven": "Oud-Heverlee Leuven", "bodrum": "Bodrumspor", "ael": "Larisa",
    "r racing club": "Racing Santander", "sport club freiburg": "Friburgo",
    "akhisarspor": "Akhisar Belediyespor",
    "chamois niortais": "Niort", "sporting de gijon": "Sporting Gijón", "real sporting de gijon": "Sporting Gijón",
    "stade malherbe caen": "Caen", "es troyes ac": "Troyes", "red star fc": "Red Star",
    "celta fortuna": "Celta B", "stade lavallois mfc": "Laval", "stade lavallois": "Laval",
}

# varianti dello stesso nome per le squadre che giocano solo le coppe
ALIAS_COPPE = [
    ["shakhtar", "shakhtar donetsk"], ["plzen", "viktoria plzen"], ["lech", "lech poznan"],
    ["legia", "legia warszawa", "legia warsaw"], ["cska moscow", "cska moskva"],
    ["spartak moscow", "spartak moskva"], ["sk rapid", "rapid wien", "rapid vienna"],
    ["sturm", "sturm graz"], ["dinamo zagreb", "gnk dinamo"], ["m haifa", "maccabi haifa"],
    ["s bratislava", "slovan bratislava"], ["omonia", "omonoia"], ["m tel aviv", "maccabi tel aviv"],
    ["h beer sheva", "hapoel beer sheva"], ["salzburg", "red bull salzburg", "rb salzburg"],
    ["crvena zvezda", "red star belgrade"], ["copenhagen", "fc copenhagen", "kobenhavn"],
    ["young boys", "bsc young boys"], ["ferencvaros", "ferencvarosi tc"],
]


class Abbinatore:
    """
    Riconduce un nome esterno al nome del database. Ordine dei tentativi:
    nome esatto → alias → nome senza sigle (FC, AC…) → parole contenute
    (solo se l'esito è unico) → somiglianza (solo dentro lo stesso campionato).
    """

    def __init__(self, leghe_squadra):
        # leghe_squadra: {nome_db: set(leghe in cui ha giocato)}
        self.leghe = leghe_squadra
        self.per_norm = {norm(n): n for n in leghe_squadra}
        self.per_chiave = defaultdict(list)
        for n in leghe_squadra:
            self.per_chiave[chiave(n)].append(n)
        self.non_abbinate = defaultdict(set)
        self.alias_coppa = {}

    def nome_coppa(self, raw):
        """Nome unico per le squadre che giocano solo le coppe."""
        return self.alias_coppa.get(raw, raw)

    def _candidati(self, lega):
        if not lega:
            return list(self.leghe)
        return [n for n, ls in self.leghe.items() if lega in ls]

    def trova(self, nome, lega=None, titolo=None, fuzzy=True):
        for testo in [nome, titolo]:
            if not testo:
                continue
            r = self._trova(testo, lega, fuzzy and lega is not None)
            if r:
                return r
        self.non_abbinate[lega or "coppe"].add(nome)
        return None

    def _trova(self, testo, lega, fuzzy):
        n = norm(testo)
        if n in self.per_norm:
            return self.per_norm[n]
        if n in ALIAS_SQUADRE and ALIAS_SQUADRE[n] in self.leghe:
            return ALIAS_SQUADRE[n]
        k = chiave(testo)
        if not k:
            return None
        cand = self._candidati(lega)
        insieme = set(cand)
        esatti = [c for c in self.per_chiave.get(k, []) if c in insieme]
        if len(esatti) == 1:
            return esatti[0]
        if k in ALIAS_SQUADRE and ALIAS_SQUADRE[k] in self.leghe:
            return ALIAS_SQUADRE[k]
        parole = set(k.split())
        contenuti = []
        for c in cand:
            pc = set(chiave(c).split())
            # senza campionato di riferimento accetto solo il nome esterno più corto
            # ("Sporting" → "Sporting Lisbona"), mai quello più lungo ("AEK Larnaca" ≠ "AEK")
            if pc and (parole <= pc or (lega and pc <= parole)):
                contenuti.append(c)
        if len(contenuti) == 1:
            return contenuti[0]
        if fuzzy and cand:
            punteggi = sorted(((difflib.SequenceMatcher(None, k, chiave(c)).ratio(), c) for c in cand), reverse=True)
            if punteggi and punteggi[0][0] >= 0.80 and (len(punteggi) == 1 or punteggi[0][0] - punteggi[1][0] >= 0.08):
                return punteggi[0][1]
        return None


# ==================================================================
# WIKIPEDIA: TABELLE ALLENATORI
# ==================================================================

PAGINE_WIKI = {
    "Serie A": ["{s} Serie A"],
    "Premier League": ["{s} Premier League"],
    "La Liga": ["{s} La Liga"],
    "Bundesliga": ["{s} Bundesliga"],
    "Ligue 1": ["{s} Ligue 1"],
    "Primeira Liga": ["{s} Primeira Liga"],
    "Eredivisie": ["{s} Eredivisie"],
    "Pro League (Bel)": ["{s} Belgian Pro League", "{s} Belgian First Division A"],
    "Süper Lig (Tur)": ["{s} Süper Lig"],
    "Super League (Gre)": ["{s} Super League Greece", "{s} Superleague Greece"],
    "Premiership (Sco)": ["{s} Scottish Premiership"],
    "Liga 2": ["{s} Segunda División"],
    "Ligue 2": ["{s} Ligue 2"],
}

_MESI = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}


class _Tabelle(HTMLParser):
    """Estrae le tabelle 'wikitable' come righe di celle (testo + link), con rowspan/colspan."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tabelle, self.prof, self.salta = [], 0, 0
        self.riga = self.cella = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "sup", "script"):
            self.salta += 1
        if tag == "table":
            self.prof += 1
            if self.prof == 1 and "wikitable" in (a.get("class") or ""):
                self.tabelle.append([])
            elif self.prof == 1:
                self.tabelle.append(None)
            return
        if self.prof != 1 or not self.tabelle or self.tabelle[-1] is None:
            return
        if tag == "tr":
            self.riga = []
        elif tag in ("td", "th") and self.riga is not None:
            def num(x):
                try:
                    return max(1, int(re.sub(r"\D", "", x or "1") or 1))
                except ValueError:
                    return 1
            self.cella = {"t": "", "links": [], "rs": num(a.get("rowspan")), "cs": num(a.get("colspan")),
                          "th": tag == "th"}
        elif tag == "a" and self.cella is not None and not self.salta:
            self.cella["links"].append(a.get("title") or "")
        elif tag == "br" and self.cella is not None:
            self.cella["t"] += " "

    def handle_endtag(self, tag):
        if tag in ("style", "sup", "script") and self.salta:
            self.salta -= 1
        if tag == "table":
            self.prof -= 1
            return
        if self.prof != 1 or not self.tabelle or self.tabelle[-1] is None:
            return
        if tag in ("td", "th") and self.cella is not None and self.riga is not None:
            self.cella["t"] = " ".join(self.cella["t"].split())
            self.riga.append(self.cella)
            self.cella = None
        elif tag == "tr" and self.riga is not None:
            self.tabelle[-1].append(self.riga)
            self.riga = None

    def handle_data(self, data):
        if self.cella is not None and not self.salta:
            self.cella["t"] += data


def _griglia(righe):
    """Espande rowspan/colspan: ogni riga diventa una lista allineata di celle."""
    griglia, pendenti = [], {}
    for riga in righe:
        out, col, it = [], 0, iter(riga)
        cella = next(it, None)
        while cella is not None or any(c >= col for c in pendenti):
            if col in pendenti:
                c, resto = pendenti[col]
                out.append(c)
                if resto <= 1:
                    del pendenti[col]
                else:
                    pendenti[col] = (c, resto - 1)
                col += 1
                continue
            if cella is None:
                break
            for k in range(cella["cs"]):
                out.append(cella)
                if cella["rs"] > 1:
                    pendenti[col] = (cella, cella["rs"] - 1)
                col += 1
            cella = next(it, None)
        griglia.append(out)
    return griglia


def _data(testo):
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", testo or "")
    if m and m.group(2).lower() in _MESI:
        try:
            return datetime.date(int(m.group(3)), _MESI[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", testo or "")
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _pulisci_allenatore(testo):
    t = re.sub(r"\[[^\]]*\]", "", testo or "")
    interim = bool(re.search(r"caretaker|interim|ad interim|\(c\)", t, re.I))
    t = re.sub(r"\((caretaker|interim|ad interim|c)\)", "", t, flags=re.I)
    t = re.sub(r"\b(caretaker|interim)\b", "", t, flags=re.I)
    t = " ".join(t.replace("†", "").split()).strip(" ,;")
    if not t or norm(t) in ("tbd", "tba", "none", "vacant", "n a", "to be announced", "to be determined"):
        return None, interim
    return t, interim


def _col(intestazione, *parole):
    for i, h in enumerate(intestazione):
        hn = norm(h)
        if any(p in hn for p in parole):
            return i
    return None


def leggi_pagina_wiki(lega, anno):
    """
    Ritorna {"personale": [(squadra, link, allenatore)], "cambi": [dict]} per la
    stagione che inizia in `anno`. Le stagioni passate restano in cache per sempre.
    """
    stag = f"{anno}–{(anno + 1) % 100:02d}"
    corrente = anno >= anno_stagione()
    cache = _cartella("wiki", f"{norm(lega).replace(' ', '_')}_{anno}.json")
    if os.path.exists(cache) and not (corrente and (time.time() - os.path.getmtime(cache)) / 3600 > 6):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)

    html = None
    for modello in PAGINE_WIKI[lega]:
        titolo = modello.format(s=stag)
        url = ("https://en.wikipedia.org/w/api.php?action=parse&format=json&formatversion=2"
               "&prop=text&redirects=1&page=" + urllib.parse.quote(titolo))
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        dati = None
        for tentativo in range(5):
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    dati = json.loads(r.read().decode("utf-8"))
                time.sleep(0.3)          # cortesia verso Wikipedia
                break
            except Exception:
                time.sleep(3 + 4 * tentativo)
        if dati and "parse" in dati:
            html = dati["parse"]["text"]
            break
    if html is None:
        return {"personale": [], "cambi": [], "errore": True}

    p = _Tabelle()
    p.feed(html)
    personale, cambi = [], []
    for tab in p.tabelle:
        if not tab:
            continue
        g = _griglia(tab)
        # intestazione: prime righe composte da sole celle th
        inizio = 0
        while inizio < len(g) and g[inizio] and all(c["th"] for c in g[inizio]):
            inizio += 1
        if inizio == 0:
            continue
        intest = [" ".join(dict.fromkeys(g[r][i]["t"] for r in range(inizio) if i < len(g[r])))
                  for i in range(max(len(r) for r in g[:inizio]))]
        c_team = _col(intest, "team", "club")
        if c_team is None:
            continue
        c_out, c_in = _col(intest, "outgoing"), _col(intest, "incoming", "replaced by")
        if c_out is not None and c_in is not None:
            c_vac = _col(intest, "vacancy")
            c_app = _col(intest, "appointment")
            c_mod = _col(intest, "manner", "departure")
            for r in g[inizio:]:
                if len(r) <= max(c_team, c_out, c_in):
                    continue
                uscente, _ = _pulisci_allenatore(r[c_out]["t"])
                entrante, interim = _pulisci_allenatore(r[c_in]["t"])
                cambi.append({
                    "team": r[c_team]["t"], "link": (r[c_team]["links"] or [""])[0],
                    "uscente": uscente, "entrante": entrante, "interim": interim,
                    "vacanza": str(_data(r[c_vac]["t"])) if c_vac is not None and c_vac < len(r) and _data(r[c_vac]["t"]) else None,
                    "nomina": str(_data(r[c_app]["t"])) if c_app is not None and c_app < len(r) and _data(r[c_app]["t"]) else None,
                    "modo": r[c_mod]["t"] if c_mod is not None and c_mod < len(r) else "",
                })
            continue
        c_man = _col(intest, "manager", "head coach", "coach", "trainer")
        if c_man is not None and not personale:
            for r in g[inizio:]:
                if len(r) <= max(c_team, c_man):
                    continue
                nome, _ = _pulisci_allenatore(r[c_man]["t"])
                if nome and r[c_team]["t"]:
                    personale.append([r[c_team]["t"], (r[c_team]["links"] or [""])[0], nome])
    out = {"personale": personale, "cambi": cambi}
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return out


# ==================================================================
# CALENDARI E RISULTATI (fixturedownload.com + football-data.co.uk)
# ==================================================================

LEGHE_CALENDARIO = {
    "Serie A": "serie-a", "Premier League": "epl", "La Liga": "la-liga", "Bundesliga": "bundesliga",
    "Ligue 1": "ligue-1", "Eredivisie": "eredivisie", "Primeira Liga": "primeira-liga",
    "Süper Lig (Tur)": "super-lig", "Premiership (Sco)": "scottish-premiership",
    "Ligue 2": "ligue-2",
}


def json_calendario(slug, anno, max_ore):
    dati = scarica(f"https://fixturedownload.com/feed/json/{slug}-{anno}",
                   _cartella("calendari", f"{slug}_{anno}.json"), max_ore=max_ore)
    if not dati or not dati.lstrip().startswith(b"["):
        return []
    try:
        return json.loads(dati.decode("utf-8"))
    except ValueError:
        return []


def _ultima_domenica(anno, mese):
    d = (datetime.date(anno, mese + 1, 1) if mese < 12 else datetime.date(anno + 1, 1, 1)) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def ora_uk_a_utc(data, ora):
    """football-data scrive l'orario inglese: lo porto in UTC (ora legale britannica)."""
    try:
        hh, mm = (int(x) for x in (ora or "").split(":")[:2])
    except ValueError:
        hh, mm = 15, 0
    bst = _ultima_domenica(data.year, 3) <= data < _ultima_domenica(data.year, 10)
    dt = datetime.datetime(data.year, data.month, data.day, hh, mm) - datetime.timedelta(hours=1 if bst else 0)
    return dt.strftime("%Y-%m-%dT%H:%M:00Z")


def _t_utc(r):
    t = (r.get("DateUtc") or "")[:16].replace(" ", "T")
    return t + ":00Z" if len(t) == 16 else None


def partite_finestra(abbinatore, partite_db, giorni_prima=4, giorni_dopo=12):
    """
    Partite tra giorni_prima giorni fa e giorni_dopo giorni avanti, con il
    risultato quando è disponibile e le statistiche reali (tiri, angoli,
    cartellini, xG) quando football-data le ha già pubblicate.
    """
    oggi = datetime.date.today()
    da, a = oggi - datetime.timedelta(days=giorni_prima), oggi + datetime.timedelta(days=giorni_dopo)
    anno = anno_stagione()
    out, visti = [], set()
    stats = {(m["data"], m["casa"], m["ospite"]): m for m in partite_db
             if da - datetime.timedelta(days=2) <= m["data"] <= a}

    def aggiungi(comp, lega, t_utc, casa_raw, osp_raw, gc, go, giornata=None, gruppo=None):
        if lega:
            casa = abbinatore.trova(casa_raw, lega)
            osp = abbinatore.trova(osp_raw, lega)
        else:
            casa = abbinatore.trova(casa_raw, None, fuzzy=False)
            osp = abbinatore.trova(osp_raw, None, fuzzy=False)
        d = datetime.date.fromisoformat(t_utc[:10])
        k = (d, casa or abbinatore.nome_coppa(casa_raw), osp or abbinatore.nome_coppa(osp_raw))
        if k in visti:
            return
        visti.add(k)
        f = {"comp": comp, "t": t_utc, "c": casa or abbinatore.nome_coppa(casa_raw),
             "o": osp or abbinatore.nome_coppa(osp_raw)}
        if not casa:
            f["cx"] = 1          # squadra fuori dal database: rating solo dalle coppe (o assente)
        if not osp:
            f["ox"] = 1
        if giornata:
            f["g"] = giornata
        if gruppo:
            f["gr"] = gruppo
        if gc is not None and go is not None:
            f["r"] = [gc, go]
        for dd in (d, d - datetime.timedelta(days=1), d + datetime.timedelta(days=1)):
            m = stats.get((dd, casa, osp))
            if m:
                f["r"] = [m["gc"], m["go"]]
                st = {}
                for k2 in ("tiri", "tip", "cor", "cart", "ros", "fal", "xg"):
                    if m.get(k2 + "_c") is not None and m.get(k2 + "_o") is not None:
                        st[k2] = [m[k2 + "_c"], m[k2 + "_o"]]
                if st:
                    f["st"] = st
                break
        out.append(f)

    for lega, slug in LEGHE_CALENDARIO.items():
        for r in json_calendario(slug, anno, max_ore=3):
            t = _t_utc(r)
            if t and da <= datetime.date.fromisoformat(t[:10]) <= a:
                aggiungi(lega, lega, t, r.get("HomeTeam"), r.get("AwayTeam"),
                         r.get("HomeTeamScore"), r.get("AwayTeamScore"), r.get("RoundNumber"))
    for slug, nome in engine.COPPE_FD.items():
        for r in json_calendario(slug, anno, max_ore=3):
            t = _t_utc(r)
            if t and da <= datetime.date.fromisoformat(t[:10]) <= a:
                aggiungi(nome, None, t, r.get("HomeTeam"), r.get("AwayTeam"),
                         r.get("HomeTeamScore"), r.get("AwayTeamScore"), r.get("RoundNumber"), r.get("Group"))

    # campionati senza calendario completo: partite della settimana + risultati recenti
    import csv
    import io
    coperte = set(LEGHE_CALENDARIO)
    dati = scarica("https://football-data.co.uk/fixtures.csv", _cartella("calendari", "fixtures.csv"), max_ore=3)
    if dati:
        for r in csv.DictReader(io.StringIO(dati.decode("utf-8-sig", errors="replace"))):
            lega = engine.LEGHE_FD.get((r.get("Div") or "").strip())
            d = engine._parse_data(r.get("Date") or "")
            if not lega or lega in coperte or not d or not (da <= d <= a):
                continue
            casa = engine.FD_RENAME.get(r["HomeTeam"].strip(), r["HomeTeam"].strip())
            osp = engine.FD_RENAME.get(r["AwayTeam"].strip(), r["AwayTeam"].strip())
            aggiungi(lega, lega, ora_uk_a_utc(d, r.get("Time")), casa, osp, None, None)
    for m in partite_db:
        if m["lega"] not in coperte and da <= m["data"] <= oggi:
            aggiungi(m["lega"], m["lega"], m["data"].isoformat() + "T15:00:00Z", m["casa"], m["ospite"], m["gc"], m["go"])
    out.sort(key=lambda f: (f["t"], f["comp"], f["c"]))
    return out


def _unifica_nomi_coppa(ultimo_anno):
    """
    La stessa squadra di coppa compare con nomi diversi negli anni ("Shakhtar" /
    "Shakhtar Donetsk"). Le riunisco e tengo il nome della stagione più recente,
    che è quello mostrato dal calendario.
    """
    manuale = {}
    for gruppo in ALIAS_COPPE:
        for v in gruppo:
            manuale[v] = gruppo[0]
    gruppi = defaultdict(list)
    for raw, anno in ultimo_anno.items():
        gruppi[manuale.get(norm(raw), norm(raw))].append((anno, raw))
    for k in sorted(gruppi, key=len):
        parole = set(k.split())
        sopra = [k2 for k2 in gruppi if k2 != k and parole < set(k2.split())]
        if len(sopra) == 1 and len(k) >= 4:
            gruppi[sopra[0]].extend(gruppi.pop(k))
    mappa = {}
    for membri in gruppi.values():
        nome = max(membri)[1]
        for _, raw in membri:
            mappa[raw] = nome
    return mappa


def partite_coppe(abbinatore, anni):
    """Storico Champions/Europa/Conference con risultato e nomi abbinati al database."""
    righe = []
    ultimo_anno = {}
    corrente = anno_stagione()
    for slug, nome in engine.COPPE_FD.items():
        for anno in anni:
            for r in json_calendario(slug, anno, max_ore=3 if anno == corrente else None):
                casa_raw, osp_raw = r.get("HomeTeam") or "", r.get("AwayTeam") or ""
                casa = abbinatore.trova(casa_raw, None, fuzzy=False)
                osp = abbinatore.trova(osp_raw, None, fuzzy=False)
                for raw, ok in ((casa_raw, casa), (osp_raw, osp)):
                    if not ok and raw:
                        ultimo_anno[raw] = max(anno, ultimo_anno.get(raw, 0))
                gc, go = r.get("HomeTeamScore"), r.get("AwayTeamScore")
                if gc is None or go is None:
                    continue
                try:
                    d = datetime.date.fromisoformat(str(r.get("DateUtc", ""))[:10])
                except ValueError:
                    continue
                righe.append((nome, d, casa, casa_raw, osp, osp_raw, gc, go))
    abbinatore.alias_coppa = _unifica_nomi_coppa(ultimo_anno)
    out = [{"comp": comp, "data": d, "casa": casa or abbinatore.nome_coppa(cr),
            "ospite": osp or abbinatore.nome_coppa(orw), "gc": gc, "go": go}
           for comp, d, casa, cr, osp, orw, gc, go in righe]
    out.sort(key=lambda m: m["data"])
    return out
