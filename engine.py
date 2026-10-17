# -*- coding: utf-8 -*-
"""
================================================================================
 ⚽  ORACLE ENGINE v5.0 — Simulatore Predittivo di Partite di Calcio
================================================================================
 NOVITÀ v5.0
   • 11 CAMPIONATI EUROPEI: Serie A, Premier League, La Liga, Bundesliga,
     Ligue 1, Primeira Liga, Eredivisie, Pro League belga, Süper Lig turca,
     Super League greca, Premiership scozzese — 10 stagioni di partite vere
     (risultati, corner, cartellini) da football-data.co.uk, pesate col
     decadimento temporale di Dixon-Coles. Se internet manca, database
     interno di riserva.
   • WEBAPP PER IL TELEFONO: all'avvio scegli l'opzione 2 e il programma
     genera "oracle_webapp.html", un'app colorata (stemmi, barre animate,
     schede squadra coi numeri veri) che funziona su Android anche offline.
     Gli allenatori si modificano direttamente nell'app e il telefono li
     ricorda. Rigenera il file quando vuoi dati freschi.
   • SCHEDA NUMERI REALI per ogni squadra: media gol fatti/subiti, % Over
     2.5, % Gol/Gol, risultati più frequenti, gialli e rossi a partita.
   • ASSENZE CHIAVE: segnala 0-3 assenze pesanti per squadra; il modello
     riduce attacco e solidità di conseguenza.
   • ALLENATORE INSERIBILE: l'identità tattica è dell'allenatore e se la
     porta dietro (archivio ~100 tecnici; i nuovi si registrano dal menu).

 MOTORE QUANTITATIVO
   1. Poisson bivariata + matrice di transizione dei punteggi (0-9 gol)
   2. Correzione DIXON-COLES (rho per lega) su 0-0, 1-0, 0-1, 1-1
   3. Rating attacco/difesa calcolati dalle partite reali con decadimento
      temporale + regressione verso la media (shrinkage bayesiano)
   4. MATRICE TATTICA: stile dell'allenatore → coefficiente di attrito
   5. Corner e cartellini CORRELATI all'andamento di ogni simulazione
   6. Monte Carlo: 10.000 simulazioni per match

 FONTE DATI: https://www.football-data.co.uk (CSV pubblici e gratuiti).
   Risultati, corner e cartellini reali per tutte e 6 le leghe. Se per
   qualche squadra/lega mancassero corner o cartellini, il modello li
   stima dal profilo di lega e lo segnala nel report.
   Per aggiungere altri campionati basta una riga in LEGHE_FD (codici sul
   sito: N1 Eredivisie, B1 Pro League belga, T1 Süper Lig, G1 Grecia...).
   Per più storia, alza N_STAGIONI.

 USO: esegui → Squadra Casa → allenatore → Squadra Ospite → allenatore.
      Scrivi "lista" per vedere tutte le squadre disponibili.

 ⚠️  Modello probabilistico a scopo informativo/educativo.
     Nessuna previsione è una certezza. Gioca responsabilmente (18+).
================================================================================
"""

import csv
import datetime
import difflib
import io
import json
import math
import os
import random
import sys
import unicodedata
import time
import urllib.request
from collections import Counter, defaultdict
from statistics import median, mean

try:  # garantisce l'output UTF-8 anche su terminali Windows
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ------------------------------------------------------------------
# CONFIGURAZIONE MOTORE
# ------------------------------------------------------------------
N_SIMULAZIONI = 10_000    # iterazioni Monte Carlo
MAX_GOL       = 9         # matrice punteggi 0..9 gol per squadra
DISP_CORNER   = 9.0       # dispersione neg-binomiale corner
DISP_CART     = 7.0       # dispersione neg-binomiale cartellini (varianza arbitrale)
N_STAGIONI    = 10        # quante stagioni di storia scaricare
DECADIMENTO   = 0.50      # peso temporale: una partita di un anno fa vale la metà di una di oggi
                          # (scelto con la verifica sul passato in taratura.py: 1 anno batte 3 anni e 3 mesi)
K_SHRINK      = 6.0       # regressione verso la media (partite "virtuali" neutre)
CARTELLA_CACHE = os.environ.get("ORACLE_CACHE", "cache_dati_calcio")   # i CSV scaricati restano qui

# Coppe europee: slug fixturedownload.com → nome (solo risultati; angoli e
# cartellini non pubblicati → stimati dai profili di lega, dichiarato nel report)
COPPE_FD = {
    "champions-league": "Champions League",
    "europa-league": "Europa League",
    "conference-league": "Conference League",
}

# Campionati da scaricare: codice football-data.co.uk → nome lega
LEGHE_FD = {
    "I1":  "Serie A",
    "E0":  "Premier League",
    "SP1": "La Liga",
    "D1":  "Bundesliga",
    "F1":  "Ligue 1",
    "P1":  "Primeira Liga",
    "N1":  "Eredivisie",
    "B1":  "Pro League (Bel)",
    "T1":  "Süper Lig (Tur)",
    "G1":  "Super League (Gre)",
    "SC0": "Premiership (Sco)",
    "SP2": "Liga 2",
    "F2":  "Ligue 2",
}

# Campionati letti SOLO per lo storico (carriera degli allenatori, squadre neopromosse):
# le loro partite non compaiono nell'app
LEGHE_STORIA = {
    "I2":  "Serie B",
    "E1":  "Championship",
    "D2":  "2. Bundesliga",
}

# seconde divisioni e prima divisione dello stesso paese (per le squadre promosse/retrocesse)
SECONDE = {"Liga 2": "La Liga", "Ligue 2": "Ligue 1", "Serie B": "Serie A",
           "Championship": "Premier League", "2. Bundesliga": "Bundesliga"}

# Traduzione nomi football-data → nomi canonici del simulatore
FD_RENAME = {
    "Man City": "Manchester City", "Man United": "Manchester United",
    "Nott'm Forest": "Nottingham Forest", "Wolves": "Wolverhampton",
    "Ath Madrid": "Atletico Madrid", "Ath Bilbao": "Athletic Bilbao",
    "Barcelona": "Barcellona", "Sevilla": "Siviglia", "Sociedad": "Real Sociedad",
    "Celta": "Celta Vigo", "Vallecano": "Rayo Vallecano", "Espanol": "Espanyol",
    "Bayern Munich": "Bayern Monaco", "Dortmund": "Borussia Dortmund",
    "RB Leipzig": "Lipsia", "Leverkusen": "Bayer Leverkusen",
    "Ein Frankfurt": "Eintracht Francoforte", "Stuttgart": "Stoccarda",
    "Freiburg": "Friburgo", "M'gladbach": "Borussia M'gladbach",
    "Koln": "Colonia", "FC Koln": "Colonia", "Werder Bremen": "Werder Brema",
    "Hamburg": "Amburgo",
    "Paris SG": "PSG", "Marseille": "Marsiglia", "Lyon": "Lione",
    "Nice": "Nizza", "St Etienne": "Saint-Étienne",
    "Sp Lisbon": "Sporting Lisbona", "Sp Braga": "Braga",
    "Guimaraes": "Vitória Guimarães", "Famalicao": "Famalicão",
    "Pacos Ferreira": "Paços de Ferreira", "Estrela": "Estrela Amadora",
    "PSV Eindhoven": "PSV", "For Sittard": "Fortuna Sittard",
    "Nijmegen": "NEC Nijmegen", "Waalwijk": "RKC Waalwijk",
    "Groningen": "FC Groningen", "Utrecht": "FC Utrecht", "Twente": "FC Twente",
    "St Gilloise": "Union Saint-Gilloise", "Union St Gilloise": "Union Saint-Gilloise",
    "St Truiden": "Sint-Truiden", "Club Brugge": "Club Brugge",
    "Fenerbahce": "Fenerbahçe", "Besiktas": "Beşiktaş",
    "Buyuksehyr": "Başakşehir", "Basaksehir": "Başakşehir",
    "Karagumruk": "Fatih Karagümrük", "Goztep": "Göztepe", "Goztepe": "Göztepe",
    "St. Gilloise": "Union Saint-Gilloise", "Santander": "Racing Santander",
    "La Coruna": "Deportivo La Coruña", "Den Haag": "ADO Den Haag", "Zwolle": "PEC Zwolle",
    "RAAL La Louviere": "La Louvière", "Ad. Demirspor": "Adana Demirspor",
    "Sp Gijon": "Sporting Gijón", "Cordoba": "Córdoba", "Cadiz": "Cádiz", "Malaga": "Málaga",
    "Mirandes": "Mirandés", "Castellon": "Castellón", "Leganes": "Leganés", "Alcorcon": "Alcorcón",
    "Nimes": "Nîmes", "Chateauroux": "Châteauroux", "Orleans": "Orléans", "Beziers": "Béziers",
}

# Parametro rho di Dixon-Coles per lega (più negativo = più 0-0 e 1-1)
RHO_LEGA = {
    "Serie A": -0.13, "Premier League": -0.08, "La Liga": -0.11,
    "Bundesliga": -0.06, "Ligue 1": -0.10, "Primeira Liga": -0.11,
    "Eredivisie": -0.06, "Pro League (Bel)": -0.08, "Süper Lig (Tur)": -0.10,
    "Super League (Gre)": -0.12, "Premiership (Sco)": -0.09,
    "Liga 2": -0.12, "Ligue 2": -0.11, "Serie B": -0.12, "Championship": -0.09, "2. Bundesliga": -0.07,
}
RHO_DEFAULT = -0.10

# Costanti di lega di RISERVA (usate se internet non è disponibile,
# o per corner/cartellini dove la fonte non li fornisce)
FALLBACK_LEGHE = {
    "Serie A":        {"gol_casa": 1.42, "gol_trasferta": 1.13, "corner": 9.9,  "cart": 4.9},
    "Premier League": {"gol_casa": 1.62, "gol_trasferta": 1.35, "corner": 10.4, "cart": 4.3},
    "La Liga":        {"gol_casa": 1.48, "gol_trasferta": 1.15, "corner": 9.6,  "cart": 5.1},
    "Bundesliga":     {"gol_casa": 1.68, "gol_trasferta": 1.40, "corner": 9.8,  "cart": 3.9},
    "Ligue 1":        {"gol_casa": 1.53, "gol_trasferta": 1.22, "corner": 9.7,  "cart": 4.6},
    "Primeira Liga":  {"gol_casa": 1.52, "gol_trasferta": 1.18, "corner": 9.8,  "cart": 5.5},
    "Eredivisie":         {"gol_casa": 1.75, "gol_trasferta": 1.40, "corner": 10.2, "cart": 4.0},
    "Pro League (Bel)":   {"gol_casa": 1.60, "gol_trasferta": 1.30, "corner": 10.0, "cart": 4.4},
    "Süper Lig (Tur)":    {"gol_casa": 1.55, "gol_trasferta": 1.25, "corner": 10.2, "cart": 5.3},
    "Super League (Gre)": {"gol_casa": 1.45, "gol_trasferta": 1.05, "corner": 9.5,  "cart": 5.6},
    "Premiership (Sco)":  {"gol_casa": 1.55, "gol_trasferta": 1.25, "corner": 10.0, "cart": 4.0},
    "Liga 2":             {"gol_casa": 1.30, "gol_trasferta": 0.95, "corner": 9.4,  "cart": 5.2},
    "Ligue 2":            {"gol_casa": 1.40, "gol_trasferta": 1.05, "corner": 9.5,  "cart": 4.4},
    "Serie B":            {"gol_casa": 1.35, "gol_trasferta": 1.05, "corner": 9.6,  "cart": 5.0},
    "Championship":       {"gol_casa": 1.45, "gol_trasferta": 1.15, "corner": 10.3, "cart": 4.0},
    "2. Bundesliga":      {"gol_casa": 1.60, "gol_trasferta": 1.30, "corner": 9.8,  "cart": 4.2},
}

# ------------------------------------------------------------------
# MATRICE TATTICA — attributi di ogni identità di gioco
# ------------------------------------------------------------------
STYLES = {
    "Gegenpressing":        {"tempo": 1.12, "pressing": 1.20, "linea": 1.15, "possesso": 1.02, "verticalita": 1.05},
    "Pressing Alto":        {"tempo": 1.08, "pressing": 1.12, "linea": 1.10, "possesso": 1.03, "verticalita": 1.00},
    "Uomo su Uomo":         {"tempo": 1.10, "pressing": 1.18, "linea": 1.12, "possesso": 1.00, "verticalita": 1.06},
    "Possesso Posizionale": {"tempo": 0.98, "pressing": 1.05, "linea": 1.10, "possesso": 1.15, "verticalita": 0.90},
    "Verticale":            {"tempo": 1.06, "pressing": 1.00, "linea": 1.00, "possesso": 0.97, "verticalita": 1.15},
    "Blocco Medio":         {"tempo": 0.97, "pressing": 0.95, "linea": 0.95, "possesso": 0.98, "verticalita": 1.05},
    "Equilibrato":          {"tempo": 1.00, "pressing": 1.00, "linea": 1.00, "possesso": 1.00, "verticalita": 1.00},
    "Blocco Basso":         {"tempo": 0.90, "pressing": 0.85, "linea": 0.85, "possesso": 0.90, "verticalita": 1.10},
}
LISTA_STILI = list(STYLES)   # ordine fisso per il menu di scelta

DESCR_STILE = {
    "Gegenpressing":        "riaggressione immediata dopo la perdita del pallone e recuperi altissimi",
    "Pressing Alto":        "pressione organizzata sulla prima costruzione avversaria",
    "Uomo su Uomo":         "marcature a uomo a tutto campo e duelli individuali continui",
    "Possesso Posizionale": "dominio del pallone e occupazione razionale degli spazi",
    "Verticale":            "transizioni rapide e attacco immediato della profondità",
    "Blocco Medio":         "compattezza a metà campo e ripartenze organizzate",
    "Equilibrato":          "approccio flessibile che si adatta all'avversario",
    "Blocco Basso":         "difesa posizionale bassa e rinuncia al possesso",
}

# ------------------------------------------------------------------
# ARCHIVIO ALLENATORI — l'identità di gioco segue il tecnico
# (se un allenatore manca, il programma fa scegliere lo stile dal menu)
# ------------------------------------------------------------------
COACHES = {
    # --- Italia ---
    "Cristian Chivu": "Verticale",           "Antonio Conte": "Blocco Medio",
    "Massimiliano Allegri": "Blocco Basso",  "Luciano Spalletti": "Possesso Posizionale",
    "Gian Piero Gasperini": "Uomo su Uomo",  "Raffaele Palladino": "Pressing Alto",
    "Maurizio Sarri": "Possesso Posizionale","Vincenzo Italiano": "Pressing Alto",
    "Paolo Vanoli": "Blocco Medio",          "Cesc Fàbregas": "Possesso Posizionale",
    "Marco Baroni": "Equilibrato",           "Kosta Runjaić": "Verticale",
    "Daniele De Rossi": "Blocco Medio",      "Fabio Pisacane": "Blocco Basso",
    "Eusebio Di Francesco": "Pressing Alto", "Paolo Zanetti": "Blocco Basso",
    "Carlos Cuesta": "Blocco Medio",         "Fabio Grosso": "Equilibrato",
    "Alberto Gilardino": "Blocco Basso",     "Davide Nicola": "Blocco Basso",
    "Simone Inzaghi": "Verticale",           "Filippo Inzaghi": "Verticale",
    "Stefano Pioli": "Equilibrato",          "Thiago Motta": "Possesso Posizionale",
    "Igor Tudor": "Uomo su Uomo",            "Ivan Juric": "Uomo su Uomo",
    "Claudio Ranieri": "Blocco Medio",       "Roberto Mancini": "Possesso Posizionale",
    "Walter Mazzarri": "Blocco Basso",       "Alessandro Nesta": "Equilibrato",
    "Marco Giampaolo": "Possesso Posizionale","Leonardo Semplici": "Blocco Basso",
    "Davide Ballardini": "Blocco Basso",     "Roberto D'Aversa": "Blocco Medio",
    "Patrick Vieira": "Possesso Posizionale","Gennaro Gattuso": "Pressing Alto",
    "Luca Gotti": "Blocco Medio",            "Roberto De Zerbi": "Possesso Posizionale",
    # --- Inghilterra / internazionali ---
    "Mikel Arteta": "Possesso Posizionale",  "Pep Guardiola": "Possesso Posizionale",
    "Arne Slot": "Gegenpressing",            "Enzo Maresca": "Possesso Posizionale",
    "Ruben Amorim": "Verticale",             "Thomas Frank": "Blocco Medio",
    "Eddie Howe": "Pressing Alto",           "Unai Emery": "Equilibrato",
    "Fabian Hürzeler": "Possesso Posizionale","Oliver Glasner": "Blocco Medio",
    "Andoni Iraola": "Gegenpressing",        "Keith Andrews": "Verticale",
    "Marco Silva": "Equilibrato",            "Nuno Espírito Santo": "Blocco Basso",
    "David Moyes": "Blocco Basso",           "Sean Dyche": "Blocco Basso",
    "Rob Edwards": "Blocco Basso",           "Scott Parker": "Blocco Basso",
    "Daniel Farke": "Pressing Alto",         "Régis Le Bris": "Blocco Medio",
    "Jürgen Klopp": "Gegenpressing",         "Ange Postecoglou": "Pressing Alto",
    "Graham Potter": "Possesso Posizionale", "José Mourinho": "Blocco Medio",
    "Carlo Ancelotti": "Equilibrato",        "Zinédine Zidane": "Equilibrato",
    "Thomas Tuchel": "Pressing Alto",        "Julian Nagelsmann": "Pressing Alto",
    "Erik ten Hag": "Possesso Posizionale",
    # --- Spagna ---
    "Xabi Alonso": "Verticale",              "Hansi Flick": "Possesso Posizionale",
    "Diego Simeone": "Blocco Medio",         "Ernesto Valverde": "Pressing Alto",
    "Marcelino": "Equilibrato",              "Sergio Francisco": "Possesso Posizionale",
    "Manuel Pellegrini": "Possesso Posizionale", "Matías Almeyda": "Equilibrato",
    "Carlos Corberán": "Blocco Basso",       "Míchel": "Possesso Posizionale",
    "Xavi Hernández": "Possesso Posizionale",
    # --- Germania ---
    "Vincent Kompany": "Gegenpressing",      "Kasper Hjulmand": "Possesso Posizionale",
    "Niko Kovač": "Blocco Medio",            "Ole Werner": "Verticale",
    "Sebastian Hoeneß": "Pressing Alto",     "Dino Toppmöller": "Verticale",
    "Julian Schuster": "Equilibrato",        "Eugen Polanski": "Equilibrato",
    "Marco Rose": "Gegenpressing",           "Edin Terzić": "Verticale",
    # --- Francia ---
    "Luis Enrique": "Possesso Posizionale",  "Sébastien Pocognoli": "Verticale",
    "Paulo Fonseca": "Possesso Posizionale", "Bruno Genesio": "Equilibrato",
    "Franck Haise": "Blocco Medio",          "Will Still": "Pressing Alto",
    # --- Portogallo ---
    "Francesco Farioli": "Possesso Posizionale", "Rui Borges": "Pressing Alto",
    "Carlos Vicens": "Pressing Alto",        "Bruno Lage": "Possesso Posizionale",
    "Sérgio Conceição": "Verticale",         "Abel Ferreira": "Blocco Medio",
    "Jorge Jesus": "Possesso Posizionale",
    # --- Olanda / Belgio / Turchia / Grecia / Scozia ---
    "Peter Bosz": "Pressing Alto",           "Robin van Persie": "Pressing Alto",
    "John Heitinga": "Possesso Posizionale", "Ruud van Nistelrooy": "Equilibrato",
    "Okan Buruk": "Equilibrato",             "Domenico Tedesco": "Possesso Posizionale",
    "Sergen Yalçın": "Equilibrato",          "José Luis Mendilibar": "Pressing Alto",
    "Rafa Benítez": "Blocco Medio",          "Răzvan Lucescu": "Equilibrato",
    "Brendan Rodgers": "Possesso Posizionale", "Danny Röhl": "Pressing Alto",
    "Steven Gerrard": "Equilibrato",         "Vítor Pereira": "Equilibrato",
    # --- nuove panchine 2026-27 (verificate) ---
    "Ignazio Abate": "Equilibrato",          "Giovanni Stroppa": "Equilibrato",
    "Massimiliano Alvini": "Pressing Alto",
}

# ------------------------------------------------------------------
# STORICO PANCHINE DOCUMENTATO (solo periodi certi, nei campionati coperti)
# Serve a calcolare i NUMERI VERI di ogni allenatore incrociandoli con le
# partite reali scaricate. Formato: (squadra, da "AAAA-MM", a "AAAA-MM" o ""
# = ancora in carica). Se un periodo non è certo, NON è in elenco: il
# programma non inventa mai dati.
# ------------------------------------------------------------------
COACH_HISTORY = {
    "Massimiliano Allegri": [("Juventus","2016-08","2019-06"),("Juventus","2021-08","2024-06"),("Milan","2025-07","2026-06"),("Napoli","2026-07","")],
    "Maurizio Sarri": [("Napoli","2016-08","2018-06"),("Chelsea","2018-08","2019-06"),("Juventus","2019-08","2020-08"),("Lazio","2021-08","2024-03"),("Lazio","2025-07","2026-06"),("Atalanta","2026-07","")],
    "Antonio Conte": [("Chelsea","2016-08","2018-06"),("Inter","2019-08","2021-06"),("Tottenham","2021-11","2023-03"),("Napoli","2024-07","2026-06")],
    "Ruben Amorim": [("Sporting Lisbona","2020-03","2024-11"),("Manchester United","2024-11","2026-06"),("Milan","2026-07","")],
    "Gennaro Gattuso": [("Milan","2017-11","2019-06"),("Napoli","2019-12","2021-06"),("Valencia","2022-07","2023-01"),("Marsiglia","2023-09","2024-02"),("Lazio","2026-07","")],
    "Pep Guardiola": [("Manchester City","2016-08","")],
    "Mikel Arteta": [("Arsenal","2019-12","")],
    "Carlo Ancelotti": [("Bayern Monaco","2016-08","2017-09"),("Napoli","2018-07","2019-12"),("Everton","2019-12","2021-06"),("Real Madrid","2021-07","2025-05")],
    "Jürgen Klopp": [("Liverpool","2016-08","2024-06")],
    "Arne Slot": [("Feyenoord","2021-07","2024-06"),("Liverpool","2024-07","")],
    "Diego Simeone": [("Atletico Madrid","2016-08","")],
    "Zinédine Zidane": [("Real Madrid","2016-08","2018-06"),("Real Madrid","2019-03","2021-06")],
    "José Mourinho": [("Manchester United","2016-08","2018-12"),("Tottenham","2019-11","2021-04"),("Roma","2021-07","2024-01"),("Fenerbahçe","2024-07","2025-08"),("Benfica","2025-09","")],
    "Luciano Spalletti": [("Roma","2016-08","2017-06"),("Inter","2017-07","2019-06"),("Napoli","2021-07","2023-06"),("Juventus","2025-10","")],
    "Gian Piero Gasperini": [("Atalanta","2016-08","2025-06"),("Roma","2025-07","")],
    "Simone Inzaghi": [("Lazio","2016-08","2021-06"),("Inter","2021-07","2025-06")],
    "Cristian Chivu": [("Parma","2025-02","2025-06"),("Inter","2025-07","")],
    "Stefano Pioli": [("Inter","2016-11","2017-05"),("Fiorentina","2017-07","2019-04"),("Milan","2019-10","2024-06"),("Fiorentina","2025-07","2025-11")],
    "Vincenzo Italiano": [("Spezia","2020-08","2021-06"),("Fiorentina","2021-07","2024-06"),("Bologna","2024-07","2026-06")],
    "Domenico Tedesco": [("Lipsia","2021-12","2022-09"),("Fenerbahçe","2025-09","2026-06"),("Bologna","2026-07","")],
    "Thiago Motta": [("Spezia","2021-08","2022-06"),("Bologna","2022-09","2024-06"),("Juventus","2024-07","2025-03")],
    "Igor Tudor": [("Verona","2021-09","2022-06"),("Marsiglia","2022-07","2023-06"),("Lazio","2024-03","2024-06"),("Juventus","2025-03","2025-10")],
    "Ivan Juric": [("Verona","2019-07","2021-06"),("Torino","2021-07","2024-06"),("Roma","2024-09","2024-11"),("Atalanta","2025-07","2025-11")],
    "Roberto De Zerbi": [("Sassuolo","2018-07","2021-06"),("Brighton","2022-09","2024-06"),("Marsiglia","2024-07","")],
    "Eddie Howe": [("Bournemouth","2016-08","2020-08"),("Newcastle","2021-11","")],
    "Unai Emery": [("PSG","2016-08","2018-06"),("Arsenal","2018-08","2019-11"),("Villarreal","2020-07","2022-10"),("Aston Villa","2022-11","")],
    "Erik ten Hag": [("Ajax","2018-01","2022-06"),("Manchester United","2022-07","2024-10"),("Bayer Leverkusen","2025-07","2025-09")],
    "Enzo Maresca": [("Chelsea","2024-07","")],
    "Thomas Frank": [("Brentford","2021-08","2025-06"),("Tottenham","2025-07","")],
    "Oliver Glasner": [("Eintracht Francoforte","2021-07","2023-06"),("Crystal Palace","2024-02","")],
    "Xabi Alonso": [("Bayer Leverkusen","2022-10","2025-06"),("Real Madrid","2025-07","")],
    "Hansi Flick": [("Bayern Monaco","2019-11","2021-06"),("Barcellona","2024-07","")],
    "Vincent Kompany": [("Burnley","2023-08","2024-06"),("Bayern Monaco","2024-07","")],
    "Niko Kovač": [("Eintracht Francoforte","2016-08","2018-06"),("Bayern Monaco","2018-07","2019-11"),("Monaco","2020-08","2022-01"),("Borussia Dortmund","2025-02","")],
    "Julian Nagelsmann": [("Lipsia","2019-07","2021-06"),("Bayern Monaco","2021-07","2023-03")],
    "Thomas Tuchel": [("Borussia Dortmund","2016-08","2017-06"),("PSG","2018-07","2020-12"),("Chelsea","2021-01","2022-09"),("Bayern Monaco","2023-03","2024-06")],
    "Luis Enrique": [("PSG","2023-07","")],
    "Paulo Fonseca": [("Roma","2019-07","2021-06"),("Lille","2022-07","2024-06"),("Milan","2024-07","2024-12"),("Lione","2025-01","")],
    "Sérgio Conceição": [("Porto","2017-07","2024-06"),("Milan","2024-12","2025-06")],
    "Francesco Farioli": [("Nizza","2023-07","2024-06"),("Ajax","2024-07","2025-05"),("Porto","2025-07","")],
    "Marco Rose": [("Borussia M'gladbach","2019-07","2021-06"),("Borussia Dortmund","2021-07","2022-06"),("Lipsia","2022-09","2025-03")],
    "Ange Postecoglou": [("Celtic","2021-07","2023-06"),("Tottenham","2023-07","2025-06"),("Nottingham Forest","2025-09","2025-10")],
    "Brendan Rodgers": [("Celtic","2016-08","2019-02"),("Leicester","2019-03","2023-04"),("Celtic","2023-07","2025-10")],
    "Graham Potter": [("Brighton","2019-07","2022-09"),("Chelsea","2022-09","2023-04"),("West Ham","2025-01","2025-09")],
    "David Moyes": [("Sunderland","2016-08","2017-05"),("West Ham","2017-11","2018-05"),("West Ham","2019-12","2024-06"),("Everton","2025-01","")],
    "Sean Dyche": [("Burnley","2016-08","2022-04"),("Everton","2023-01","2025-01"),("Nottingham Forest","2025-10","")],
    "Nuno Espírito Santo": [("Porto","2016-08","2017-06"),("Wolverhampton","2018-08","2021-06"),("Tottenham","2021-08","2021-11"),("Nottingham Forest","2023-12","2025-09"),("West Ham","2025-09","")],
    "Marco Silva": [("Everton","2018-07","2019-12"),("Fulham","2022-08","")],
    "Andoni Iraola": [("Rayo Vallecano","2021-08","2023-06"),("Bournemouth","2023-07","")],
    "Ernesto Valverde": [("Athletic Bilbao","2016-08","2017-06"),("Barcellona","2017-08","2020-01"),("Athletic Bilbao","2022-07","")],
    "Manuel Pellegrini": [("West Ham","2018-07","2019-12"),("Betis","2020-08","")],
    "Míchel": [("Girona","2022-08","")],
    "Marcelino": [("Valencia","2017-07","2019-09"),("Athletic Bilbao","2021-01","2022-06"),("Villarreal","2023-11","")],
    "Xavi Hernández": [("Barcellona","2021-11","2024-06")],
    "Okan Buruk": [("Galatasaray","2022-07","")],
    "Fabian Hürzeler": [("Brighton","2024-07","")],
    "Kasper Hjulmand": [("Bayer Leverkusen","2025-09","")],
    "Ole Werner": [("Werder Brema","2022-01","2025-06"),("Lipsia","2025-07","")],
    "Sebastian Hoeneß": [("Stoccarda","2023-04","")],
    "Dino Toppmöller": [("Eintracht Francoforte","2023-07","")],
    "Bruno Genesio": [("Lione","2016-08","2019-06"),("Lille","2024-07","")],
    "Franck Haise": [("Lens","2020-02","2024-06"),("Nizza","2024-07","")],
    "Will Still": [("Reims","2022-10","2024-05"),("Lens","2024-07","2025-06")],
    "Régis Le Bris": [("Lorient","2022-08","2024-06"),("Sunderland","2025-08","")],
    "Daniel Farke": [("Norwich","2019-08","2020-06"),("Norwich","2021-08","2021-11"),("Borussia M'gladbach","2022-07","2023-06"),("Leeds","2025-08","")],
    "Scott Parker": [("Fulham","2019-02","2021-06"),("Burnley","2025-08","")],
    "Rob Edwards": [("Luton","2023-08","2024-06"),("Wolverhampton","2025-11","")],
    "Keith Andrews": [("Brentford","2025-07","")],
    "Eugen Polanski": [("Borussia M'gladbach","2025-09","")],
    "Julian Schuster": [("Friburgo","2024-07","")],
    "Peter Bosz": [("Ajax","2016-08","2017-06"),("Borussia Dortmund","2017-07","2017-12"),("Bayer Leverkusen","2019-01","2021-03"),("Lione","2021-08","2022-10"),("PSV","2023-07","")],
    "Robin van Persie": [("Heerenveen","2024-07","2025-02"),("Feyenoord","2025-02","")],
    "John Heitinga": [("Ajax","2023-01","2023-06"),("Ajax","2025-07","2025-11")],
    "Rui Borges": [("Vitória Guimarães","2024-07","2024-12"),("Sporting Lisbona","2024-12","")],
    "Bruno Lage": [("Benfica","2019-01","2020-06"),("Wolverhampton","2021-08","2022-10"),("Benfica","2024-09","2025-09")],
    "Jorge Jesus": [("Sporting Lisbona","2016-08","2018-06"),("Benfica","2020-08","2021-12")],
    "Abel Ferreira": [("Braga","2017-07","2019-12"),("PAOK","2020-01","2020-10")],
    "Carlos Vicens": [("Braga","2025-07","")],
    "Vítor Pereira": [("Wolverhampton","2024-12","2025-11")],
    "Danny Röhl": [("Rangers","2025-11","")],
    "Rafa Benítez": [("Newcastle","2017-08","2019-06"),("Everton","2021-07","2022-01"),("Celta Vigo","2023-07","2024-03"),("Panathinaikos","2025-02","")],
    "Eusebio Di Francesco": [("Sassuolo","2016-08","2017-06"),("Roma","2017-07","2019-03"),("Cagliari","2020-08","2021-02"),("Frosinone","2023-07","2024-06"),("Venezia","2024-07","2025-06"),("Lecce","2025-07","")],
    "Marco Baroni": [("Lecce","2022-08","2023-06"),("Verona","2023-08","2024-06"),("Lazio","2024-07","2025-06"),("Torino","2025-07","2026-06")],
    "Paolo Vanoli": [("Torino","2024-07","2025-06"),("Fiorentina","2025-11","2026-06")],
    "Daniele De Rossi": [("Roma","2024-01","2024-09"),("Genoa","2025-11","")],
    "Davide Nicola": [("Crotone","2016-08","2017-06"),("Udinese","2019-11","2020-03"),("Genoa","2020-12","2021-06"),("Salernitana","2022-02","2023-02"),("Empoli","2024-07","2025-06"),("Cremonese","2025-07","")],
    "Cesc Fàbregas": [("Como","2024-07","")],
    "Raffaele Palladino": [("Monza","2022-09","2024-06"),("Fiorentina","2024-07","2025-06"),("Atalanta","2025-11","2026-06")],
    "Alberto Gilardino": [("Genoa","2022-12","2024-11"),("Pisa","2025-07","")],
    "Fabio Grosso": [("Sassuolo","2025-07","2026-06"),("Fiorentina","2026-07","")],
    "Kosta Runjaić": [("Udinese","2024-07","")],
    "Sébastien Pocognoli": [("Union Saint-Gilloise","2024-07","2025-10"),("Monaco","2025-10","")],
    "Sergio Francisco": [("Real Sociedad","2025-07","")],
    "Matías Almeyda": [("Siviglia","2025-07","")],
    "Carlos Corberán": [("Valencia","2024-12","")],
    "Carlos Cuesta": [("Parma","2025-07","")],
    "Fabio Pisacane": [("Cagliari","2025-07","")],
    "Paolo Zanetti": [("Venezia","2021-08","2022-06"),("Empoli","2022-07","2023-10"),("Verona","2024-07","")],
}

# ------------------------------------------------------------------
# IDENTITÀ SQUADRE + DATABASE DI RISERVA (snapshot 2025-26)
# Fornisce: allenatore di default (modificabile all'avvio) e statistiche
# di riserva se il download dei dati reali non è possibile.
# ------------------------------------------------------------------
T = lambda lega, all_, stile, att, dif, cp, cc, cart, aggr: {
    "lega": lega, "allenatore": all_, "stile": stile, "att": att, "dif": dif,
    "cor_pro": cp, "cor_con": cc, "cart": cart, "aggr": aggr,
}

TEAMS = {
    # ---------------- SERIE A ----------------
    "Inter":            T("Serie A", "Cristian Chivu",      "Verticale",            1.35, 0.72, 6.2, 4.0, 1.9, 0.90),
    "Napoli":           T("Serie A", "Massimiliano Allegri","Blocco Basso",         1.18, 0.72, 5.8, 4.2, 2.1, 1.00),
    "Milan":            T("Serie A", "Ruben Amorim",        "Verticale",            1.12, 0.78, 5.0, 4.8, 2.0, 0.95),
    "Juventus":         T("Serie A", "Luciano Spalletti",   "Possesso Posizionale", 1.08, 0.82, 5.6, 4.4, 2.0, 0.95),
    "Roma":             T("Serie A", "Gian Piero Gasperini","Uomo su Uomo",         1.12, 0.78, 5.7, 4.5, 2.2, 1.10),
    "Atalanta":         T("Serie A", "Maurizio Sarri",      "Possesso Posizionale", 1.08, 0.92, 5.8, 4.6, 2.1, 1.05),
    "Lazio":            T("Serie A", "Gennaro Gattuso",     "Pressing Alto",        0.98, 0.88, 5.3, 4.7, 2.2, 1.05),
    "Bologna":          T("Serie A", "Domenico Tedesco",    "Possesso Posizionale", 1.05, 0.88, 5.6, 4.5, 2.0, 1.00),
    "Fiorentina":       T("Serie A", "Fabio Grosso",        "Equilibrato",          0.88, 1.05, 4.9, 5.2, 2.3, 1.10),
    "Como":             T("Serie A", "Cesc Fàbregas",       "Possesso Posizionale", 1.00, 0.98, 5.5, 4.9, 2.1, 1.00),
    "Torino":           T("Serie A", "Ignazio Abate",       "Equilibrato",          0.82, 0.98, 4.7, 5.1, 2.1, 1.00),
    "Udinese":          T("Serie A", "Kosta Runjaić",       "Verticale",            0.85, 1.05, 4.6, 5.3, 2.2, 1.10),
    "Genoa":            T("Serie A", "Daniele De Rossi",    "Blocco Medio",         0.78, 1.02, 4.5, 5.2, 2.2, 1.05),
    "Cagliari":         T("Serie A", "Fabio Pisacane",      "Blocco Basso",         0.78, 1.10, 4.3, 5.5, 2.2, 1.05),
    "Lecce":            T("Serie A", "Eusebio Di Francesco","Pressing Alto",        0.72, 1.12, 4.4, 5.6, 2.3, 1.10),
    "Verona":           T("Serie A", "Paolo Zanetti",       "Blocco Basso",         0.72, 1.15, 4.2, 5.6, 2.5, 1.20),
    "Parma":            T("Serie A", "Carlos Cuesta",       "Blocco Medio",         0.78, 1.12, 4.4, 5.5, 2.3, 1.05),
    "Sassuolo":         T("Serie A", "",                    "Equilibrato",          0.85, 1.10, 4.6, 5.4, 2.1, 1.00),
    "Pisa":             T("Serie A", "Alberto Gilardino",   "Blocco Basso",         0.70, 1.10, 4.2, 5.5, 2.4, 1.15),
    "Cremonese":        T("Serie A", "Davide Nicola",       "Blocco Basso",         0.72, 1.12, 4.1, 5.6, 2.2, 1.05),
    # ---------------- PREMIER LEAGUE ----------------
    "Arsenal":          T("Premier League", "Mikel Arteta",     "Possesso Posizionale", 1.30, 0.62, 6.8, 3.9, 1.9, 0.95),
    "Manchester City":  T("Premier League", "Pep Guardiola",    "Possesso Posizionale", 1.32, 0.85, 6.9, 3.8, 1.7, 0.85),
    "Liverpool":        T("Premier League", "Arne Slot",        "Gegenpressing",        1.22, 0.95, 6.2, 4.4, 1.7, 0.90),
    "Chelsea":          T("Premier League", "Enzo Maresca",     "Possesso Posizionale", 1.18, 0.90, 6.0, 4.5, 2.1, 1.05),
    "Manchester United":T("Premier League", "",                 "Equilibrato",          1.05, 1.00, 5.4, 4.9, 2.0, 1.00),
    "Tottenham":        T("Premier League", "Thomas Frank",     "Blocco Medio",         1.02, 0.95, 5.3, 4.9, 1.9, 0.95),
    "Newcastle":        T("Premier League", "Eddie Howe",       "Pressing Alto",        1.08, 0.90, 5.8, 4.6, 2.0, 1.05),
    "Aston Villa":      T("Premier League", "Unai Emery",       "Equilibrato",          1.05, 0.92, 5.4, 4.8, 2.0, 1.00),
    "Brighton":         T("Premier League", "Fabian Hürzeler",  "Possesso Posizionale", 1.08, 1.00, 5.7, 4.7, 1.9, 0.95),
    "Crystal Palace":   T("Premier League", "Oliver Glasner",   "Blocco Medio",         1.00, 0.85, 5.0, 4.9, 2.0, 1.00),
    "Bournemouth":      T("Premier League", "Andoni Iraola",    "Gegenpressing",        1.05, 0.98, 5.6, 4.8, 2.2, 1.10),
    "Brentford":        T("Premier League", "Keith Andrews",    "Verticale",            1.02, 1.02, 5.1, 5.0, 2.0, 1.00),
    "Fulham":           T("Premier League", "Marco Silva",      "Equilibrato",          0.95, 1.00, 5.0, 5.1, 2.0, 1.00),
    "West Ham":         T("Premier League", "Nuno Espírito Santo","Blocco Basso",       0.85, 1.15, 4.5, 5.6, 2.1, 1.05),
    "Everton":          T("Premier League", "David Moyes",      "Blocco Basso",         0.85, 0.95, 4.4, 5.3, 2.0, 1.00),
    "Nottingham Forest":T("Premier League", "Sean Dyche",       "Blocco Basso",         0.85, 1.05, 4.4, 5.5, 2.2, 1.10),
    "Wolverhampton":    T("Premier League", "Rob Edwards",      "Blocco Basso",         0.75, 1.20, 4.3, 5.8, 2.2, 1.05),
    "Burnley":          T("Premier League", "Scott Parker",     "Blocco Basso",         0.72, 1.18, 4.2, 5.8, 2.1, 1.00),
    "Leeds":            T("Premier League", "Daniel Farke",     "Pressing Alto",        0.85, 1.10, 5.0, 5.3, 2.0, 1.00),
    "Sunderland":       T("Premier League", "Régis Le Bris",    "Blocco Medio",         0.92, 0.88, 4.8, 5.0, 2.0, 1.00),
    # ---------------- LA LIGA ----------------
    "Real Madrid":      T("La Liga", "Xabi Alonso",        "Verticale",            1.35, 0.75, 6.3, 4.0, 2.0, 0.95),
    "Barcellona":       T("La Liga", "Hansi Flick",        "Possesso Posizionale", 1.38, 0.85, 6.5, 4.1, 2.0, 0.95),
    "Atletico Madrid":  T("La Liga", "Diego Simeone",      "Blocco Medio",         1.15, 0.75, 5.5, 4.4, 2.4, 1.15),
    "Athletic Bilbao":  T("La Liga", "Ernesto Valverde",   "Pressing Alto",        1.02, 0.82, 5.6, 4.5, 2.2, 1.05),
    "Villarreal":       T("La Liga", "Marcelino",          "Equilibrato",          1.12, 0.88, 5.6, 4.6, 2.1, 1.00),
    "Real Sociedad":    T("La Liga", "Sergio Francisco",   "Possesso Posizionale", 0.95, 0.95, 5.2, 4.9, 2.1, 1.00),
    "Betis":            T("La Liga", "Manuel Pellegrini",  "Possesso Posizionale", 1.02, 0.95, 5.4, 4.8, 2.2, 1.05),
    "Siviglia":         T("La Liga", "Matías Almeyda",     "Equilibrato",          0.90, 1.05, 4.9, 5.2, 2.4, 1.15),
    "Valencia":         T("La Liga", "Carlos Corberán",    "Blocco Basso",         0.82, 1.05, 4.5, 5.4, 2.3, 1.10),
    "Girona":           T("La Liga", "Míchel",             "Possesso Posizionale", 0.85, 1.10, 5.0, 5.3, 2.2, 1.05),
    # ---------------- BUNDESLIGA ----------------
    "Bayern Monaco":    T("Bundesliga", "Vincent Kompany",  "Gegenpressing",        1.45, 0.70, 6.8, 3.8, 1.7, 0.85),
    "Bayer Leverkusen": T("Bundesliga", "Kasper Hjulmand",  "Possesso Posizionale", 1.15, 0.90, 5.9, 4.4, 1.9, 0.95),
    "Borussia Dortmund":T("Bundesliga", "Niko Kovač",       "Blocco Medio",         1.15, 0.85, 5.8, 4.4, 1.9, 0.95),
    "Lipsia":           T("Bundesliga", "Ole Werner",       "Verticale",            1.10, 0.90, 5.5, 4.6, 1.9, 0.95),
    "Stoccarda":        T("Bundesliga", "Sebastian Hoeneß", "Pressing Alto",        1.10, 0.95, 5.7, 4.6, 2.0, 1.00),
    "Eintracht Francoforte": T("Bundesliga", "Dino Toppmöller", "Verticale",        1.10, 1.05, 5.4, 4.9, 2.0, 1.00),
    "Friburgo":         T("Bundesliga", "Julian Schuster",  "Equilibrato",          0.95, 0.95, 5.1, 5.0, 2.0, 1.00),
    "Borussia M'gladbach": T("Bundesliga", "Eugen Polanski","Equilibrato",          0.92, 1.05, 4.9, 5.2, 2.0, 1.00),
    # ---------------- LIGUE 1 ----------------
    "PSG":              T("Ligue 1", "Luis Enrique",       "Possesso Posizionale", 1.45, 0.70, 7.0, 3.7, 1.8, 0.90),
    "Marsiglia":        T("Ligue 1", "Roberto De Zerbi",   "Possesso Posizionale", 1.20, 0.90, 6.0, 4.4, 2.2, 1.05),
    "Monaco":           T("Ligue 1", "Sébastien Pocognoli","Verticale",            1.15, 1.00, 5.7, 4.7, 2.1, 1.00),
    "Lione":            T("Ligue 1", "Paulo Fonseca",      "Possesso Posizionale", 1.05, 0.95, 5.5, 4.8, 2.1, 1.00),
    "Lille":            T("Ligue 1", "Bruno Genesio",      "Equilibrato",          1.05, 0.90, 5.4, 4.8, 2.1, 1.00),
    "Nizza":            T("Ligue 1", "Franck Haise",       "Blocco Medio",         0.95, 0.95, 5.0, 5.0, 2.2, 1.05),
    # ---------------- PRIMEIRA LIGA ----------------
    "Benfica":          T("Primeira Liga", "José Mourinho",     "Blocco Medio",         1.30, 0.75, 5.9, 4.3, 2.3, 1.10),
    "Porto":            T("Primeira Liga", "Francesco Farioli", "Possesso Posizionale", 1.32, 0.72, 6.0, 4.2, 2.3, 1.05),
    "Sporting Lisbona": T("Primeira Liga", "Rui Borges",        "Pressing Alto",        1.38, 0.70, 6.1, 4.1, 2.2, 1.05),
    "Braga":            T("Primeira Liga", "Carlos Vicens",     "Pressing Alto",        1.12, 0.90, 5.5, 4.6, 2.3, 1.10),
    "Vitória Guimarães":T("Primeira Liga", "",                  "Equilibrato",          0.95, 0.95, 5.0, 5.0, 2.4, 1.10),
    "Famalicão":        T("Primeira Liga", "",                  "Blocco Medio",         0.85, 1.05, 4.6, 5.3, 2.4, 1.10),
}

# Alias per il riconoscimento dei nomi (chiave normalizzata -> nome canonico)
ALIASES = {
    "internazionale": "Inter", "fc inter": "Inter",
    "ac milan": "Milan", "juve": "Juventus", "hellas verona": "Verona", "hellas": "Verona",
    "man city": "Manchester City", "city": "Manchester City", "mancity": "Manchester City",
    "man united": "Manchester United", "man utd": "Manchester United", "united": "Manchester United",
    "spurs": "Tottenham", "tottenham hotspur": "Tottenham",
    "wolves": "Wolverhampton", "forest": "Nottingham Forest", "newcastle united": "Newcastle",
    "real": "Real Madrid", "barcelona": "Barcellona", "barca": "Barcellona", "fc barcelona": "Barcellona",
    "atletico": "Atletico Madrid", "atleti": "Atletico Madrid", "athletic": "Athletic Bilbao",
    "bilbao": "Athletic Bilbao", "sevilla": "Siviglia", "real betis": "Betis",
    "bayern": "Bayern Monaco", "bayern munich": "Bayern Monaco", "bayern munchen": "Bayern Monaco",
    "leverkusen": "Bayer Leverkusen", "dortmund": "Borussia Dortmund", "bvb": "Borussia Dortmund",
    "rb leipzig": "Lipsia", "leipzig": "Lipsia", "stuttgart": "Stoccarda",
    "eintracht": "Eintracht Francoforte", "frankfurt": "Eintracht Francoforte",
    "freiburg": "Friburgo", "gladbach": "Borussia M'gladbach", "monchengladbach": "Borussia M'gladbach",
    "paris": "PSG", "paris saint germain": "PSG", "paris sg": "PSG",
    "marseille": "Marsiglia", "om": "Marsiglia", "as monaco": "Monaco",
    "lyon": "Lione", "ol": "Lione", "losc": "Lille", "nice": "Nizza",
    "sporting": "Sporting Lisbona", "sporting cp": "Sporting Lisbona", "sporting lisbon": "Sporting Lisbona",
    "slb": "Benfica", "fc porto": "Porto", "sp braga": "Braga", "sporting braga": "Braga",
    "guimaraes": "Vitória Guimarães", "vitoria guimaraes": "Vitória Guimarães", "vitoria": "Vitória Guimarães",
    "ajax amsterdam": "Ajax", "psv eindhoven": "PSV", "az alkmaar": "AZ Alkmaar",
    "gala": "Galatasaray", "fener": "Fenerbahçe", "istanbul basaksehir": "Başakşehir",
    "brugge": "Club Brugge", "bruges": "Club Brugge", "union sg": "Union Saint-Gilloise",
    "olympiacos": "Olympiakos", "pao": "Panathinaikos", "glasgow rangers": "Rangers",
    "celtic glasgow": "Celtic",
}

# Derby e rivalità storiche: (etichetta, moltiplicatore nervosismo cartellini)
DERBIES = {
    frozenset({"Inter", "Milan"}):               ("Derby della Madonnina", 1.30),
    frozenset({"Roma", "Lazio"}):                ("Derby della Capitale", 1.35),
    frozenset({"Juventus", "Torino"}):           ("Derby della Mole", 1.25),
    frozenset({"Juventus", "Inter"}):            ("Derby d'Italia", 1.20),
    frozenset({"Real Madrid", "Barcellona"}):    ("El Clásico", 1.25),
    frozenset({"Real Madrid", "Atletico Madrid"}):("Derby di Madrid", 1.30),
    frozenset({"Athletic Bilbao", "Real Sociedad"}):("Derby Basco", 1.15),
    frozenset({"Liverpool", "Everton"}):         ("Merseyside Derby", 1.25),
    frozenset({"Liverpool", "Manchester United"}):("North-West Derby", 1.20),
    frozenset({"Manchester United", "Manchester City"}):("Derby di Manchester", 1.20),
    frozenset({"Arsenal", "Tottenham"}):         ("North London Derby", 1.30),
    frozenset({"Bayern Monaco", "Borussia Dortmund"}):("Der Klassiker", 1.15),
    frozenset({"PSG", "Marsiglia"}):             ("Le Classique", 1.35),
    frozenset({"Benfica", "Porto"}):             ("O Clássico", 1.35),
    frozenset({"Benfica", "Sporting Lisbona"}):  ("Derby di Lisbona", 1.30),
    frozenset({"Porto", "Sporting Lisbona"}):    ("Clássico portoghese", 1.25),
    frozenset({"Ajax", "Feyenoord"}):            ("De Klassieker", 1.35),
    frozenset({"Celtic", "Rangers"}):            ("Old Firm", 1.40),
    frozenset({"Galatasaray", "Fenerbahçe"}):    ("Derby Intercontinentale", 1.40),
    frozenset({"Beşiktaş", "Fenerbahçe"}):       ("Derby di Istanbul", 1.30),
    frozenset({"Galatasaray", "Beşiktaş"}):      ("Derby di Istanbul", 1.30),
    frozenset({"Olympiakos", "Panathinaikos"}):  ("Derby degli Eterni Nemici", 1.40),
    frozenset({"Club Brugge", "Anderlecht"}):    ("Topper belga", 1.20),
}

# ==================================================================
# 1. DOWNLOAD E COSTRUZIONE DEL DATABASE DAI DATI REALI
# ==================================================================

_DB = None   # database attivo (impostato da inizializza_database)


def _codici_stagioni(n=N_STAGIONI):
    """Codici stagione football-data (es. '2526') per le ultime n stagioni."""
    oggi = datetime.date.today()
    inizio = oggi.year if oggi.month >= 8 else oggi.year - 1
    return [f"{a % 100:02d}{(a + 1) % 100:02d}" for a in range(inizio - n + 1, inizio + 1)]


def _scarica_csv(codice_stagione, divisione, usa_cache=True, max_ore=None):
    """Scarica un CSV (o lo legge dalla cache locale, se più giovane di max_ore). Ritorna il testo o None."""
    os.makedirs(CARTELLA_CACHE, exist_ok=True)
    percorso = os.path.join(CARTELLA_CACHE, f"{divisione}_{codice_stagione}.csv")
    giovane = max_ore is not None and os.path.exists(percorso) and (time.time() - os.path.getmtime(percorso)) / 3600 < max_ore
    if (usa_cache or giovane) and os.path.exists(percorso):
        with open(percorso, "rb") as f:
            return f.read().decode("utf-8-sig", errors="replace")
    url = f"https://football-data.co.uk/mmz4281/{codice_stagione}/{divisione}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            dati = r.read()
    except Exception:
        return None
    with open(percorso, "wb") as f:
        f.write(dati)
    return dati.decode("utf-8-sig", errors="replace")


def _parse_data(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _to_int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _to_float(x):
    try:
        v = float(x)
        return v if v == v else None   # scarta NaN
    except (TypeError, ValueError):
        return None


def _devig(quote):
    """Quote → probabilità, togliendo il margine del bookmaker (in proporzione)."""
    try:
        q = [float(x) for x in quote]
    except (TypeError, ValueError):
        return None
    if any(not (x > 1.0) for x in q):
        return None
    inv = [1 / x for x in q]
    s = sum(inv)
    return [x / s for x in inv]


# colonne delle quote nei CSV di football-data, in ordine di preferenza: media di tutti i
# bookmaker (dal 2019), media Betbrain (prima), poi i singoli
_COL_1X2 = (("AvgH", "AvgD", "AvgA"), ("BbAvH", "BbAvD", "BbAvA"), ("PSH", "PSD", "PSA"), ("B365H", "B365D", "B365A"))
_COL_OU = (("Avg>2.5", "Avg<2.5"), ("BbAv>2.5", "BbAv<2.5"), ("P>2.5", "P<2.5"), ("B365>2.5", "B365<2.5"))


def quote_riga(riga):
    """
    Attese del mercato per una partita (riga di un CSV di football-data): [p1, pX, p2, pOver2.5]
    senza margine, oppure None. Sono le quote raccolte prima della partita (non quelle di chiusura),
    le stesse che il file fixtures.csv pubblica per le partite in arrivo.
    """
    x12 = ou = None
    for c in _COL_1X2:
        x12 = _devig([riga.get(k) for k in c])
        if x12:
            break
    for c in _COL_OU:
        ou = _devig([riga.get(k) for k in c])
        if ou:
            break
    if not x12 or not ou:
        return None
    return [round(x12[0], 5), round(x12[1], 5), round(x12[2], 5), round(ou[0], 5)]


def carica_partite():
    """
    Scarica le ultime N_STAGIONI per ogni lega in LEGHE_FD (e in LEGHE_STORIA, solo storico).
    Ritorna (lista_partite, conteggi_per_lega).
    Ogni partita: dict con lega, peso temporale, gol, corner, cartellini, attese del mercato.
    """
    stagioni = _codici_stagioni()
    oggi = datetime.date.today()
    partite, conteggi = [], Counter()

    for div, lega in list(LEGHE_FD.items()) + list(LEGHE_STORIA.items()):
        for cod in stagioni:
            # la stagione più recente si riscarica (la fonte la aggiorna una o due volte a settimana: basta ogni 2 ore)
            testo = _scarica_csv(cod, div, usa_cache=(cod != stagioni[-1]), max_ore=2)
            if not testo:
                continue
            for riga in csv.DictReader(io.StringIO(testo)):
                casa = (riga.get("HomeTeam") or "").strip()
                ospite = (riga.get("AwayTeam") or "").strip()
                gc, go = _to_int(riga.get("FTHG")), _to_int(riga.get("FTAG"))
                data = _parse_data(riga.get("Date") or "")
                if not casa or not ospite or gc is None or go is None or data is None:
                    continue
                anni_fa = max(0.0, (oggi - data).days / 365.25)
                cart_c = cart_o = ros_c = ros_o = None
                if _to_int(riga.get("HY")) is not None:
                    ros_c = _to_int(riga.get("HR")) or 0
                    ros_o = _to_int(riga.get("AR")) or 0
                    cart_c = (_to_int(riga.get("HY")) or 0) + ros_c
                    cart_o = (_to_int(riga.get("AY")) or 0) + ros_o
                partite.append({
                    "lega": lega, "peso": DECADIMENTO ** anni_fa, "data": data,
                    "casa": FD_RENAME.get(casa, casa), "ospite": FD_RENAME.get(ospite, ospite),
                    "gc": gc, "go": go,
                    "cor_c": _to_int(riga.get("HC")), "cor_o": _to_int(riga.get("AC")),
                    "cart_c": cart_c, "cart_o": cart_o, "ros_c": ros_c, "ros_o": ros_o,
                    "tiri_c": _to_int(riga.get("HS")), "tiri_o": _to_int(riga.get("AS")),
                    "tip_c": _to_int(riga.get("HST")), "tip_o": _to_int(riga.get("AST")),
                    "fal_c": _to_int(riga.get("HF")), "fal_o": _to_int(riga.get("AF")),
                    "xg_c": _to_float(riga.get("HxG")), "xg_o": _to_float(riga.get("AxG")),
                    "arb": (riga.get("Referee") or "").strip() or None,
                    "stagione": cod, "q": quote_riga(riga),
                })
                conteggi[lega] += 1
    return partite, conteggi


def _scarica_coppa(slug, anno, usa_cache=True):
    """Scarica il JSON di una coppa europea (fixturedownload.com) o legge la cache."""
    os.makedirs(CARTELLA_CACHE, exist_ok=True)
    percorso = os.path.join(CARTELLA_CACHE, f"{slug}_{anno}.json")
    if usa_cache and os.path.exists(percorso):
        with open(percorso, "rb") as f:
            return f.read().decode("utf-8", errors="replace")
    url = f"https://fixturedownload.com/feed/json/{slug}-{anno}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            dati = r.read()
    except Exception:
        return None
    testo = dati.decode("utf-8", errors="replace")
    if not testo.lstrip().startswith("["):   # 404 → pagina HTML, non dati
        return None
    with open(percorso, "wb") as f:
        f.write(dati)
    return testo


def carica_coppe():
    """
    Costanti reali delle coppe europee (Champions, Europa, Conference):
    gol casa/trasferta, esiti, Over, Gol/Gol e rho calibrato — tutto dai
    risultati veri. I rating delle squadre restano quelli di campionato.
    """
    oggi = datetime.date.today()
    anno_corrente = oggi.year if oggi.month >= 8 else oggi.year - 1
    coppe = {}
    for slug, nome in COPPE_FD.items():
        acc = defaultdict(float)
        anni = []
        for anno in range(anno_corrente - N_STAGIONI + 1, anno_corrente + 1):
            testo = _scarica_coppa(slug, anno, usa_cache=(anno != anno_corrente))
            if not testo:
                continue
            try:
                righe = json.loads(testo)
            except Exception:
                continue
            for r in righe:
                gc, go = r.get("HomeTeamScore"), r.get("AwayTeamScore")
                if gc is None or go is None:
                    continue
                try:
                    d = datetime.datetime.strptime(str(r.get("DateUtc", ""))[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
                w = DECADIMENTO ** max(0.0, (oggi - d).days / 365.25)
                acc["w"] += w
                acc["n"] += 1
                acc["gc"] += w * gc
                acc["gt"] += w * go
                if gc > go:
                    acc["p1"] += w
                elif gc == go:
                    acc["px"] += w
                else:
                    acc["p2"] += w
                if gc + go > 2.5:
                    acc["ov"] += w
                if gc > 0 and go > 0:
                    acc["gg"] += w
                if gc == 0 and go == 0:
                    acc["p00"] += w
                if gc == 1 and go == 1:
                    acc["p11"] += w
                anni.append(d.year)
        if acc["w"] < 60:
            continue
        w = acc["w"]
        gc_m, gt_m = acc["gc"] / w, acc["gt"] / w
        coppe[nome] = {
            "gc": round(gc_m, 3), "gt": round(gt_m, 3),
            "rho": _rho_empirico(gc_m, gt_m, acc["p00"] / w, acc["p11"] / w),
            "n": int(acc["n"]), "anni": f"{min(anni)}–{max(anni)}",
            "p1": round(100 * acc["p1"] / w, 1), "px": round(100 * acc["px"] / w, 1),
            "p2": round(100 * acc["p2"] / w, 1),
            "ov": round(100 * acc["ov"] / w, 1), "gg": round(100 * acc["gg"] / w, 1),
        }
    return coppe


def _rho_empirico(lam_c, lam_o, obs00, obs11, fallback=RHO_DEFAULT):
    """
    Calibra il rho di Dixon-Coles DAI DATI: confronta la frequenza reale di
    0-0 e 1-1 nella competizione con quella prevista da una Poisson
    indipendente. Niente costanti a mano dove i dati bastano.
    """
    try:
        e00 = math.exp(-lam_c - lam_o)
        e11 = lam_c * lam_o * e00
        r00 = (1 - obs00 / e00) / (lam_c * lam_o)
        r11 = 1 - obs11 / e11
        return round(max(-0.25, min(0.05, (r00 + r11) / 2)), 3)
    except Exception:
        return fallback


def costruisci_da_dati(partite):
    """
    Trasforma le partite reali in: costanti di lega + rating per squadra
    (attacco/difesa normalizzati per lega e venue, con decadimento temporale
    e regressione verso la media). Metodo: stimatore Dixon-Coles semplificato.
    """
    # ---- passo 1: costanti + DNA di lega (medie pesate) ----
    acc = defaultdict(lambda: defaultdict(float))
    punteggi_lega = defaultdict(Counter)
    for m in partite:
        a, w = acc[m["lega"]], m["peso"]
        a["w"] += w
        a["gol_casa"] += w * m["gc"]
        a["gol_trasferta"] += w * m["go"]
        if m["gc"] > m["go"]:
            a["p1"] += w
        elif m["gc"] == m["go"]:
            a["px"] += w
        else:
            a["p2"] += w
        if m["gc"] + m["go"] > 2.5:
            a["ov"] += w
        if m["gc"] > 0 and m["go"] > 0:
            a["gg"] += w
        if m["gc"] == 0 and m["go"] == 0:
            a["p00"] += w
        if m["gc"] == 1 and m["go"] == 1:
            a["p11"] += w
        punteggi_lega[m["lega"]][f"{m['gc']}-{m['go']}"] += w
        if m["cor_c"] is not None:
            a["w_cor"] += w
            a["corner"] += w * (m["cor_c"] + m["cor_o"])
        if m["cart_c"] is not None:
            a["w_cart"] += w
            a["cart"] += w * (m["cart_c"] + m["cart_o"])

    leghe = {}
    for lega, a in acc.items():
        fb = FALLBACK_LEGHE.get(lega, FALLBACK_LEGHE["Serie A"])
        w = a["w"]
        gc_m = a["gol_casa"] / w if w else fb["gol_casa"]
        gt_m = a["gol_trasferta"] / w if w else fb["gol_trasferta"]
        leghe[lega] = {
            "gol_casa": gc_m,
            "gol_trasferta": gt_m,
            "corner": a["corner"] / a["w_cor"] if a["w_cor"] > 30 else fb["corner"],
            "cart": a["cart"] / a["w_cart"] if a["w_cart"] > 30 else fb["cart"],
            # DNA della lega: cosa succede "di solito" in questo campionato
            "p1": round(100 * a["p1"] / w, 1), "px": round(100 * a["px"] / w, 1),
            "p2": round(100 * a["p2"] / w, 1),
            "ov": round(100 * a["ov"] / w, 1), "gg": round(100 * a["gg"] / w, 1),
            "top": [[p, round(100 * c / w, 1)] for p, c in punteggi_lega[lega].most_common(3)],
            "rho_emp": _rho_empirico(gc_m, gt_m, a["p00"] / w, a["p11"] / w,
                                     RHO_LEGA.get(lega, RHO_DEFAULT)),
        }

    # ---- passo 2: rating + scheda statistica per squadra ----
    st = defaultdict(lambda: defaultdict(float))
    punteggi_freq = defaultdict(Counter)
    ultima = {}
    for m in partite:
        L = leghe[m["lega"]]
        w = m["peso"]
        for nome, fatti, subiti, avg_f, avg_s, cor_p, cor_c, cart, ros in (
            (m["casa"],  m["gc"], m["go"], L["gol_casa"], L["gol_trasferta"], m["cor_c"], m["cor_o"], m["cart_c"], m["ros_c"]),
            (m["ospite"],m["go"], m["gc"], L["gol_trasferta"], L["gol_casa"], m["cor_o"], m["cor_c"], m["cart_o"], m["ros_o"]),
        ):
            s = st[nome]
            s["w"] += w
            s["n_raw"] += 1
            s["att"] += w * (fatti / max(avg_f, 0.1))
            s["dif"] += w * (subiti / max(avg_s, 0.1))
            s["gf"] += w * fatti
            s["gs"] += w * subiti
            if fatti + subiti > 2.5:
                s["ov"] += w
            if fatti > 0 and subiti > 0:
                s["gg"] += w
            punteggi_freq[nome][f"{fatti}-{subiti}"] += w
            if cor_p is not None:
                s["w_cor"] += w
                s["cor_pro"] += w * cor_p
                s["cor_con"] += w * cor_c
            if cart is not None:
                s["w_cart"] += w
                s["cart"] += w * cart
                s["ros"] += w * ros
            if nome not in ultima or m["data"] > ultima[nome][0]:
                ultima[nome] = (m["data"], m["lega"])

    clamp = lambda x, lo, hi: max(lo, min(hi, x))
    squadre = {}
    for nome, s in st.items():
        lega = ultima[nome][1]
        L = leghe[lega]
        w = s["w"]
        # shrinkage: con poche partite pesate il rating regredisce verso 1.0
        att = clamp((s["att"] + K_SHRINK) / (w + K_SHRINK), 0.45, 1.70)
        dif = clamp((s["dif"] + K_SHRINK) / (w + K_SHRINK), 0.45, 1.70)
        norm = L["corner"] / 2
        if s["w_cor"] > 5:
            cor_pro = s["cor_pro"] / s["w_cor"]
            cor_con = s["cor_con"] / s["w_cor"]
            cor_stima = False
        else:  # lega senza dati corner (es. Primeira Liga): stima dal profilo
            cor_pro = norm * (0.72 + 0.28 * att)
            cor_con = norm * (0.72 + 0.28 * dif)
            cor_stima = True
        if s["w_cart"] > 5:
            cart = s["cart"] / s["w_cart"]
        else:
            cart = L["cart"] / 2
        aggr = clamp(cart / max(L["cart"] / 2, 0.5), 0.85, 1.25)
        # scheda "numeri veri" della squadra (medie pesate sui 10 anni)
        prof = {
            "n": int(s["n_raw"]),
            "gf": round(s["gf"] / w, 2), "gs": round(s["gs"] / w, 2),
            "ov": round(100 * s["ov"] / w, 1), "gg": round(100 * s["gg"] / w, 1),
            "gialli": round((s["cart"] - s["ros"]) / s["w_cart"], 2) if s["w_cart"] > 5 else None,
            "rossi": round(s["ros"] / s["w_cart"], 3) if s["w_cart"] > 5 else None,
            "top": [[p, round(100 * c / w, 1)] for p, c in punteggi_freq[nome].most_common(3)],
        }
        squadre[nome] = {
            "lega": lega, "att": att, "dif": dif,
            "cor_pro": cor_pro, "cor_con": cor_con,
            "cart": cart, "aggr": aggr, "cor_stima": cor_stima, "prof": prof,
        }

    # ---- passo 3: rho Dixon-Coles calibrato PARTITA PER PARTITA ----
    # Confronta 0-0 e 1-1 osservati con quelli attesi usando i gol attesi
    # della singola partita (rating delle due squadre), non la media di lega:
    # così l'eterogeneità forti/deboli non annacqua la stima.
    acc2 = defaultdict(lambda: defaultdict(float))
    for m in partite:
        tc, to = squadre.get(m["casa"]), squadre.get(m["ospite"])
        if not tc or not to:
            continue
        L = leghe[m["lega"]]
        w = m["peso"]
        lc = L["gol_casa"] * tc["att"] * to["dif"]
        lo = L["gol_trasferta"] * to["att"] * tc["dif"]
        p00 = math.exp(-lc - lo)
        a2 = acc2[m["lega"]]
        a2["e00"] += w * p00
        a2["e11"] += w * lc * lo * p00
        a2["peso00"] += w * p00 * lc * lo
        if m["gc"] == 0 and m["go"] == 0:
            a2["o00"] += w
        if m["gc"] == 1 and m["go"] == 1:
            a2["o11"] += w
    for lega, a2 in acc2.items():
        try:
            r11 = 1 - a2["o11"] / a2["e11"]
            r00 = (a2["e00"] - a2["o00"]) / a2["peso00"]
            leghe[lega]["rho_emp"] = round(max(-0.25, min(0.08, (r00 + r11) / 2)), 3)
        except ZeroDivisionError:
            pass

    return leghe, squadre


def _mese(s, fine=False):
    a, m = s.split("-")
    return datetime.date(int(a), int(m), 28 if fine else 1)


def profili_allenatori(partite):
    """
    NUMERI VERI per allenatore: incrocia le partite reali con lo storico
    panchine documentato (COACH_HISTORY). Medie semplici sul periodo di
    carica. Sotto le 20 partite reali non viene mostrato nulla.
    """
    per_team = defaultdict(list)
    for m in partite:
        per_team[m["casa"]].append((m["data"], m["gc"], m["go"], m["cor_c"], m["cart_c"], m["ros_c"]))
        per_team[m["ospite"]].append((m["data"], m["go"], m["gc"], m["cor_o"], m["cart_o"], m["ros_o"]))
    oggi = datetime.date.today()
    prof = {}
    for coach, stints in COACH_HISTORY.items():
        righe, squadre = [], []
        for team, da, a in stints:
            d1 = _mese(da)
            d2 = _mese(a, fine=True) if a else oggi
            sel = [r for r in per_team.get(team, []) if d1 <= r[0] <= d2]
            if sel:
                righe += sel
                squadre.append(team)
        n = len(righe)
        if n < 20:
            continue
        squadre = list(dict.fromkeys(squadre))
        vin = sum(1 for r in righe if r[1] > r[2]) / n
        par = sum(1 for r in righe if r[1] == r[2]) / n
        cor = [r[3] for r in righe if r[3] is not None]
        car = [(r[4], r[5]) for r in righe if r[4] is not None]
        prof[coach] = {
            "n": n,
            "anni": f"{min(r[0] for r in righe).year}–{max(r[0] for r in righe).year}",
            "squadre": squadre,
            "gf": round(sum(r[1] for r in righe) / n, 2),
            "gs": round(sum(r[2] for r in righe) / n, 2),
            "vin": round(100 * vin, 1), "par": round(100 * par, 1),
            "per": round(100 * (1 - vin - par), 1),
            "ov": round(100 * sum(1 for r in righe if r[1] + r[2] > 2.5) / n, 1),
            "gg": round(100 * sum(1 for r in righe if r[1] > 0 and r[2] > 0) / n, 1),
            "cor": round(sum(cor) / len(cor), 2) if len(cor) >= 10 else None,
            "gialli": round(sum(c - r for c, r in car) / len(car), 2) if len(car) >= 10 else None,
            "rossi": round(sum(r for _, r in car) / len(car), 3) if len(car) >= 10 else None,
        }
    return prof


def inizializza_database(verbose=True):
    """Prova a costruire il database dai dati reali; altrimenti usa la riserva."""
    global _DB
    if _DB is not None:
        return _DB
    if verbose:
        print("\n 📡 Scarico i dati storici reali (football-data.co.uk)...")
        print(f"    {len(LEGHE_FD)} campionati × {N_STAGIONI} stagioni — la prima volta serve ~1 minuto,")
        print(f"    poi resta tutto nella cartella '{CARTELLA_CACHE}' e riparte all'istante.\n")
    partite, conteggi = [], Counter()
    try:
        partite, conteggi = carica_partite()
    except Exception:
        pass

    if len(partite) > 1000:
        leghe, squadre = costruisci_da_dati(partite)
        codici = _codici_stagioni()
        anni = f"20{codici[0][:2]}/{codici[0][2:]} → 20{codici[-1][:2]}/{codici[-1][2:]}"
        tot = f"{len(partite):,}".replace(",", ".")
        if verbose:
            for lega in LEGHE_FD.values():
                cnt = f"{conteggi[lega]:,}".replace(",", ".")
                print(f"    {lega:<20} {cnt:>6} partite reali ✓")
            print(f"\n    Totale: {tot} partite, stagioni {anni} — rating calcolati.")
        fonte = f"football-data.co.uk — {tot} partite reali, stagioni {anni}"
        try:
            coppe = carica_coppe()
        except Exception:
            coppe = {}
        if verbose and coppe:
            for nome_c, c in coppe.items():
                cnt = f"{c['n']:,}".replace(",", ".")
                print(f"    {nome_c:<20} {cnt:>6} partite reali ✓ (fixturedownload.com)")
        _DB = {"squadre": squadre, "leghe": leghe, "fonte": fonte, "online": True,
               "coach_prof": profili_allenatori(partite), "coppe": coppe}
    else:
        if verbose:
            print("    ⚠ Internet non disponibile: uso il database interno di riserva")
            print("      (stime calibrate, stagione 2025-26).")
        squadre = {n: dict(t) for n, t in TEAMS.items()}
        _DB = {"squadre": squadre, "leghe": dict(FALLBACK_LEGHE),
               "fonte": "database interno di riserva (stime calibrate 2025-26)", "online": False,
               "coach_prof": {}, "coppe": {}}
    _costruisci_indice_squadre()
    return _DB


# ==================================================================
# 2. FUNZIONI MATEMATICHE DI BASE
# ==================================================================

def pmf_poisson(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def matrice_dixon_coles(lam_c, lam_o, rho, max_gol=MAX_GOL):
    """Matrice P[i][j] = P(casa=i, ospite=j): Poisson + correzione tau Dixon-Coles."""
    P = [[pmf_poisson(i, lam_c) * pmf_poisson(j, lam_o)
          for j in range(max_gol + 1)] for i in range(max_gol + 1)]
    tau = {
        (0, 0): 1 - lam_c * lam_o * rho,
        (0, 1): 1 + lam_c * rho,
        (1, 0): 1 + lam_o * rho,
        (1, 1): 1 - rho,
    }
    for (i, j), t in tau.items():
        P[i][j] *= max(t, 0.05)
    tot = sum(sum(r) for r in P)
    return [[v / tot for v in r] for r in P]


def campiona_poisson(mu):
    L = math.exp(-mu)
    k, p = 0, 1.0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1


def campiona_negbin(mu, k_disp):
    """Negativa binomiale (miscela Gamma-Poisson): sovradispersione reale."""
    mu = max(mu, 0.2)
    lam = random.gammavariate(k_disp, mu / k_disp)
    return campiona_poisson(lam)


# ==================================================================
# 3. MATRICE TATTICA — coefficiente di attrito tra identità di gioco
# ==================================================================

def attrito_tattico(stile_casa, stile_ospite):
    a, b = STYLES[stile_casa], STYLES[stile_ospite]

    # apertura della gara: ritmo combinato dei due stili
    mod_gol = 0.55 + 0.45 * (a["tempo"] * b["tempo"])

    # linea alta avversaria punita dalla verticalità propria
    bonus_casa = 1 + 2.0 * max(0.0, b["linea"] - 1.0) * max(0.0, a["verticalita"] - 1.0)
    bonus_osp  = 1 + 2.0 * max(0.0, a["linea"] - 1.0) * max(0.0, b["verticalita"] - 1.0)

    # blocco basso: soffoca l'attacco avversario ma concede territorio (corner)
    comp_casa = max(0.0, 1.0 - a["linea"])
    comp_osp  = max(0.0, 1.0 - b["linea"])
    bonus_casa *= (1 - 0.55 * comp_osp)
    bonus_osp  *= (1 - 0.55 * comp_casa)

    cor_casa = (0.5 + 0.5 * a["possesso"]) * (1 + 0.9 * comp_osp)
    cor_osp  = (0.5 + 0.5 * b["possesso"]) * (1 + 0.9 * comp_casa)

    mod_cart = 0.70 + 0.30 * (a["pressing"] * b["pressing"])

    clamp = lambda x, lo, hi: max(lo, min(hi, x))
    return {
        "mod_gol":  clamp(mod_gol, 0.85, 1.15),
        "bonus_casa": clamp(bonus_casa, 0.80, 1.20),
        "bonus_osp":  clamp(bonus_osp, 0.80, 1.20),
        "cor_casa": clamp(cor_casa, 0.80, 1.30),
        "cor_osp":  clamp(cor_osp, 0.80, 1.30),
        "mod_cart": clamp(mod_cart, 0.85, 1.20),
    }


# ==================================================================
# 4. COSTRUZIONE DEI PARAMETRI DEL MATCH
# ==================================================================

def parametri_match(casa, ospite, stile_c=None, stile_o=None, all_c=None, all_o=None,
                    ass_c=0, ass_o=0, coppa=None):
    db = inizializza_database(verbose=False)
    tc, to = db["squadre"][casa], db["squadre"][ospite]

    # identità: allenatore/stile scelti dall'utente > default della squadra
    ident_c, ident_o = TEAMS.get(casa, {}), TEAMS.get(ospite, {})
    stile_c = stile_c or ident_c.get("stile", "Equilibrato")
    stile_o = stile_o or ident_o.get("stile", "Equilibrato")
    all_c = all_c or ident_c.get("allenatore") or "—"
    all_o = all_o or ident_o.get("allenatore") or "—"

    # costanti di lega (media mista per match inter-lega, es. coppe europee)
    if tc["lega"] == to["lega"]:
        cost = db["leghe"][tc["lega"]]
        rho = cost.get("rho_emp", RHO_LEGA.get(tc["lega"], RHO_DEFAULT))
        lega_label = tc["lega"]
        profilo = cost if "p1" in cost else None
    else:
        l1, l2 = db["leghe"][tc["lega"]], db["leghe"][to["lega"]]
        cost = {k: (l1[k] + l2[k]) / 2 for k in ("gol_casa", "gol_trasferta", "corner", "cart")}
        rho = (l1.get("rho_emp", RHO_LEGA.get(tc["lega"], RHO_DEFAULT))
               + l2.get("rho_emp", RHO_LEGA.get(to["lega"], RHO_DEFAULT))) / 2
        lega_label = f"{tc['lega']} × {to['lega']} (costanti miste)"
        profilo = None

    # coppa europea: gol, esiti e rho REALI della competizione;
    # angoli e cartellini restano dai profili di campionato delle due squadre
    if coppa:
        cp = db.get("coppe", {}).get(coppa)
        if cp:
            cost = {"gol_casa": cp["gc"], "gol_trasferta": cp["gt"],
                    "corner": cost["corner"], "cart": cost["cart"]}
            rho = cp["rho"]
            lega_label = (f"{coppa} · {tc['lega']} vs {to['lega']}"
                          if tc["lega"] != to["lega"] else coppa)
            profilo = cp

    attr = attrito_tattico(stile_c, stile_o)

    # assenze pesanti (0-3 per squadra): meno attacco, difesa più fragile
    att_c = tc["att"] * (1 - 0.06 * ass_c)
    dif_c = tc["dif"] * (1 + 0.05 * ass_c)
    att_o = to["att"] * (1 - 0.06 * ass_o)
    dif_o = to["dif"] * (1 + 0.05 * ass_o)

    # --- GOL ATTESI (Dixon-Coles: forza attacco × debolezza difesa) ---
    lam_c = cost["gol_casa"]      * att_c * dif_o * attr["mod_gol"] * attr["bonus_casa"]
    lam_o = cost["gol_trasferta"] * att_o * dif_c * attr["mod_gol"] * attr["bonus_osp"]
    lam_c = max(0.15, min(4.5, lam_c))
    lam_o = max(0.15, min(4.5, lam_o))

    # --- CORNER ATTESI ---
    dom = max(0.88, min(1.15, (lam_c / max(lam_o, 0.1)) ** 0.15))
    norm = cost["corner"] / 2
    mu_cor_c = tc["cor_pro"] * (to["cor_con"] / norm) * attr["cor_casa"] * dom * 1.08
    mu_cor_o = to["cor_pro"] * (tc["cor_con"] / norm) * attr["cor_osp"] / dom * 0.94

    # --- CARTELLINI ATTESI ---
    derby = DERBIES.get(frozenset({casa, ospite}))
    boost_derby = derby[1] if derby else 1.0
    mu_cart_c = tc["cart"] * to["aggr"] * attr["mod_cart"] * boost_derby
    mu_cart_o = to["cart"] * tc["aggr"] * attr["mod_cart"] * boost_derby * 1.10

    return {
        "casa": casa, "ospite": ospite, "tc": tc, "to": to,
        "stile_c": stile_c, "stile_o": stile_o, "all_c": all_c, "all_o": all_o,
        "lega": lega_label, "rho": rho, "attr": attr,
        "lam_c": lam_c, "lam_o": lam_o,
        "mu_cor_c": mu_cor_c, "mu_cor_o": mu_cor_o,
        "mu_cart_c": mu_cart_c, "mu_cart_o": mu_cart_o,
        "derby": derby[0] if derby else None, "boost_derby": boost_derby,
        "cor_stimati": tc.get("cor_stima") or to.get("cor_stima"),
        "profilo": profilo, "ass_c": ass_c, "ass_o": ass_o, "coppa": coppa,
    }


# ==================================================================
# 5. MOTORE MONTE CARLO (eventi secondari correlati al match simulato)
# ==================================================================

def monte_carlo(ctx, n=N_SIMULAZIONI):
    P = matrice_dixon_coles(ctx["lam_c"], ctx["lam_o"], ctx["rho"])
    celle = [(i, j) for i in range(MAX_GOL + 1) for j in range(MAX_GOL + 1)]
    pesi = [P[i][j] for (i, j) in celle]
    punteggi = random.choices(celle, weights=pesi, k=n)

    tot_gol_atteso = ctx["lam_c"] + ctx["lam_o"]
    esiti = Counter()
    conta_punteggi = Counter()
    corner_c, corner_o, corner_tot = [], [], []
    cart_tot = []

    for gc, go in punteggi:
        conta_punteggi[(gc, go)] += 1
        esiti["1" if gc > go else ("X" if gc == go else "2")] += 1

        # CORRELAZIONE: partite più aperte del previsto → più ritmo → più corner
        apertura = max(0.85, min(1.25, 1 + 0.05 * ((gc + go) - tot_gol_atteso)))
        spinta_c = 1.06 if gc < go else 1.0     # chi insegue spinge
        spinta_o = 1.06 if go < gc else 1.0
        cc = campiona_negbin(ctx["mu_cor_c"] * apertura * spinta_c, DISP_CORNER)
        co = campiona_negbin(ctx["mu_cor_o"] * apertura * spinta_o, DISP_CORNER)
        corner_c.append(cc); corner_o.append(co); corner_tot.append(cc + co)

        # CORRELAZIONE cartellini: chi perde si innervosisce, chi stravince cala
        m_c = 1.08 if gc < go else (0.95 if gc - go >= 2 else 1.0)
        m_o = 1.08 if go < gc else (0.95 if go - gc >= 2 else 1.0)
        kc = campiona_negbin(ctx["mu_cart_c"] * m_c, DISP_CART)
        ko = campiona_negbin(ctx["mu_cart_o"] * m_o, DISP_CART)
        cart_tot.append(kc + ko)

    over25 = sum(1 for gc, go in punteggi if gc + go > 2.5) / n
    btts = sum(1 for gc, go in punteggi if gc > 0 and go > 0) / n

    return {
        "n": n, "esiti": esiti, "punteggi": conta_punteggi,
        "corner_c": corner_c, "corner_o": corner_o, "corner_tot": corner_tot,
        "cart_tot": cart_tot, "over25": over25, "btts": btts,
    }


def linea_consigliata(campioni, linee):
    n = len(campioni)
    med = median(campioni)
    linea = min(linee, key=lambda L: abs(L - med))
    p_over = sum(1 for x in campioni if x > linea) / n
    tabella = [(L, sum(1 for x in campioni if x > L) / n) for L in linee]
    return linea, p_over, tabella


# ==================================================================
# 6. ANALISI TATTICA TESTUALE
# ==================================================================

def genera_analisi(ctx, ris):
    c, o = ctx["casa"], ctx["ospite"]
    attr = ctx["attr"]
    frasi = []

    diff = ctx["lam_c"] - ctx["lam_o"]
    if diff > 0.75:
        frasi.append(f"Il modello vede {c} nettamente favorita: il differenziale di gol attesi "
                     f"({ctx['lam_c']:.2f} vs {ctx['lam_o']:.2f}) indica che {o} dovrà sopravvivere "
                     f"a lunghe fasi di assedio.")
    elif diff > 0.30:
        frasi.append(f"{c} parte favorita ma non domina il modello: il vantaggio di gol attesi "
                     f"({ctx['lam_c']:.2f} vs {ctx['lam_o']:.2f}) è concreto ma non blindato, e un "
                     f"episodio può riaprire tutto.")
    elif diff < -0.30:
        frasi.append(f"Segnale controcorrente: nonostante il fattore campo, i rating storici "
                     f"premiano {o} ({ctx['lam_o']:.2f} gol attesi contro {ctx['lam_c']:.2f}).")
    else:
        frasi.append(f"Partita da equilibrio quasi perfetto ({ctx['lam_c']:.2f} vs {ctx['lam_o']:.2f} "
                     f"gol attesi): il pareggio pesa più del solito nella distribuzione.")

    frasi.append(f"Sul piano tattico, il {ctx['stile_c']} di {ctx['all_c']} "
                 f"({DESCR_STILE[ctx['stile_c']]}) incrocia il {ctx['stile_o']} di {ctx['all_o']} "
                 f"({DESCR_STILE[ctx['stile_o']]}): coefficiente di attrito {attr['mod_gol']:.2f}, "
                 f"{'gara che tende ad aprirsi' if attr['mod_gol'] > 1.02 else ('gara che tende a bloccarsi' if attr['mod_gol'] < 0.98 else 'ritmo nella norma della lega')}.")

    if ctx["stile_o"] == "Blocco Basso" and STYLES[ctx["stile_c"]]["possesso"] >= 1.0:
        frasi.append(f"{o} si abbasserà accettando di difendere nella propria trequarti: il possesso di "
                     f"{c} si tradurrà più facilmente in calci d'angolo e conclusioni respinte che in "
                     f"occasioni nitide — attenzione al valore sui corner della squadra di casa.")
    if ctx["stile_c"] == "Blocco Basso" and STYLES[ctx["stile_o"]]["possesso"] >= 1.0:
        frasi.append(f"{c} rinuncerà al pallone anche in casa: {o} farà la partita e accumulerà corner, "
                     f"ma resterà esposta alle ripartenze.")

    if STYLES[ctx["stile_c"]]["pressing"] >= 1.1 and STYLES[ctx["stile_o"]]["pressing"] >= 1.1:
        frasi.append("Con due squadre che riaggrediscono così in alto, il centrocampo sarà una zona di "
                     "duelli continui: ritmo altissimo, transizioni da entrambe le parti e conto dei "
                     "falli destinato a salire.")

    if ctx["derby"]:
        frasi.append(f"È il {ctx['derby']}: la componente emotiva vale un +{int((ctx['boost_derby']-1)*100)}% "
                     f"sul nervosismo atteso — i cartellini in queste gare storicamente sfondano la media di lega.")
    elif ctx["mu_cart_c"] + ctx["mu_cart_o"] > 5.2:
        frasi.append("L'aggressività combinata delle due squadre è sopra la media di lega: gara da "
                     "arbitro severo, con soglia cartellini alta.")

    tot_cor = mean(ris["corner_tot"])
    lato = c if mean(ris["corner_c"]) >= mean(ris["corner_o"]) else o
    frasi.append(f"La proiezione angoli ({tot_cor:.1f} totali attesi) pende dal lato di {lato}, "
                 f"coerente con il piano-partita descritto sopra.")
    return frasi


# ==================================================================
# 7. REPORT GRAFICO TESTUALE
# ==================================================================

def barra(p, larghezza=32):
    return "█" * max(1, round(p * larghezza))


def stampa_report(ctx, ris):
    db = inizializza_database(verbose=False)
    c, o = ctx["casa"], ctx["ospite"]
    n = ris["n"]
    riga = "─" * 70

    print()
    print("╔" + "═" * 68 + "╗")
    print("║{:^68}║".format("⚽  ORACLE ENGINE v5.0 — REPORT PREDITTIVO  ⚽"))
    print("╚" + "═" * 68 + "╝")
    print(f" MATCH   : {c} (casa)  vs  {o} (ospite)")
    print(f" CONTESTO: {ctx['lega']}" + (f"  |  🔥 {ctx['derby']}" if ctx["derby"] else ""))
    if ctx.get("profilo"):
        pr = ctx["profilo"]
        print(f" DNA LEGA: di solito 1 {pr['p1']}% · X {pr['px']}% · 2 {pr['p2']}%"
              f" · Over 2.5 {pr['ov']}% · Gol/Gol {pr['gg']}%")
    print(f" PANCHINE: {ctx['all_c']} [{ctx['stile_c']}]  vs  {ctx['all_o']} [{ctx['stile_o']}]")
    if ctx.get("ass_c") or ctx.get("ass_o"):
        print(f" ASSENZE : {c} -{ctx['ass_c']} titolari · {o} -{ctx['ass_o']} titolari (pesate nel calcolo)")
    print(f" DATI    : {db['fonte']}")
    print(f" xG MODELLO: {c} {ctx['lam_c']:.2f} — {o} {ctx['lam_o']:.2f}"
          f"   |   attrito tattico: {ctx['attr']['mod_gol']:.2f}   |   rho D-C: {ctx['rho']:.2f}")
    print(riga)

    # ---- le 3 uscite più probabili (tutti i mercati a confronto) ----
    p1, px, p2 = (ris["esiti"][e] / n for e in ("1", "X", "2"))
    linea, p_over, tab = linea_consigliata(ris["corner_tot"], [7.5, 8.5, 9.5, 10.5, 11.5, 12.5])
    consiglio = ("OVER", p_over) if p_over >= 0.5 else ("UNDER", 1 - p_over)
    linea_k, p_over_k, tab_k = linea_consigliata(ris["cart_tot"], [2.5, 3.5, 4.5, 5.5, 6.5])
    consiglio_k = ("OVER", p_over_k) if p_over_k >= 0.5 else ("UNDER", 1 - p_over_k)
    candidati = [
        (f"1 · vince {c}", p1), ("X · pareggio", px), (f"2 · vince {o}", p2),
        (f"1X · {c} o pareggio", p1 + px), (f"X2 · {o} o pareggio", px + p2),
        ("12 · niente pareggio", p1 + p2),
        ("Over 2.5 gol", ris["over25"]), ("Under 2.5 gol", 1 - ris["over25"]),
        ("Gol/Gol", ris["btts"]), ("No Gol", 1 - ris["btts"]),
        (f"{consiglio[0]} {linea} angoli", consiglio[1]),
        (f"{consiglio_k[0]} {linea_k} cartellini", consiglio_k[1]),
    ]
    candidati.sort(key=lambda x: -x[1])
    print(" ⭐ LE 3 USCITE PIÙ PROBABILI")
    for medaglia, (nome_m, pm) in zip(("🥇", "🥈", "🥉"), candidati[:3]):
        print(f"   {medaglia} {nome_m:<34} {pm*100:5.1f}%")
    print(riga)

    print(f" PROBABILITÀ ESITO  ({n:,} simulazioni Monte Carlo)".replace(",", "."))
    for esito, label in (("1", c), ("X", "Pareggio"), ("2", o)):
        p = ris["esiti"][esito] / n
        print(f"   {esito:<2} {label:<22} {p*100:5.1f}%  {barra(p)}")
    print(riga)

    print(" TOP 3 RISULTATI ESATTI")
    for (gc, go), cnt in ris["punteggi"].most_common(3):
        p = cnt / n
        print(f"   {gc}-{go:<20} {p*100:5.1f}%  {barra(p)}")
    print(f"   Over 2.5 gol: {ris['over25']*100:.1f}%   |   Gol/Gol (BTTS): {ris['btts']*100:.1f}%")
    print(riga)

    mc, mo = mean(ris["corner_c"]), mean(ris["corner_o"])
    print(" CALCI D'ANGOLO")
    print(f"   Media attesa: {c} {mc:.2f}  |  {o} {mo:.2f}  |  Totale {mc+mo:.2f}")
    print(f"   ➤ Linea consigliata: {consiglio[0]} {linea}  (probabilità {consiglio[1]*100:.1f}%)")
    print("   Distribuzione sulle linee:  " +
          "  ".join(f"O{L}: {p*100:.0f}%" for L, p in tab if abs(L - linea) <= 1.0))
    if ctx.get("cor_stimati"):
        print("   (nota: corner non disponibili dalla fonte per una delle due")
        print("    squadre — valori stimati dal profilo storico di lega)")
    if ctx.get("coppa"):
        print("   (nota: in coppa gol/esiti sono da partite europee reali; angoli")
        print("    e cartellini stimati dai profili di campionato delle squadre)")
    print(riga)

    mcart = mean(ris["cart_tot"])
    print(" CARTELLINI (gialli + rossi)")
    print(f"   Media attesa totale: {mcart:.2f}" +
          (f"   (nervosismo derby ×{ctx['boost_derby']:.2f})" if ctx["boost_derby"] > 1.0 else ""))
    print(f"   ➤ Soglia consigliata: {consiglio_k[0]} {linea_k}  (probabilità {consiglio_k[1]*100:.1f}%)")
    print("   Distribuzione sulle linee:  " +
          "  ".join(f"O{L}: {p*100:.0f}%" for L, p in tab_k if abs(L - linea_k) <= 1.0))
    print(riga)

    print(" ANALISI TATTICA DELL'ALGORITMO")
    for f in genera_analisi(ctx, ris):
        parole, r = f.split(), "   • "
        for w in parole:
            if len(r) + len(w) > 68:
                print(r); r = "     "
            r += w + " "
        print(r.rstrip())
    print(riga)
    print(" ⚠  Modello probabilistico a scopo informativo: nessuna previsione")
    print("    è garantita. Gioca responsabilmente (18+).")
    print("═" * 70)


# ==================================================================
# 8. RICONOSCIMENTO SQUADRE / ALLENATORI E INTERFACCIA
# ==================================================================

def normalizza(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s.lower())
    return " ".join(s.split())


_INDICE = {}

def _costruisci_indice_squadre():
    _INDICE.clear()
    db = _DB or {"squadre": TEAMS}
    for nome in db["squadre"]:
        _INDICE[normalizza(nome)] = nome
    for alias, canon in ALIASES.items():
        if canon in db["squadre"]:
            _INDICE[normalizza(alias)] = canon


def trova_squadra(testo):
    chiave = normalizza(testo)
    if not chiave:
        return None
    if chiave in _INDICE:
        return _INDICE[chiave]
    prefissi = [v for k, v in _INDICE.items() if k.startswith(chiave)]
    if len(set(prefissi)) == 1:
        return prefissi[0]
    vicini = difflib.get_close_matches(chiave, list(_INDICE.keys()), n=1, cutoff=0.75)
    if vicini:
        return _INDICE[vicini[0]]
    return None


# indici allenatori: nome completo e cognome
_IDX_ALL = {}
_IDX_COGNOME = defaultdict(set)

def _costruisci_indice_allenatori():
    _IDX_ALL.clear(); _IDX_COGNOME.clear()
    for nome in COACHES:
        _IDX_ALL[normalizza(nome)] = nome
        _IDX_COGNOME[normalizza(nome).split()[-1]].add(nome)

_costruisci_indice_allenatori()


def trova_allenatore(testo):
    """Ritorna (nome_canonico, None) se trovato, (None, [candidati]) se ambiguo."""
    chiave = normalizza(testo)
    if not chiave:
        return None, None
    if chiave in _IDX_ALL:
        return _IDX_ALL[chiave], None
    cognome = chiave.split()[-1]
    if cognome in _IDX_COGNOME:
        candidati = sorted(_IDX_COGNOME[cognome])
        if len(candidati) == 1:
            return candidati[0], None
        return None, candidati
    vicini = difflib.get_close_matches(chiave, list(_IDX_ALL.keys()), n=1, cutoff=0.80)
    if vicini:
        return _IDX_ALL[vicini[0]], None
    return None, None


def scegli_stile_da_menu(nome_allenatore):
    print(f"   Allenatore nuovo per l'archivio. Che identità di gioco ha {nome_allenatore}?")
    for i, s in enumerate(LISTA_STILI, 1):
        print(f"     {i}) {s:<22}" + ("" if i % 2 == 0 else ""), end="\n" if i % 2 == 0 else "")
    if len(LISTA_STILI) % 2:
        print()
    while True:
        try:
            scelta = input(f"   Scegli 1-{len(LISTA_STILI)} [Invio = Equilibrato] ➤ ").strip()
        except EOFError:
            return "Equilibrato"
        if not scelta:
            return "Equilibrato"
        if scelta.isdigit() and 1 <= int(scelta) <= len(LISTA_STILI):
            return LISTA_STILI[int(scelta) - 1]
        print("   ✗ Scrivi solo il numero dello stile.")


def chiedi_allenatore(squadra):
    """Chiede il tecnico attuale. Ritorna (nome, stile)."""
    default = TEAMS.get(squadra, {}).get("allenatore", "")
    stile_squadra = TEAMS.get(squadra, {}).get("stile", "Equilibrato")
    suffisso = f" [Invio = {default}]" if default else ""
    while True:
        try:
            testo = input(f"   Allenatore attuale di {squadra}{suffisso} ➤ ").strip()
        except EOFError:
            testo = ""
        if not testo:
            if default:
                return default, COACHES.get(default, stile_squadra)
            return "—", stile_squadra
        nome, candidati = trova_allenatore(testo)
        if nome:
            stile = COACHES[nome]
            print(f"   ✓ {nome} → identità: {stile}")
            return nome, stile
        if candidati:
            print("   Più allenatori con questo cognome: " + ", ".join(candidati))
            print("   Riscrivi il nome completo.")
            continue
        # allenatore sconosciuto: si registra con lo stile scelto dal menu
        nome_nuovo = testo.title()
        stile = scegli_stile_da_menu(nome_nuovo)
        COACHES[nome_nuovo] = stile
        _costruisci_indice_allenatori()
        print(f"   ✓ {nome_nuovo} registrato con identità: {stile}")
        return nome_nuovo, stile


def mostra_lista():
    db = inizializza_database(verbose=False)
    per_lega = defaultdict(list)
    for nome, t in db["squadre"].items():
        per_lega[t["lega"]].append(nome)
    print("\n SQUADRE DISPONIBILI NEL DATABASE:")
    for lega in LEGHE_FD.values():
        nomi = sorted(per_lega.get(lega, []))
        if not nomi:
            continue
        print(f"\n  ▸ {lega} ({len(nomi)} squadre, ultime {N_STAGIONI} stagioni):")
        for i in range(0, len(nomi), 4):
            print("     " + " | ".join(f"{x:<18}" for x in nomi[i:i+4]))
    print()


def chiedi_squadra(prompt):
    while True:
        try:
            testo = input(prompt).strip()
        except EOFError:
            sys.exit(0)
        if normalizza(testo) == "lista":
            mostra_lista()
            continue
        squadra = trova_squadra(testo)
        if squadra:
            if normalizza(testo) != normalizza(squadra):
                print(f"   ✓ riconosciuta: {squadra}")
            return squadra
        print("   ✗ Squadra non trovata. Riprova (o scrivi 'lista' per l'elenco).")


# ==================================================================
# 9. AVVIO
# ==================================================================

def simula(casa, ospite, allenatore_casa=None, allenatore_ospite=None,
           stile_casa=None, stile_ospite=None, assenze_casa=0, assenze_ospite=0,
           coppa=None, n=N_SIMULAZIONI, verbose=True):
    """
    API programmatica, utile anche da Colab:
      simula("Inter", "Milan")
      simula("Benfica", "Porto", allenatore_casa="Mourinho")
      simula("Real Madrid", "Arsenal", coppa="Champions League")
    """
    inizializza_database(verbose=False)
    stile_c = stile_o = all_c = all_o = None
    if allenatore_casa:
        nome, _ = trova_allenatore(allenatore_casa)
        if nome:
            all_c, stile_c = nome, COACHES[nome]
        else:
            all_c = allenatore_casa
    if allenatore_ospite:
        nome, _ = trova_allenatore(allenatore_ospite)
        if nome:
            all_o, stile_o = nome, COACHES[nome]
        else:
            all_o = allenatore_ospite
    ctx = parametri_match(casa, ospite, stile_casa or stile_c, stile_ospite or stile_o,
                          all_c, all_o, assenze_casa, assenze_ospite, coppa)
    ris = monte_carlo(ctx, n)
    if verbose:
        stampa_report(ctx, ris)
    return ctx, ris


def stampa_scheda_squadra(nome):
    """Numeri veri della squadra (medie pesate sulle ultime 10 stagioni)."""
    db = inizializza_database(verbose=False)
    t = db["squadre"].get(nome)
    if not t:
        print(f" ✗ Squadra '{nome}' non nel database.")
        return
    p = t.get("prof")
    print(f"\n 📊 {nome} — {t['lega']}")
    if not p:
        print("    Statistiche storiche non disponibili (database di riserva offline).")
        return
    print(f"    Gol fatti {p['gf']} · subiti {p['gs']} a partita")
    print(f"    Over 2.5: {p['ov']}% · Gol/Gol: {p['gg']}%")
    print(f"    Angoli: {t['cor_pro']:.2f} fatti · {t['cor_con']:.2f} concessi a partita")
    if p.get("gialli") is not None:
        print(f"    Gialli {p['gialli']} · Rossi {p['rossi']} a partita")
    top = " · ".join(f"{x[0]} ({x[1]}%)" for x in p["top"])
    print(f"    Risultati più frequenti: {top}")
    print(f"    ({p['n']} partite reali, pesate sulle ultime {N_STAGIONI} stagioni)")


def stampa_scheda_allenatore(nome):
    """Numeri veri dell'allenatore (periodi di panchina documentati)."""
    db = inizializza_database(verbose=False)
    canonico, candidati = trova_allenatore(nome)
    if not canonico and candidati:
        print(" Più allenatori con questo cognome: " + ", ".join(candidati))
        return
    if not canonico:
        print(f" ✗ Allenatore '{nome}' non in archivio.")
        return
    p = db.get("coach_prof", {}).get(canonico)
    stile = COACHES.get(canonico, "—")
    print(f"\n 🧢 {canonico} — identità di gioco: {stile}")
    if not p:
        print("    Nessuna statistica verificata nei campionati coperti (2016 → oggi).")
        print("    Niente dati inventati: meglio nessun numero che un numero falso.")
        return
    print(f"    {p['n']} partite reali ({p['anni']}) su panchine di: {', '.join(p['squadre'])}")
    print(f"    Vittorie {p['vin']}% · Pareggi {p['par']}% · Sconfitte {p['per']}%")
    print(f"    Gol fatti {p['gf']} · subiti {p['gs']} a partita")
    print(f"    Over 2.5: {p['ov']}% · Gol/Gol: {p['gg']}%")
    if p.get("cor") is not None:
        print(f"    Angoli {p['cor']} a partita")
    if p.get("gialli") is not None:
        print(f"    Gialli {p['gialli']} · Rossi {p['rossi']} a partita")


def _risolvi_coppa(testo):
    chiave = normalizza(testo)
    for nome in COPPE_FD.values():
        if chiave in normalizza(nome) or normalizza(nome) in chiave:
            return nome
    return None


def main_cli(argv):
    """Modalità a comandi (non interattiva) — pensata per agenti e script."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="oracle_engine",
        description="Oracle Engine — simulatore predittivo su dati reali (Dixon-Coles + Monte Carlo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("simula", help="simula una partita (10.000 iterazioni)")
    sp.add_argument("--casa", required=True, help="squadra di casa (accetta alias e refusi)")
    sp.add_argument("--ospite", required=True, help="squadra ospite")
    sp.add_argument("--all-casa", default=None, help="allenatore attuale della squadra di casa")
    sp.add_argument("--all-ospite", default=None, help="allenatore attuale della squadra ospite")
    sp.add_argument("--stile-casa", default=None, choices=LISTA_STILI, help="identità di gioco (override)")
    sp.add_argument("--stile-ospite", default=None, choices=LISTA_STILI)
    sp.add_argument("--assenze-casa", type=int, default=0, choices=range(4), help="titolari pesanti assenti (0-3)")
    sp.add_argument("--assenze-ospite", type=int, default=0, choices=range(4))
    sp.add_argument("--coppa", default=None, help='competizione europea: "Champions League", "Europa League", "Conference League"')

    sub.add_parser("lista", help="elenco squadre disponibili per campionato")
    sq = sub.add_parser("squadra", help="scheda numeri veri di una squadra")
    sq.add_argument("--nome", required=True)
    al = sub.add_parser("allenatore", help="scheda numeri veri di un allenatore")
    al.add_argument("--nome", required=True)
    wa = sub.add_parser("webapp", help="genera la webapp HTML per il telefono")
    wa.add_argument("--file", default="oracle_webapp.html")

    args = ap.parse_args(argv)
    inizializza_database(verbose=True)

    if args.cmd == "lista":
        mostra_lista()
    elif args.cmd == "squadra":
        nome = trova_squadra(args.nome)
        stampa_scheda_squadra(nome or args.nome)
    elif args.cmd == "allenatore":
        stampa_scheda_allenatore(args.nome)
    elif args.cmd == "webapp":
        esporta_webapp(args.file)
    elif args.cmd == "simula":
        casa = trova_squadra(args.casa)
        ospite = trova_squadra(args.ospite)
        if not casa or not ospite:
            print(f" ✗ Squadra non trovata: '{args.casa if not casa else args.ospite}'."
                  " Usa il comando 'lista' per l'elenco completo.")
            sys.exit(1)
        if casa == ospite:
            print(" ✗ Le due squadre devono essere diverse.")
            sys.exit(1)
        coppa = None
        if args.coppa:
            coppa = _risolvi_coppa(args.coppa)
            if not coppa:
                print(f" ✗ Competizione '{args.coppa}' non riconosciuta "
                      f"(disponibili: {', '.join(COPPE_FD.values())}).")
                sys.exit(1)
        simula(casa, ospite,
               allenatore_casa=args.all_casa, allenatore_ospite=args.all_ospite,
               stile_casa=args.stile_casa, stile_ospite=args.stile_ospite,
               assenze_casa=args.assenze_casa, assenze_ospite=args.assenze_ospite,
               coppa=coppa)


def main():
    print("═" * 70)
    print("  ⚽ ORACLE ENGINE v5.0 — Simulatore Predittivo (Dixon-Coles + MC)")
    print(f"     Dati reali: {len(LEGHE_FD)} campionati × {N_STAGIONI} stagioni (football-data.co.uk)")
    print("     Scrivi 'lista' per vedere tutte le squadre disponibili.")
    print("═" * 70)
    inizializza_database(verbose=True)

    print("\n Cosa vuoi fare?")
    print("   1) Simulare una partita QUI nel terminale")
    print("   2) Creare/aggiornare la WEBAPP colorata per il telefono")
    try:
        scelta = input(" Scelta [Invio = 1] ➤ ").strip()
    except EOFError:
        scelta = "1"
    if scelta == "2":
        esporta_webapp()
        return

    print()
    casa = chiedi_squadra(" Inserisci Squadra Casa   ➤ ")
    all_c, stile_c = chiedi_allenatore(casa)
    while True:
        ospite = chiedi_squadra(" Inserisci Squadra Ospite ➤ ")
        if ospite != casa:
            break
        print("   ✗ La squadra ospite deve essere diversa da quella di casa.")
    all_o, stile_o = chiedi_allenatore(ospite)

    print(f"\n ⏳ Simulazione di {N_SIMULAZIONI:,} partite in corso...".replace(",", "."))
    ctx = parametri_match(casa, ospite, stile_c, stile_o, all_c, all_o)
    ris = monte_carlo(ctx)
    stampa_report(ctx, ris)


# ==================================================================
# 10. WEBAPP PER IL TELEFONO (file HTML autonomo, funziona offline)
# ==================================================================

def _payload_webapp(db):
    squadre = {}
    for nome, t in db["squadre"].items():
        ident = TEAMS.get(nome, {})
        squadre[nome] = {
            "lega": t["lega"], "att": round(t["att"], 3), "dif": round(t["dif"], 3),
            "cp": round(t["cor_pro"], 2), "cc": round(t["cor_con"], 2),
            "cart": round(t["cart"], 2), "aggr": round(t["aggr"], 2),
            "all": ident.get("allenatore", ""), "stile": ident.get("stile", "Equilibrato"),
            "prof": t.get("prof"),
        }
    leghe = {}
    for nome, v in db["leghe"].items():
        leghe[nome] = {"gc": round(v["gol_casa"], 3), "gt": round(v["gol_trasferta"], 3),
                       "corner": round(v["corner"], 2), "cart": round(v["cart"], 2),
                       "rho": v.get("rho_emp", RHO_LEGA.get(nome, RHO_DEFAULT)),
                       "p1": v.get("p1"), "px": v.get("px"), "p2": v.get("p2"),
                       "ov": v.get("ov"), "gg": v.get("gg"), "top": v.get("top")}
    return {
        "fonte": db["fonte"], "generato": datetime.date.today().strftime("%d/%m/%Y"),
        "ordine_leghe": [l for l in LEGHE_FD.values() if l in leghe],
        "ordine_stili": LISTA_STILI,
        "leghe": leghe, "squadre": squadre, "stili": STYLES, "descr": DESCR_STILE,
        "coaches": COACHES, "coach_prof": db.get("coach_prof", {}),
        "coppe": db.get("coppe", {}),
        "derby": [[*sorted(pair), lab, boost] for pair, (lab, boost) in DERBIES.items()],
    }


def esporta_webapp(percorso="oracle_webapp.html"):
    db = inizializza_database(verbose=False)
    dati = json.dumps(_payload_webapp(db), ensure_ascii=False, separators=(",", ":"))
    html = TEMPLATE_WEBAPP.replace('"__DATI__"', dati)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n ✅ Webapp creata: {os.path.abspath(percorso)}")
    print("    • Su Colab: parte il download automatico (oppure cartella a sinistra")
    print("      → tre puntini sul file → Scarica)")
    print("    • Manda il file al telefono (WhatsApp, Drive, email) e aprilo con Chrome")
    print("    • Funziona anche offline; gli allenatori che modifichi restano salvati")
    print("    • Per dati freschi: rilancia questo programma e scegli di nuovo l'opzione 2")
    try:
        from google.colab import files
        files.download(percorso)
    except Exception:
        pass


TEMPLATE_WEBAPP = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b1026">
<title>Oracle Engine ⚽</title>
<style>
*{box-sizing:border-box}
body{margin:0;padding:14px 12px 40px;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
 background:linear-gradient(165deg,#0b1026 0%,#1b1145 55%,#251054 100%);color:#eef2ff;min-height:100vh}
.wrap{max-width:560px;margin:0 auto}
header{text-align:center;margin-bottom:14px}
header h1{margin:4px 0 2px;font-size:26px;letter-spacing:.5px}
header .sub{color:#9fb0e8;font-size:11.5px;margin:2px 0}
.card{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.13);border-radius:18px;
 padding:14px;margin-bottom:12px;box-shadow:0 8px 24px rgba(0,0,0,.25)}
.team-head{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.side-label{font-size:10.5px;font-weight:800;letter-spacing:1.5px;color:#22d3ee}
#cardO .side-label{color:#f472b6}
.tname{font-size:19px;font-weight:800}
label{display:block;font-size:11px;color:#9fb0e8;margin:8px 0 3px;letter-spacing:.4px}
select,input{width:100%;padding:10px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.18);
 background:#121737;color:#eef2ff;font-size:15px}
.due{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.cbox{position:relative}
.sug{position:absolute;left:0;right:0;top:100%;z-index:30;background:#141a3d;
 border:1px solid rgba(255,255,255,.25);border-radius:12px;margin-top:4px;
 max-height:236px;overflow-y:auto;display:none;box-shadow:0 12px 28px rgba(0,0,0,.5)}
.sug div{padding:11px 13px;font-size:14.5px;border-bottom:1px solid rgba(255,255,255,.07);cursor:pointer}
.sug div:last-child{border-bottom:none}
.sug div:active,.sug div:hover{background:rgba(34,211,238,.18)}
.vs{text-align:center;font-weight:900;font-size:15px;color:#a3e635;margin:2px 0 10px;letter-spacing:2px}
.btn{width:100%;padding:16px;border:none;border-radius:16px;font-size:17px;font-weight:900;cursor:pointer;
 background:linear-gradient(90deg,#22d3ee,#a3e635);color:#0a1126;box-shadow:0 6px 20px rgba(34,211,238,.35)}
.btn:active{transform:scale(.98)}
details{margin-top:10px}summary{cursor:pointer;font-size:13px;color:#c3d0f8}
.prof{font-size:13.5px;line-height:1.75;padding:8px 2px 0}
.prof .mini{color:#8fa0d8;font-size:11px;margin-top:4px}
h3.sec{margin:16px 2px 8px;font-size:13px;letter-spacing:1.5px;color:#22d3ee;text-transform:uppercase}
.row{display:flex;align-items:center;gap:8px;margin:7px 0}
.row .lb{width:110px;font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar{flex:1;height:20px;background:rgba(255,255,255,.09);border-radius:8px;overflow:hidden}
.bar span{display:block;height:100%;border-radius:8px;transition:width .9s cubic-bezier(.2,.8,.2,1)}
.row .pc{width:52px;text-align:right;font-weight:800;font-size:13.5px}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.15);border-radius:12px;
 padding:8px 12px;font-size:14px}
.chip b{color:#a3e635}
.pill{display:inline-block;background:rgba(255,255,255,.09);border-radius:20px;padding:6px 12px;
 font-size:12.5px;margin:3px 4px 0 0}
.cons{background:linear-gradient(90deg,rgba(163,230,53,.16),rgba(34,211,238,.12));border:1px solid rgba(163,230,53,.4);
 border-radius:12px;padding:10px 12px;font-size:14.5px;margin-top:8px}
.ana{padding-left:18px;margin:6px 0}
.ana li{font-size:13.5px;line-height:1.55;margin-bottom:8px;color:#dbe4ff}
.derbybox{background:linear-gradient(90deg,rgba(244,63,94,.25),rgba(251,146,60,.18));
 border:1px solid rgba(251,146,60,.45);border-radius:12px;padding:8px 12px;font-size:13.5px;margin:8px 0}
footer{color:#8fa0d8;font-size:10.5px;text-align:center;margin-top:22px;line-height:1.6}
.matchhead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:4px 0 8px}
.matchhead .mh-t{text-align:center;flex:1;font-weight:800;font-size:14px;line-height:1.3}
.matchhead small{color:#9fb0e8;font-weight:600}
</style>
</head>
<body>
<div class="wrap">
<header>
 <h1>⚽ Oracle Engine</h1>
 <p class="sub" id="fonte"></p>
 <p class="sub">Dixon-Coles · Matrice tattica · 10.000 simulazioni Monte Carlo</p>
</header>

<div class="card" style="padding:10px 14px">
 <label>Competizione</label>
 <select id="comp"></select>
 <div id="compinfo" style="color:#8fa0d8;font-size:11px;margin-top:5px;line-height:1.4"></div>
</div>

<div class="card" id="cardC">
 <div class="team-head"><span id="shC"></span><div><div class="side-label">IN CASA 🏟️</div><div class="tname" id="nmC">—</div></div></div>
 <div class="due">
  <div><label>Campionato</label><select id="lgC"></select></div>
  <div><label>Squadra</label><select id="sqC"></select></div>
 </div>
 <label>Allenatore attuale — scrivi per cercare (📊 = statistiche vere)</label>
 <div class="cbox">
  <input id="alC" placeholder="Digita per cercare: es. “con” → Antonio Conte" autocomplete="off">
  <div id="alsC" class="sug"></div>
 </div>
 <div class="due">
  <div><label>Identità di gioco</label><select id="stC"></select></div>
  <div><label>Assenze pesanti</label><select id="asC"><option>0</option><option>1</option><option>2</option><option>3</option></select></div>
 </div>
 <details><summary>🧢 Numeri veri dell'allenatore</summary><div class="prof" id="cprC"></div></details>
 <details><summary>📊 Numeri veri della squadra (ultime 10 stagioni)</summary><div class="prof" id="prC"></div></details>
</div>

<div class="vs">— VS —</div>

<div class="card" id="cardO">
 <div class="team-head"><span id="shO"></span><div><div class="side-label">IN TRASFERTA ✈️</div><div class="tname" id="nmO">—</div></div></div>
 <div class="due">
  <div><label>Campionato</label><select id="lgO"></select></div>
  <div><label>Squadra</label><select id="sqO"></select></div>
 </div>
 <label>Allenatore attuale — scrivi per cercare (📊 = statistiche vere)</label>
 <div class="cbox">
  <input id="alO" placeholder="Digita per cercare: es. “alle” → Allegri" autocomplete="off">
  <div id="alsO" class="sug"></div>
 </div>
 <div class="due">
  <div><label>Identità di gioco</label><select id="stO"></select></div>
  <div><label>Assenze pesanti</label><select id="asO"><option>0</option><option>1</option><option>2</option><option>3</option></select></div>
 </div>
 <details><summary>🧢 Numeri veri dell'allenatore</summary><div class="prof" id="cprO"></div></details>
 <details><summary>📊 Numeri veri della squadra (ultime 10 stagioni)</summary><div class="prof" id="prO"></div></details>
</div>

<button class="btn" id="btnSim">🎲 SIMULA 10.000 PARTITE</button>
<div id="out"></div>
<footer>⚠ Modello probabilistico a scopo informativo: nessuna previsione è garantita.<br>
Gioca responsabilmente (18+). Per aggiornare i dati, rigenera il file da Colab.</footer>
</div>
<script>
const DATI = "__DATI__";
const CLUB_COLORS={
"Inter":["#1e63b0","#0a0f14"],"Milan":["#e2001a","#101010"],"Juventus":["#1a1a1a","#5c5c66"],
"Napoli":["#199fd6","#0d3f8f"],"Roma":["#8e1f2f","#f0bc42"],"Lazio":["#7fc7e8","#33547a"],
"Atalanta":["#1e71b8","#101418"],"Bologna":["#9f1f2f","#12294a"],"Fiorentina":["#4a2c8f","#7a5cc4"],
"Torino":["#8a1e12","#4a120c"],"Genoa":["#a3122e","#123a6b"],"Como":["#1b3a8f","#7fb2e5"],
"Verona":["#0a2d6b","#f2c94c"],"Cagliari":["#8a1e2d","#0e2d5e"],"Parma":["#f2c94c","#0a3a8f"],
"Arsenal":["#ef0107","#9c824a"],"Chelsea":["#034694","#021e4a"],"Liverpool":["#c8102e","#5e0f1d"],
"Manchester City":["#6cabdd","#1c2c5b"],"Manchester United":["#da291c","#000000"],
"Tottenham":["#132257","#8fa8c8"],"Newcastle":["#241f20","#6b6b6b"],"Aston Villa":["#670e36","#95bfe5"],
"West Ham":["#7a263a","#1bb1e7"],"Everton":["#003399","#00159a"],"Brighton":["#0057b8","#f2f2f2"],
"Crystal Palace":["#1b458f","#c4122e"],"Bournemouth":["#da291c","#0a0a0a"],"Brentford":["#e30613","#f2c94c"],
"Fulham":["#f2f2f2","#0a0a0a"],"Nottingham Forest":["#dd0741","#5c0f22"],"Burnley":["#6c1d45","#99d6ea"],
"Sunderland":["#eb172b","#f2f2f2"],"Wolverhampton":["#fdb913","#231f20"],"Leeds":["#f2f2f2","#1d428a"],
"Real Madrid":["#f2f2f2","#c9b16a"],"Barcellona":["#004d98","#a50044"],"Atletico Madrid":["#cb3524","#1b3f94"],
"Athletic Bilbao":["#ee2523","#0b0b0b"],"Siviglia":["#f5f5f5","#d8412f"],"Betis":["#00954c","#0a5c34"],
"Bayern Monaco":["#dc052d","#0066b2"],"Borussia Dortmund":["#fde100","#000000"],"Lipsia":["#dd0741","#0a1e42"],
"Bayer Leverkusen":["#e32219","#0a0a0a"],"Stoccarda":["#e30613","#c9c9c9"],
"PSG":["#004170","#da291c"],"Marsiglia":["#2faee0","#0e5a8a"],"Monaco":["#e63232","#c9a44a"],"Lione":["#1b3a8f","#da291c"],
"Benfica":["#e32221","#7a0f0f"],"Porto":["#0a4b9f","#dfe3ea"],"Sporting Lisbona":["#0a7a3c","#053d1e"],"Braga":["#d21f26","#7a1216"],
"Ajax":["#d2122e","#f2f2f2"],"PSV":["#ec1c24","#3f3f3f"],"Feyenoord":["#d2122e","#0a0a0a"],
"Galatasaray":["#a90432","#fdb912"],"Fenerbahçe":["#163962","#ffed00"],"Beşiktaş":["#0a0a0a","#5c5c5c"],
"Trabzonspor":["#7a1230","#3aa0d8"],"Olympiakos":["#d2122e","#f2f2f2"],"Panathinaikos":["#0a7a3c","#053d1e"],
"PAOK":["#0a0a0a","#8a8a8a"],"AEK":["#f2c94c","#0a0a0a"],"Celtic":["#0a7a3c","#f2f2f2"],"Rangers":["#1b458f","#c9102e"],
"Club Brugge":["#0a3a8f","#0a0a0a"],"Anderlecht":["#5a2d81","#f2f2f2"],"Genk":["#1b58a8","#e8e8e8"],"Gent":["#1b58a8","#f2c94c"]
};
function norm(s){return s.normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().trim();}
function clamp(x,a,b){return Math.max(a,Math.min(b,x));}
const $=id=>document.getElementById(id);
const SIDES=['C','O'];

const perLega={};
for(const [n,t] of Object.entries(DATI.squadre)){(perLega[t.lega]=perLega[t.lega]||[]).push(n);}
for(const l in perLega) perLega[l].sort((a,b)=>a.localeCompare(b));

const coachFull={},coachSur={};
for(const n in DATI.coaches){coachFull[norm(n)]=n;const sg=norm(n).split(' ').pop();
 coachSur[sg]=(sg in coachSur)?null:n;}
function trovaCoach(t){const k=norm(t||'');if(!k)return null;if(coachFull[k])return coachFull[k];
 const c=coachSur[k.split(' ').pop()];return c||null;}

const DERBY={};for(const d of DATI.derby){DERBY[[d[0],d[1]].sort().join('|')]=[d[2],d[3]];}

function colori(n){if(CLUB_COLORS[n])return CLUB_COLORS[n];
 let h=0;for(let i=0;i<n.length;i++)h=(h*31+n.charCodeAt(i))%360;
 return ['hsl('+h+',68%,42%)','hsl('+((h+50)%360)+',68%,26%)'];}
function lum(c){if(c[0]!=='#')return 0.2;
 const r=parseInt(c.slice(1,3),16)/255,g=parseInt(c.slice(3,5),16)/255,b=parseInt(c.slice(5,7),16)/255;
 return .299*r+.587*g+.114*b;}
function iniziali(n){const w=n.split(/\s+/).filter(x=>x.length>1);
 if(w.length>=2)return (w[0][0]+w[1][0]).toUpperCase();return n.slice(0,3).toUpperCase();}
let gid=0;
function stemma(n,size){const cs=colori(n);const id='g'+(gid++);
 const tx=lum(cs[0])>0.62?'#15224e':'#ffffff';
 return '<svg viewBox="0 0 100 112" width="'+size+'" height="'+Math.round(size*1.12)+'">'+
  '<defs><linearGradient id="'+id+'" x1="0" y1="0" x2="1" y2="1">'+
  '<stop offset="0" stop-color="'+cs[0]+'"/><stop offset="1" stop-color="'+cs[1]+'"/></linearGradient></defs>'+
  '<path d="M50 4 L92 16 V54 C92 82 73 100 50 108 C27 100 8 82 8 54 V16 Z" fill="url(#'+id+')" stroke="rgba(255,255,255,.45)" stroke-width="3"/>'+
  '<text x="50" y="65" text-anchor="middle" font-size="30" font-weight="800" fill="'+tx+'" font-family="system-ui">'+iniziali(n)+'</text></svg>';}

/* ---------- motore (porting 1:1 del modello Python) ---------- */
function pmf(k,lam){let p=Math.exp(-lam);for(let i=1;i<=k;i++)p*=lam/i;return p;}
function matriceDC(lc,lo,rho){const N=10,M=[];
 for(let i=0;i<N;i++){const r=[];for(let j=0;j<N;j++)r.push(pmf(i,lc)*pmf(j,lo));M.push(r);}
 M[0][0]*=Math.max(1-lc*lo*rho,0.05);M[0][1]*=Math.max(1+lc*rho,0.05);
 M[1][0]*=Math.max(1+lo*rho,0.05);M[1][1]*=Math.max(1-rho,0.05);
 let t=0;for(const r of M)for(const v of r)t+=v;
 return M.map(r=>r.map(v=>v/t));}
function rNorm(){let u=0,v=0;while(!u)u=Math.random();while(!v)v=Math.random();
 return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);}
function rGamma(k,th){const d=k-1/3,c=1/Math.sqrt(9*d);
 for(;;){let x=rNorm(),v=1+c*x;if(v<=0)continue;v=v*v*v;const u=Math.random();
  if(u<1-0.0331*x*x*x*x)return d*v*th;
  if(Math.log(u)<0.5*x*x+d*(1-v+Math.log(v)))return d*v*th;}}
function rPois(mu){const L=Math.exp(-mu);let k=0,p=1;do{k++;p*=Math.random();}while(p>L);return k-1;}
function rNegBin(mu,kd){mu=Math.max(mu,0.2);return rPois(rGamma(kd,mu/kd));}

function attrito(sa,sb){const a=DATI.stili[sa],b=DATI.stili[sb];
 const modGol=0.55+0.45*(a.tempo*b.tempo);
 let bC=1+2.0*Math.max(0,b.linea-1)*Math.max(0,a.verticalita-1);
 let bO=1+2.0*Math.max(0,a.linea-1)*Math.max(0,b.verticalita-1);
 const cpC=Math.max(0,1-a.linea),cpO=Math.max(0,1-b.linea);
 bC*=(1-0.55*cpO);bO*=(1-0.55*cpC);
 const corC=(0.5+0.5*a.possesso)*(1+0.9*cpO),corO=(0.5+0.5*b.possesso)*(1+0.9*cpC);
 const modCart=0.70+0.30*(a.pressing*b.pressing);
 return{modGol:clamp(modGol,.85,1.15),bC:clamp(bC,.8,1.2),bO:clamp(bO,.8,1.2),
  corC:clamp(corC,.8,1.3),corO:clamp(corO,.8,1.3),modCart:clamp(modCart,.85,1.2)};}

function parametri(casa,osp,idC,idO,assC,assO,comp){
 const tc=DATI.squadre[casa],to=DATI.squadre[osp];
 let cost,rho,legaLbl,base=null,baseLbl='';
 if(tc.lega===to.lega){const L=DATI.leghe[tc.lega];cost=L;rho=L.rho;legaLbl=tc.lega;
  if(L.p1!=null){base=L;baseLbl=tc.lega;}}
 else{const l1=DATI.leghe[tc.lega],l2=DATI.leghe[to.lega];
  cost={gc:(l1.gc+l2.gc)/2,gt:(l1.gt+l2.gt)/2,corner:(l1.corner+l2.corner)/2,cart:(l1.cart+l2.cart)/2};
  rho=(l1.rho+l2.rho)/2;legaLbl=tc.lega+' × '+to.lega;}
 const coppa=(comp&&DATI.coppe&&DATI.coppe[comp])?DATI.coppe[comp]:null;
 if(coppa){ // costanti gol/esiti REALI della coppa; angoli e cartellini dai profili di lega
  cost={gc:coppa.gc,gt:coppa.gt,corner:cost.corner,cart:cost.cart};
  rho=coppa.rho;legaLbl=comp;base=coppa;baseLbl=comp;}
 const attr=attrito(idC.stile,idO.stile);
 const aC=tc.att*(1-0.06*assC),dC=tc.dif*(1+0.05*assC);
 const aO=to.att*(1-0.06*assO),dO=to.dif*(1+0.05*assO);
 const lamC=clamp(cost.gc*aC*dO*attr.modGol*attr.bC,0.15,4.5);
 const lamO=clamp(cost.gt*aO*dC*attr.modGol*attr.bO,0.15,4.5);
 const dom=clamp(Math.pow(lamC/Math.max(lamO,.1),.15),.88,1.15);
 const nrm=cost.corner/2;
 const muCorC=tc.cp*(to.cc/nrm)*attr.corC*dom*1.08;
 const muCorO=to.cp*(tc.cc/nrm)*attr.corO/dom*0.94;
 const dk=DERBY[[casa,osp].sort().join('|')];
 const boost=dk?dk[1]:1;
 const muKC=tc.cart*to.aggr*attr.modCart*boost;
 const muKO=to.cart*tc.aggr*attr.modCart*boost*1.10;
 return{casa,osp,idC,idO,legaLbl,rho,attr,lamC,lamO,muCorC,muCorO,muKC,muKO,
  derby:dk?dk[0]:null,boost,assC,assO,coppa:!!coppa,base,baseLbl};}

function monteCarlo(ctx,n){
 const M=matriceDC(ctx.lamC,ctx.lamO,ctx.rho);
 const cum=[];let acc=0;
 for(let i=0;i<10;i++)for(let j=0;j<10;j++){acc+=M[i][j];cum.push(acc);}
 const tot=ctx.lamC+ctx.lamO;
 const esiti={'1':0,'X':0,'2':0},cnt={};let sumCC=0,sumCO=0,sumK=0;
 const corTot=new Array(n),karTot=new Array(n);
 let ov25=0,gg=0;
 for(let it=0;it<n;it++){
  const r=Math.random()*acc;let lo=0,hi=99;
  while(lo<hi){const m2=(lo+hi)>>1;if(cum[m2]<r)lo=m2+1;else hi=m2;}
  const gc=(lo/10)|0,go=lo%10;
  esiti[gc>go?'1':(gc===go?'X':'2')]++;
  const key=gc+'-'+go;cnt[key]=(cnt[key]||0)+1;
  if(gc+go>2.5)ov25++;if(gc>0&&go>0)gg++;
  const ap=clamp(1+0.05*((gc+go)-tot),.85,1.25);
  const cc=rNegBin(ctx.muCorC*ap*(gc<go?1.06:1),9);
  const co=rNegBin(ctx.muCorO*ap*(go<gc?1.06:1),9);
  sumCC+=cc;sumCO+=co;corTot[it]=cc+co;
  const mc=gc<go?1.08:(gc-go>=2?0.95:1),mo=go<gc?1.08:(go-gc>=2?0.95:1);
  const k=rNegBin(ctx.muKC*mc,7)+rNegBin(ctx.muKO*mo,7);
  sumK+=k;karTot[it]=k;
 }
 return{n,esiti,cnt,mCorC:sumCC/n,mCorO:sumCO/n,mKar:sumK/n,corTot,karTot,ov25:ov25/n,gg:gg/n};}

function linea(arr,linee){const s=[...arr].sort((a,b)=>a-b);const med=s[s.length>>1];
 let best=linee[0];for(const L of linee)if(Math.abs(L-med)<Math.abs(best-med))best=L;
 const tab=linee.map(L=>[L,arr.reduce((a,x)=>a+(x>L?1:0),0)/arr.length]);
 const pO=tab.find(t=>t[0]===best)[1];return[best,pO,tab];}

function analisi(ctx,ris){
 const f=[],c=ctx.casa,o=ctx.osp,d=ctx.lamC-ctx.lamO,S=DATI.stili;
 if(d>0.75)f.push('Il modello vede <b>'+c+'</b> nettamente favorita: differenziale di gol attesi '+ctx.lamC.toFixed(2)+' contro '+ctx.lamO.toFixed(2)+'. '+o+' dovrà sopravvivere a lunghe fasi di assedio.');
 else if(d>0.30)f.push('<b>'+c+'</b> parte favorita ma non domina ('+ctx.lamC.toFixed(2)+' vs '+ctx.lamO.toFixed(2)+' gol attesi): un episodio può riaprire tutto.');
 else if(d<-0.30)f.push('Segnale controcorrente: nonostante il fattore campo, i rating storici premiano <b>'+o+'</b> ('+ctx.lamO.toFixed(2)+' vs '+ctx.lamC.toFixed(2)+' gol attesi).');
 else f.push('Equilibrio quasi perfetto ('+ctx.lamC.toFixed(2)+' vs '+ctx.lamO.toFixed(2)+' gol attesi): il pareggio pesa più del solito.');
 f.push('Il <b>'+ctx.idC.stile+'</b> di '+ctx.idC.all+' ('+DATI.descr[ctx.idC.stile]+') incrocia il <b>'+ctx.idO.stile+'</b> di '+ctx.idO.all+' ('+DATI.descr[ctx.idO.stile]+'): attrito '+ctx.attr.modGol.toFixed(2)+', '+(ctx.attr.modGol>1.02?'gara che tende ad aprirsi':(ctx.attr.modGol<0.98?'gara che tende a bloccarsi':'ritmo nella norma della lega'))+'.');
 if(ctx.idO.stile==='Blocco Basso'&&S[ctx.idC.stile].possesso>=1)f.push(o+' si abbasserà: il possesso di '+c+' produrrà più angoli e respinte che occasioni nitide.');
 if(ctx.idC.stile==='Blocco Basso'&&S[ctx.idO.stile].possesso>=1)f.push(c+' rinuncerà al pallone anche in casa: '+o+' farà la partita ma resterà esposta alle ripartenze.');
 if(S[ctx.idC.stile].pressing>=1.1&&S[ctx.idO.stile].pressing>=1.1)f.push('Due squadre che riaggrediscono alto: centrocampo zona di duelli, ritmo altissimo e conto dei falli in salita.');
 if(ctx.base){const b=ctx.base,pxm=100*ris.esiti['X']/ris.n,ovm=100*ris.ov25;
  const dx=pxm-b.px,dov=ovm-b.ov;
  f.push('Unione col DNA di <b>'+ctx.baseLbl+'</b>: lì il pareggio esce di solito il '+b.px+'% delle volte → in questo match il modello lo dà al '+pxm.toFixed(1)+'% ('+(dx>=0?'+':'')+dx.toFixed(1)+' punti); l&#39;Over 2.5 di solito è al '+b.ov+'% → qui '+ovm.toFixed(1)+'% ('+(dov>=0?'+':'')+dov.toFixed(1)+' punti).');}
 if(ctx.derby)f.push('È il <b>'+ctx.derby+'</b>: +'+Math.round((ctx.boost-1)*100)+'% di nervosismo atteso — in queste gare i cartellini sfondano la media di lega.');
 if(ctx.assC>0||ctx.assO>0)f.push('Assenze considerate nel calcolo: '+(ctx.assC>0?c+' −'+ctx.assC:'')+(ctx.assC>0&&ctx.assO>0?' · ':'')+(ctx.assO>0?o+' −'+ctx.assO:'')+' titolari pesanti.');
 f.push('Proiezione angoli ('+(ris.mCorC+ris.mCorO).toFixed(1)+' attesi) dal lato di <b>'+(ris.mCorC>=ris.mCorO?c:o)+'</b>.');
 return f;}

/* ---------- interfaccia ---------- */
const COACH_NAMES=Object.keys(DATI.coaches).sort((a,b)=>a.localeCompare(b));
function coachLabel(n){return n+(DATI.coach_prof&&DATI.coach_prof[n]?' 📊':'');}
/* ricerca allenatore a tastiera: digiti "con" → Antonio Conte, Conceição... */
function mostraSugg(side){
 const inp=$('al'+side),box=$('als'+side),q=norm(inp.value);
 if(!q){box.style.display='none';return;}
 // priorità: inizio di nome o cognome ("bian" → Paolo BIANchi prima di FaBIAN)
 const hits=COACH_NAMES.map(n=>{const nn=norm(n);const i=nn.indexOf(q);
   if(i<0)return null;
   const inizioParola=nn.split(' ').some(w=>w.startsWith(q));
   return [n,inizioParola?0:1,i];}).filter(Boolean)
  .sort((a,b)=>a[1]-b[1]||a[2]-b[2]||a[0].localeCompare(b[0]))
  .slice(0,8).map(x=>x[0]);
 let h='';
 for(const n of hits)h+='<div data-n="'+n.replace(/"/g,'&quot;')+'">'+coachLabel(n)+'</div>';
 if(!hits.some(n=>norm(n)===q)&&inp.value.trim().length>2)
  h+='<div data-n="__NEW__">➕ Usa “'+inp.value.trim()+'” come nuovo allenatore</div>';
 box.innerHTML=h;box.style.display=h?'block':'none';}
function setCoach(side,nome){
 const inp=$('al'+side);
 inp.value=nome;
 if(DATI.coaches[nome])$('st'+side).value=DATI.coaches[nome];
 else if(nome&&!COACH_NAMES.includes(nome)){ // nuovo tecnico: registrato per le prossime ricerche
  DATI.coaches[nome]=$('st'+side).value;COACH_NAMES.push(nome);COACH_NAMES.sort((a,b)=>a.localeCompare(b));}
 fillCoachProf(side,nome);
 $('als'+side).style.display='none';
 salvaIdent($('sq'+side).value,{all:nome,stile:$('st'+side).value});}
function confermaCoach(side){
 const t=$('al'+side).value.trim(),team=$('sq'+side).value;
 if(!t){fillCoachProf(side,'');salvaIdent(team,{all:'',stile:$('st'+side).value});return;}
 const c=trovaCoach(t)||(DATI.coaches[t]?t:null);
 if(c){setCoach(side,c);return;}
 // testo non riconosciuto (es. ricerca a metà): torna all'allenatore salvato.
 // Per aggiungerne uno nuovo si usa il tasto ➕ nei suggerimenti.
 const idn=ident(team);
 $('al'+side).value=idn.all||'';
 fillCoachProf(side,idn.all);}
function fillCoachProf(side,name){const el=$('cpr'+side);
 if(!name){el.innerHTML='<i>Nessun allenatore selezionato.</i>';return;}
 const p=DATI.coach_prof?DATI.coach_prof[name]:null;
 if(!p){el.innerHTML='<i>Nessuna statistica verificata per '+name+' nei campionati coperti (2016 → oggi). Niente dati inventati: meglio nessun numero che un numero falso.</i>';return;}
 el.innerHTML=
  '<div>🧢 <b>'+name+'</b> — '+p.n+' partite reali ('+p.anni+')<br><small style="color:#8fa0d8">panchine: '+p.squadre.join(', ')+'</small></div>'+
  '<div>🏆 Vittorie <b>'+p.vin+'%</b> · 🤝 Pareggi <b>'+p.par+'%</b> · ❌ Sconfitte <b>'+p.per+'%</b></div>'+
  '<div>⚽ Gol fatti <b>'+p.gf+'</b> · subiti <b>'+p.gs+'</b> a partita</div>'+
  '<div>📈 Over 2.5: <b>'+p.ov+'%</b> · Gol/Gol: <b>'+p.gg+'%</b></div>'+
  (p.cor!=null?'<div>🚩 Angoli <b>'+p.cor+'</b> a partita</div>':'')+
  (p.gialli!=null?'<div>🟨 <b>'+p.gialli+'</b> gialli · 🟥 <b>'+p.rossi+'</b> rossi a partita</div>':'');}
function fillLega(side,def){const sel=$('lg'+side);sel.innerHTML='';
 for(const l of DATI.ordine_leghe){const op=document.createElement('option');op.textContent=l;sel.appendChild(op);}
 if(def)sel.value=def;}
function fillSquadre(side,def){const l=$('lg'+side).value;const sel=$('sq'+side);sel.innerHTML='';
 for(const n of (perLega[l]||[])){const op=document.createElement('option');op.textContent=n;sel.appendChild(op);}
 if(def&&(perLega[l]||[]).includes(def))sel.value=def;
 caricaSquadra(side);}
function ident(team){try{const s=localStorage.getItem('oc_'+team);if(s)return JSON.parse(s);}catch(e){}
 const t=DATI.squadre[team];return{all:t.all||'',stile:t.stile||'Equilibrato'};}
function salvaIdent(team,idn){try{localStorage.setItem('oc_'+team,JSON.stringify(idn));}catch(e){}}
function caricaSquadra(side){const n=$('sq'+side).value;if(!n)return;
 $('sh'+side).innerHTML=stemma(n,54);$('nm'+side).textContent=n;
 const idn=ident(n);
 $('al'+side).value=idn.all||'';$('st'+side).value=idn.stile;
 $('als'+side).style.display='none';
 fillCoachProf(side,idn.all);fillProf(side,n);}
function fillProf(side,n){const t=DATI.squadre[n],p=t.prof,el=$('pr'+side);
 if(!p){el.innerHTML='<i>Statistiche storiche non disponibili</i>';return;}
 el.innerHTML=
  '<div>⚽ Gol fatti <b>'+p.gf+'</b> · subiti <b>'+p.gs+'</b> a partita</div>'+
  '<div>📈 Over 2.5: <b>'+p.ov+'%</b> · Gol/Gol: <b>'+p.gg+'%</b></div>'+
  '<div>🚩 Angoli: <b>'+t.cp+'</b> fatti · <b>'+t.cc+'</b> concessi a partita</div>'+
  (p.gialli!=null?'<div>🟨 <b>'+p.gialli+'</b> gialli · 🟥 <b>'+p.rossi+'</b> rossi a partita</div>':'')+
  '<div>🎯 Risultati più frequenti: '+p.top.map(x=>'<b>'+x[0]+'</b> ('+x[1]+'%)').join(' · ')+'</div>'+
  '<div class="mini">'+p.n+' partite reali analizzate, pesate sulle ultime 10 stagioni</div>';}

function barRow(lbl,p,grad){return '<div class="row"><span class="lb">'+lbl+'</span>'+
 '<div class="bar"><span style="width:'+(p*100).toFixed(1)+'%;background:'+grad+'"></span></div>'+
 '<span class="pc">'+(p*100).toFixed(1)+'%</span></div>';}

function render(ctx,ris){
 const n=ris.n;
 const p1=ris.esiti['1']/n,px=ris.esiti['X']/n,p2=ris.esiti['2']/n;
 const top=Object.entries(ris.cnt).sort((a,b)=>b[1]-a[1]).slice(0,3);
 const rc=linea(ris.corTot,[7.5,8.5,9.5,10.5,11.5,12.5]);
 const rk=linea(ris.karTot,[2.5,3.5,4.5,5.5,6.5]);
 const cC=rc[1]>=0.5?['OVER',rc[1]]:['UNDER',1-rc[1]];
 const cK=rk[1]>=0.5?['OVER',rk[1]]:['UNDER',1-rk[1]];
 let h='<div class="card">';
 h+='<div class="matchhead">'+stemma(ctx.casa,42)+
    '<div class="mh-t">'+ctx.casa+'<br><small>'+ctx.idC.all+'</small></div>'+
    '<div style="font-weight:900;color:#a3e635">VS</div>'+
    '<div class="mh-t">'+ctx.osp+'<br><small>'+ctx.idO.all+'</small></div>'+stemma(ctx.osp,42)+'</div>';
 h+='<div style="text-align:center;font-size:11.5px;color:#9fb0e8">'+ctx.legaLbl+' · xG '+ctx.lamC.toFixed(2)+' — '+ctx.lamO.toFixed(2)+' · 10.000 simulazioni Monte Carlo</div>';
 if(ctx.derby)h+='<div class="derbybox">🔥 <b>'+ctx.derby+'</b> — nervosismo ×'+ctx.boost.toFixed(2)+'</div>';
 const cand=[
  ['1 · vince '+ctx.casa,p1],['X · pareggio',px],['2 · vince '+ctx.osp,p2],
  ['1X · '+ctx.casa+' o pareggio',p1+px],['X2 · '+ctx.osp+' o pareggio',px+p2],['12 · niente pareggio',p1+p2],
  ['Over 2.5 gol',ris.ov25],['Under 2.5 gol',1-ris.ov25],
  ['Gol/Gol (segnano entrambe)',ris.gg],['No Gol',1-ris.gg],
  [cC[0]+' '+rc[0]+' calci d&#39;angolo',cC[1]],[cK[0]+' '+rk[0]+' cartellini',cK[1]]];
 cand.sort((a,b)=>b[1]-a[1]);
 h+='<h3 class="sec">⭐ Le 3 uscite più probabili</h3>';
 const med=['🥇','🥈','🥉'];
 for(let i=0;i<3;i++)h+='<div class="cons" style="margin-top:6px">'+med[i]+' <b>'+cand[i][0]+'</b> — '+(100*cand[i][1]).toFixed(1)+'%</div>';
 if(ctx.base){const b=ctx.base;
  h+='<h3 class="sec">📊 DNA di '+ctx.baseLbl+' (dati reali)</h3>';
  h+='<div style="font-size:13px;color:#c3d0f8;line-height:1.7">Di solito qui: casa <b>'+b.p1+'%</b> · pareggio <b>'+b.px+'%</b> · trasferta <b>'+b.p2+'%</b><br>Over 2.5: <b>'+b.ov+'%</b> · Gol/Gol: <b>'+b.gg+'%</b>'+
   (b.top?'<br>Risultati più frequenti: '+b.top.map(t=>'<b>'+t[0]+'</b> ('+t[1]+'%)').join(' · '):'')+
   (b.n?'<br><small style="color:#8fa0d8">'+b.n+' partite reali '+(b.anni?'('+b.anni+')':'')+'</small>':'')+'</div>';}
 if(ctx.coppa)h+='<div style="font-size:11px;color:#8fa0d8;margin-top:6px">ℹ️ In coppa: gol, esiti e rho calcolati sulle partite europee reali; angoli e cartellini stimati dai profili di campionato delle due squadre (la fonte europea non li pubblica).</div>';
 h+='<h3 class="sec">Probabilità 1-X-2</h3>';
 h+=barRow('1 · '+ctx.casa,p1,'linear-gradient(90deg,#22d3ee,#6366f1)');
 h+=barRow('X · Pareggio',px,'linear-gradient(90deg,#94a3b8,#64748b)');
 h+=barRow('2 · '+ctx.osp,p2,'linear-gradient(90deg,#f472b6,#fb7185)');
 h+='<h3 class="sec">Risultati esatti più probabili</h3><div class="chips">';
 for(const t of top)h+='<div class="chip"><b>'+t[0]+'</b> '+(100*t[1]/n).toFixed(1)+'%</div>';
 h+='</div>';
 h+='<div style="margin-top:8px"><span class="pill">Over 2.5: <b>'+(100*ris.ov25).toFixed(1)+'%</b></span>'+
    '<span class="pill">Gol/Gol: <b>'+(100*ris.gg).toFixed(1)+'%</b></span></div>';
 h+='<h3 class="sec">🚩 Calci d&#39;angolo</h3>';
 h+='<div style="font-size:14px">'+ctx.casa+' <b>'+ris.mCorC.toFixed(1)+'</b> · '+ctx.osp+' <b>'+ris.mCorO.toFixed(1)+'</b> · totale <b>'+(ris.mCorC+ris.mCorO).toFixed(1)+'</b></div>';
 h+='<div class="cons">➤ Linea consigliata: <b>'+cC[0]+' '+rc[0]+'</b> (probabilità '+(100*cC[1]).toFixed(1)+'%)</div>';
 h+='<div style="margin-top:6px">'+rc[2].filter(t=>Math.abs(t[0]-rc[0])<=1).map(t=>'<span class="pill">Over '+t[0]+': <b>'+(100*t[1]).toFixed(0)+'%</b></span>').join('')+'</div>';
 h+='<h3 class="sec">🟨 Cartellini (gialli + rossi)</h3>';
 h+='<div style="font-size:14px">Media attesa totale: <b>'+ris.mKar.toFixed(2)+'</b></div>';
 h+='<div class="cons">➤ Soglia consigliata: <b>'+cK[0]+' '+rk[0]+'</b> (probabilità '+(100*cK[1]).toFixed(1)+'%)</div>';
 h+='<div style="margin-top:6px">'+rk[2].filter(t=>Math.abs(t[0]-rk[0])<=1).map(t=>'<span class="pill">Over '+t[0]+': <b>'+(100*t[1]).toFixed(0)+'%</b></span>').join('')+'</div>';
 h+='<h3 class="sec">🧠 Analisi tattica</h3><ul class="ana">';
 for(const fr of analisi(ctx,ris))h+='<li>'+fr+'</li>';
 h+='</ul></div>';
 $('out').innerHTML=h;
}

function simula(){
 const casa=$('sqC').value,osp=$('sqO').value;
 if(!casa||!osp)return;
 if(casa===osp){alert('Scegli due squadre diverse 😅');return;}
 const idC={all:$('alC').value.trim()||'—',stile:$('stC').value};
 const idO={all:$('alO').value.trim()||'—',stile:$('stO').value};
 const ctx=parametri(casa,osp,idC,idO,+$('asC').value,+$('asO').value,$('comp').value);
 const ris=monteCarlo(ctx,10000);
 render(ctx,ris);
 $('out').scrollIntoView({behavior:'smooth'});
}

(function init(){
 $('fonte').textContent=DATI.fonte+' · aggiornato al '+DATI.generato;
 const cs=$('comp');
 const add=(v,l)=>{const op=document.createElement('option');op.value=v;op.textContent=l;cs.appendChild(op);};
 add('','🏆 Campionato / incrocio di lega');
 for(const n in (DATI.coppe||{}))add(n,'⭐ '+n);
 cs.addEventListener('change',()=>{const c=DATI.coppe[cs.value];
  $('compinfo').textContent=c?(cs.value+': costanti calcolate su '+c.n+' partite europee reali ('+c.anni+') — scegli due squadre da qualsiasi campionato'):'';});
 for(const side of SIDES){
  const st=$('st'+side);
  for(const s of DATI.ordine_stili){const op=document.createElement('option');op.textContent=s;st.appendChild(op);}
 }
 fillLega('C','Serie A');fillLega('O','Serie A');
 fillSquadre('C','Inter');fillSquadre('O','Milan');
 for(const side of SIDES){
  $('lg'+side).addEventListener('change',()=>fillSquadre(side));
  $('sq'+side).addEventListener('change',()=>caricaSquadra(side));
  const inp=$('al'+side),box=$('als'+side);
  inp.addEventListener('input',()=>mostraSugg(side));
  inp.addEventListener('focus',()=>mostraSugg(side));
  inp.addEventListener('blur',()=>setTimeout(()=>{box.style.display='none';confermaCoach(side);},180));
  box.addEventListener('pointerdown',ev=>{
   const t=ev.target.closest('[data-n]');if(!t)return;
   ev.preventDefault();
   const v=t.getAttribute('data-n');
   setCoach(side,v==='__NEW__'?inp.value.trim():v);});
  $('st'+side).addEventListener('change',()=>salvaIdent($('sq'+side).value,{all:$('al'+side).value.trim(),stile:$('st'+side).value}));
 }
 $('btnSim').addEventListener('click',simula);
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main_cli(sys.argv[1:])   # modalità a comandi (agenti/script)
    else:
        main()                    # modalità interattiva (Colab/terminale)
