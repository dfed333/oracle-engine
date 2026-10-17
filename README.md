# Oracle Engine

App per telefono con le partite del giorno, pronostici calcolati su dati reali e
i numeri veri di ogni allenatore. Si aggiorna da sola due volte al giorno.

## Cosa fa

- **Partite**: all'apertura trovi le partite di oggi (11 campionati, Liga 2 e Ligue 2 +
  Champions, Europa e Conference League), con le probabilità 1-X-2, l'affidabilità di ogni partita e la stellina sulle partite da guardare.
- **Scheda partita**: pronostico, gol, angoli, cartellini, tiri, allenatori,
  precedenti e forma. Per le partite giocate, le statistiche reali.
- **Il pronostico**: per ogni partita l'uscita più probabile (1, X, 2, Over/Under 2.5,
  Gol/No Gol) con la sua percentuale, verificata sul passato, e "dati solidi/medi/scarsi"
  (solidi = la partita ha le quote o le squadre hanno molte partite nel campionato; medi =
  coppa europea o squadra con poche partite; scarsi = squadra vista solo in coppa).
  Stellina "Da guardare" dal 65% con dati non scarsi.
- **Com'è andata**: sulle partite giocate il pronostico fatto prima della partita con ✓ o ✗,
  e il riepilogo del giorno (quante volte è uscito contro quante ce lo aspettavamo).
- **Da guardare**: le partite con la stellina e il motivo, più la classifica delle
  partite con più gol, angoli, cartellini o tiri attesi.
- **Classifiche**: classifica della stagione e "DNA" di ogni campionato.
- **Allenatori**: ricerca a tastiera e scheda con i numeri di carriera, squadra
  per squadra.
- **Arbitri**: l'arbitro designato nella scheda partita e una scheda per ogni
  arbitro (partite dirette, cartellini, rossi, rigori segnati e falli fischiati a
  partita, contro la media dei campionati che ha arbitrato, stagione per stagione).
- **Versione gratuita**: 1X2, precedenti e "Probabilità chiave" si vedono; le schede
  complete mostrano in alto cosa contengono e il tasto "Sblocca tutto", sotto
  l'anteprima vera con le metriche leggibili e i numeri sfocati.
- **Confronto** (in Classifiche): quali campionati e quali squadre rispettano di più i
  pronostici; i numeri e i risultati esatti più frequenti di ogni campionato negli ultimi
  10 anni, 3 anni e nell'ultimo anno; "Cosa dicono i dati": su quali pronostici il modello
  è più solido in ogni campionato quando è sicuro (≥ 55/60/65/70%).
- **Preferite**: le partite scelte, messe a confronto in una tabella per studiarle
  (restano sul telefono, fino a 4 giorni dopo la partita).

## Da dove vengono i dati

| Dato | Fonte |
|---|---|
| Partite con risultati, tiri, angoli, cartellini, falli, xG e quote pre-partita (10 stagioni, 13 campionati + Serie B, Championship, 2. Bundesliga solo per lo storico) | football-data.co.uk |
| Quote delle partite in arrivo (solo per calcolare le probabilità, mai mostrate) | football-data.co.uk (fixtures.csv) |
| Calendari e risultati della stagione, storico delle coppe europee | fixturedownload.com |
| Allenatori in carica e storico dei cambi panchina | Wikipedia (tabelle "Personnel" e "Managerial changes") |
| Arbitri: storico 2012-2026, cartellini, rigori (11 campionati + 3 coppe) | transfermarkt-datasets (archivio pubblico) |
| Arbitri della stagione in corso e designati | football-data.co.uk (Inghilterra, Scozia); football-data.org con chiave gratuita (7 campionati + Champions) |

## Come ragiona il motore (dal 17/10/2026)

Il punto di partenza sono **le attese del mercato delle scommesse**: le quote medie dei
bookmaker raccolte prima della partita (football-data.co.uk: CSV dei risultati per il
passato, `fixtures.csv` per le partite in arrivo), tolto il margine del bookmaker. Le quote
**non si mostrano mai** nell'app: diventano probabilità e gol attesi.

Perché: sulle 30.895 partite della vecchia verifica (pronostici fatti solo con il passato)
le quote battono il nostro modello statistico su tutto (favorito 52,3% contro 50,9%,
Over/Under 2.5 58,5% contro 56,9%, Gol/No Gol 55,3% contro 54,4%, risultato esatto più
probabile 13,5% contro 13,2%) e qualsiasi mix tra i due peggiora rispetto alle quote da sole.
Quando il modello e le quote non erano d'accordo di oltre 10 punti, avevano ragione le quote.

1. **Quote → gol attesi** (`mercato.py`): per ogni partita con quote si cercano i gol attesi
   delle due squadre (Poisson + Dixon-Coles) che riproducono 1, 2 e Over 2.5 del mercato.
2. **Correzione sul passato** (`verifica.verifica_mercato`): curve "quando le quote dicono X%,
   quante volte esce davvero" per 1, X, 2, Over 2.5 e Gol/Gol, su 50.879 partite di 16
   campionati in 10 anni. Corregge la distorsione nota del mercato: le favorite forti escono
   più di quanto dicono le quote (80-85% → 87%), le sfavorite meno; il Gol/Gol esce circa
   1,5 punti più spesso. Provate e scartate (nessun miglioramento su stagioni mai viste):
   correzioni per campionato, per periodo della stagione, mix con il modello statistico,
   "tendenza" delle squadre che hanno fatto più gol del previsto (non continua).
3. **Forza dalle quote** (per le partite che le quote non le hanno ancora: coppe europee,
   giornate lontane): attacco e difesa di ogni squadra imparati dalle attese del mercato delle
   sue partite precedenti, partita per partita (`mercato.forza_dalle_quote`, passo 0,3).
   Verificata: favorito 50,6% e Over/Under 57,8% contro 51,2% e 57,9% delle quote vere.
   In coppa si moltiplica per la forza dei campionati misurata sui risultati europei e per il
   livello di gol della coppa (`mercato.livello_coppe`, memoria 1 anno): verificato sulle
   2.758 partite di coppa passate stimando il livello solo con le partite precedenti (prima
   l'app prevedeva 3,27 gol a partita contro 2,99 veri, ora 2,95).
4. Squadre senza quote (viste solo in coppa): storia dei risultati (vecchio modello, smorzato).

Da un'unica matrice dei risultati, allineata alle probabilità corrette, escono tutti i numeri
sui gol (risultati esatti, Over/Under, multigol, Gol/Gol). Gli **allenatori** non entrano
nel calcolo dei gol (il mercato li conosce già): si mostrano i loro numeri veri, con la
carriera che comprende anche Serie B, Championship e 2. Bundesliga (lette solo per lo
storico, le loro partite non compaiono nell'app). Angoli e cartellini: profili di squadra,
allenatore, stile, derby e arbitro, 10.000 simulazioni correlate al punteggio.

**Combinazioni**: per ogni partita la scelta più probabile sotto un tetto (80/75/70/65%),
senza le giocate quasi scontate (Over 0.5, Under 4.5, Multigol 1-5, 1-6, 2-6); verificate
sul passato con le stesse regole.

## Aggiornamento

Facoltativo: la chiave gratuita di football-data.org (registrazione con la sola email)
va messa nei "secrets" del repository con il nome `FOOTBALL_DATA_KEY`: aggiunge gli
arbitri designati di Serie A, Liga, Bundesliga, Ligue 1, Eredivisie, Primeira Liga e
Champions League.

`python build.py` scarica i dati e scrive l'app in `dist/`; `python controllo.py` (serve Playwright) la apre in un browser vero, con lo schermo di un telefono, e la usa in ogni schermata e in ogni scheda partita: con un solo errore la pubblicazione si ferma (`--tutto` prova tutte le partite). Su GitHub il file
`.github/workflows/aggiorna.yml` lo esegue ogni giorno alle 6:30 e alle 0:30
(ora italiana) e pubblica la nuova versione: l'app sul telefono la prende da sola.

Modello probabilistico su dati reali: nessuna previsione è garantita.
Gioca responsabilmente (18+).
