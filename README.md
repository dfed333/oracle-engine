# Oracle Engine

App per telefono con le partite del giorno, pronostici calcolati su dati reali e
i numeri veri di ogni allenatore. Si aggiorna da sola due volte al giorno.

## Cosa fa

- **Partite**: all'apertura trovi le partite di oggi (9 campionati + Champions,
  Europa e Conference League), con le probabilità 1-X-2 e le stelline Top 3.
- **Scheda partita**: pronostico, gol, angoli, cartellini, tiri, allenatori,
  precedenti e forma. Per le partite giocate, le statistiche reali.
- **Top 3**: le tre giocate del giorno con il segnale più forte, e la classifica
  delle partite con più gol, angoli, cartellini o tiri attesi.
- **Classifiche**: classifica della stagione e "DNA" di ogni campionato.
- **Allenatori**: ricerca a tastiera e scheda con i numeri di carriera, squadra
  per squadra.
- **Simula**: qualsiasi incrocio, anche tra campionati diversi.

## Da dove vengono i dati

| Dato | Fonte |
|---|---|
| Partite con risultati, tiri, angoli, cartellini, falli, xG (10 stagioni, 11 campionati) | football-data.co.uk |
| Calendari e risultati della stagione, storico delle coppe europee | fixturedownload.com |
| Allenatori in carica e storico dei cambi panchina | Wikipedia (tabelle "Personnel" e "Managerial changes") |

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

Poi: forza dei campionati misurata sui risultati europei, stile di gioco degli
allenatori, derby, precedenti (peso piccolo), assenze indicate dall'utente.
Gol: matrice Dixon-Coles esatta. Angoli e cartellini: 10.000 simulazioni
Monte Carlo correlate al punteggio.

## Aggiornamento

`python build.py` scarica i dati e scrive l'app in `dist/`. Su GitHub il file
`.github/workflows/aggiorna.yml` lo esegue ogni giorno alle 6:30 e alle 0:30
(ora italiana) e pubblica la nuova versione: l'app sul telefono la prende da sola.

Modello probabilistico su dati reali: nessuna previsione è garantita.
Gioca responsabilmente (18+).
