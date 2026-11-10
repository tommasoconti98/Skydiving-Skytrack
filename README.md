# ✈️ SkyTrack - Dropzone Run Tracker

SkyTrack è un sistema di monitoraggio automatizzato e in tempo reale per le operazioni di lancio paracadutistico (dropzones).
Il sistema adotta un'architettura **dropzone-centrica** in grado di gestire una flotta di aerei condivisi tra diverse drop, riconosce automaticamente le fasi di *run-in* (passaggio in asse) e picchiata, invia notifiche in tempo reale su Telegram e pubblica i dati di ogni decollo su una dashboard web accessibile da qualsiasi dispositivo.

## ✨ Cosa fa il progetto

* **Rilevamento 100% Autonomo:** Sfrutta i dati di telemetria (coordinate, quota, ground speed) per intercettare l'inizio del lancio e la successiva picchiata, registrando l'intera operazione senza alcun intervento manuale da parte dei piloti o dello staff a terra.
* **Architettura Dropzone-Centrica & Flotta Condivisa:** Le dropzone sono definite dalle loro coordinate fisse sul territorio. Quando un velivolo della flotta opera su una determinata dropzone, il sistema riconosce la sua presenza e associa dinamicamente l'aereo attivo, il modello e la livrea fotografica alla dropzone corrispondente.
* **Variometro Matematico Intelligente:** Calcola in autonomia la velocità verticale reale ($\text{V/S}$ in ft/min) per identificare la picchiata post-lancio con estrema precisione, superando i limiti di quegli aerei che non trasmettono questo dato tramite il transponder.
* **Dashboard Web Interattiva:** Offre un'interfaccia ottimizzata per smartphone (con supporto all'aggiunta sulla schermata Home come Web App) per consultare i lanci registrati.
* Per ogni lancio calcola e mostra:
  * Traccia GPS esatta disegnata su mappa satellitare con indicazione di inizio run e picchiata.
  * Quota di uscita espressa in metri ($m$).
  * Asse di lancio (Prua / Heading) calcolato tramite trigonometria circolare.
  * Velocità al suolo (Ground Speed).
  * Tempo di separazione consigliato tra i gruppi (calcolato a $300\text{ m}$).
  * Collegamento rapido alla visualizzazione radar in diretta su Flightradar24 per l'aereo attivo.
* **Fuso Orario Dinamico:** Riconosce le coordinate geografiche della dropzone e adatta automaticamente l'orario dei lanci al fuso orario locale (ignorando il fuso orario del dispositivo da cui si consulta il portale).
* **Recupero Storico e Archiviazione:** Permette l'elaborazione retroattiva della telemetria da file CSV con geolocalizzazione automatica dei decolli, mantenendo un archivio cronologico consultabile degli ultimi 30 giorni.

## 🤖 Bot Telegram (@SkyTrack_Monitor_bot)

Il sistema include un bot Telegram ufficiale per ricevere aggiornamenti istantanei direttamente sul proprio smartphone:  
👉 **[@SkyTrack_Monitor_bot](https://t.me/SkyTrack_Monitor_bot)**

### 🔔 Notifiche inviate dal Bot:
* 🛫 **Decollo:** Avviso immediato non appena un velivolo inizia la salita in quota sopra la dropzone.
* 🪂 **Resoconto Jump Run:** Report istantaneo al termine della passata con quota di uscita, asse di volo (°), velocità al suolo (kt) e tempo di separazione calcolato.
* 🌅 **Riepilogo Serale:** Notifica automatica a fine giornata con il totale dei decolli effettuati.

### 📌 Comandi disponibili:
* `/start` — Avvia la chat con il bot.
* `/stato` — Controlla lo stato operativo del monitoraggio radar.
* `/lista` — Mostra tutte le dropzone monitorate, il velivolo attualmente attivo e i comandi di iscrizione rapida.
* `/stop` — Disattiva la ricezione delle notifiche relativa alla drop/aereo
* `/nomedrop` — Iscriviti alle notifiche per quella determinata drop (es /salerno).
* `/registrazione` — Iscriviti alle notifiche per quel determinato aereo (es /DFGMG).

## ⚙️ Come funziona (Dietro le quinte)

SkyTrack si compone di tre elementi essenziali:

1. **Il Motore di Tracciamento & Geofencing:** Un servizio in background che analizza costantemente i vettori radar attorno alle dropzone monitorate. Quando rileva i parametri caratteristici di un passaggio di lancio (quota di lancio, rotta costante e discesa ripida post-uscita), estrae la traiettoria, calcola le metriche e aggiorna l'archivio.
2. **Il Bot Telegram:** Un modulo integrato che gestisce le preferenze di notifica degli utenti e distribuisce istantaneamente gli avvisi operativi di decollo e di fine lancio.
3. **L'Interfaccia Web:** Una dashboard consultabile da browser, leggera e mobile-first, che mostra in tempo reale le dropzone attive, l'aereo in uso e le mappe interattive dei passaggi registrati.

## 📩 Contatti

Sviluppato da **Tommaso Conti**.  
Se desideri richiedere l'inserimento del tuo aereo o della tua Dropzone all'interno del circuito di SkyTrack, puoi inviare una richiesta via email a: `tommasoconti98@gmail.com` indicando semplicemente le *Marche dell'aereo* e il *Nome della dropzone*.
