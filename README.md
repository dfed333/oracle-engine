# Oracle Engine

App per telefono con le partite del giorno, pronostici calcolati su dati reali e
i numeri veri di ogni allenatore. Si aggiorna da sola due volte al giorno.

## Cosa fa

- **Partite**: all'apertura trovi le partite di oggi (11 campionati, Liga 2 e Ligue 2 +
  Champions, Europa e Conference League), con le probabilità 1-X-2, l'affidabilità di ogni partita e la stellina sulle partite da guardare.
- **Scheda partita**: pronostico, gol, angoli, cartellini, tiri, allenatori,
  precedenti e forma. Per le partite giocate, le statistiche reali.
- **Affidabilità**: ogni partita ha la sua percentuale. È la probabilità dell'uscita
  principale (verificata sul passato) meno il margine d'incertezza di quella
  partita (inizio stagione, allenatore nuovo, squadre viste solo in coppa).
  Dal 65% in su la partita prende la stellina "Da guardare".
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
- **Simula**: qualsiasi incrocio, anche tra campionati diversi.

## Da dove vengono i dati

| Dato | Fonte |
|---|---|
| Partite con risultati, tiri, angoli, cartellini, falli, xG (10 stagioni, 11 campionati) | football-data.co.uk |
| Calendari e risultati della stagione, storico delle coppe europee | fixturedownload.com |
| Allenatori in carica e storico dei cambi panchina | Wikipedia (tabelle "Personnel" e "Managerial changes") |
| Arbitri: storico 2012-2026, cartellini, rigori (11 campionati + 3 coppe) | transfermarkt-datasets (archivio pubblico) |
| Arbitri della stagione in corso e designati | football-data.co.uk (Inghilterra, Scozia); football-data.org con chiave gratuita (7 campionati + Champions) |

## Come ragiona il modello

Per ogni squadra il pronostico unisce tre fonti, ognuna pesata per quante partite
reali la sostengono (ponderazione per credibilità):

1. **Storia della squadra**: 10 stagioni, le più recenti contano di più, corrette
   per la forza degli avversari; quando ci sono gli xG, ogni partita vale metà gol
   reali e metà xG.
2. **L'allenatore in questa squadra**: peso = partite / (partite + 25) per i gol.
   3 partite pesano circa il 10%, nove anni quasi tutto.
3. **La carriera dell'allenatore altrove**: quanto cambia le sue squadre rispetto
   al loro standard, con un tetto (la rosa è diversa).

Seconde divisioni (Liga 2, Ligue 2): la loro forza rispetto alla prima divisione è
misurata sulle squadre promosse e retrocesse, così una neopromossa non sembra una big.
Poi: forza dei campionati misurata sui risultati europei, stile di gioco degli
allenatori, derby, precedenti (peso piccolo), assenze indicate dall'utente.
Verifica sul passato (verifica.py): per ogni stagione dalla terza in poi il modello
rifà i pronostici usando solo le partite precedenti e li confronta con i risultati
veri (oltre 25.000 partite). Da qui lo smorzamento del totale gol (il modello grezzo
esagera le partite "da tanti" o "da pochi" gol) e la correzione di Over/Under e Gol/No Gol.
Taratura (taratura.py): partita per partita, come se il modello girasse ogni giorno,
si sceglie la memoria che sbaglia meno. Risultato: le partite pesano la metà dopo
un anno (non tre); il livello di gol delle coppe si stima con memoria di 8 mesi;
la parte della carriera di un allenatore che si ripete in una squadra nuova è
misurata sui cambi di panchina reali (circa il 10-20%) e ricalcolata a ogni aggiornamento.
Livello della stagione in corso (taratura.fattori_stagione): nel 2026/27, dopo il
Mondiale, nei primi mesi ci sono più gol (2,95 a partita contro 2,65-2,78) e tiri e
meno cartellini (4,05 contro 4,4-4,8). La memoria di un anno arriva in ritardo, quindi
si confrontano valori veri e previsti della stagione, prima su tutti i campionati
insieme e poi per campionato, con pesi scelti sulle 8 stagioni di verifica.
Arbitro: fattore cartellini = (rapporti "cartellini / media" delle sue partite, memoria
1 anno, + 10) / (partite + 10), verificato su 41.557 partite. I suoi rigori non
prevedono quelli futuri: si mostrano ma non entrano nel calcolo.
Gol: matrice Dixon-Coles esatta. Angoli e cartellini: 10.000 simulazioni
Monte Carlo correlate al punteggio.

## Aggiornamento

Facoltativo: la chiave gratuita di football-data.org (registrazione con la sola email)
va messa nei "secrets" del repository con il nome `FOOTBALL_DATA_KEY`: aggiunge gli
arbitri designati di Serie A, Liga, Bundesliga, Ligue 1, Eredivisie, Primeira Liga e
Champions League.

`python build.py` scarica i dati e scrive l'app in `dist/`. Su GitHub il file
`.github/workflows/aggiorna.yml` lo esegue ogni giorno alle 6:30 e alle 0:30
(ora italiana) e pubblica la nuova versione: l'app sul telefono la prende da sola.

Modello probabilistico su dati reali: nessuna previsione è garantita.
Gioca responsabilmente (18+).
