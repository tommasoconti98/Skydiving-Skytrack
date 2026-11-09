# ✈️ SkyTrack - Dropzone Run Tracker

SkyTrack è un sistema di monitoraggio automatizzato e in tempo reale per le operazioni di lancio paracadutistico (dropzones)[cite: 186]. 
Il sistema adotta un'architettura **dropzone-centrica** in grado di gestire una flotta di aerei condivisi tra diversi campi, riconosce automaticamente le fasi di *run-in* (passaggio in asse) e picchiata, invia notifiche in tempo reale su Telegram e pubblica i dati di ogni decollo su una dashboard web accessibile da qualsiasi dispositivo[cite: 7, 186].

## ✨ Cosa fa il progetto

* **Rilevamento 100% Autonomo:** Sfrutta i dati di telemetria (coordinate, quota, ground speed) per intercettare l'inizio del lancio e la successiva picchiata, registrando l'intera operazione senza alcun intervento manuale da parte dei piloti o dello staff a terra[cite: 186].
* **Architettura Dropzone-Centrica & Flotta Condivisa:** Le dropzone sono definite dalle loro coordinate fisse sul territorio[cite: 14]. Quando un velivolo della flotta opera su un determinato campo, il sistema riconosce la sua presenza e associa dinamicamente l'aereo attivo, il modello e la livrea fotografica alla dropzone corrispondente[cite: 7, 14].
* **Variometro Matematico Intelligente:** Calcola in autonomia la velocità verticale reale ($\text{V/S}$ in ft/min) per identificare la picchiata post-lancio con estrema precisione, superando i limiti di quegli aerei che non trasmettono questo dato tramite il transponder[cite: 186].
* **Dashboard Web Interattiva:** Offre un'interfaccia ottimizzata per smartphone (con supporto all'aggiunta sulla schermata Home come Web App) per consultare i lanci registrati[cite: 11, 186]. Per ogni lancio calcola e mostra:
  * Traccia GPS esatta disegnata su mappa satellitare con indicazione di inizio run e picchiata[cite: 11, 186].
  * Quota di uscita espressa in metri ($m$)[cite: 11, 186].
  * Asse di lancio (Prua / Heading) calcolato tramite trigonometria circolare[cite: 7, 186].
  * Velocità al suolo (Ground Speed)[cite: 186].
  * Tempo di separazione consigliato tra i gruppi (calcolato a $300\text{ m}$)[cite: 7, 186].
  * Collegamento rapido alla visualizzazione radar in diretta su Flightradar24 per l'aereo attivo[cite: 11].
* **Fuso Orario Dinamico:** Riconosce le coordinate geografiche della dropzone e adatta automaticamente l'orario dei lanci al fuso orario locale (ignorando il fuso orario del dispositivo da cui si consulta il portale)[cite: 11, 186].
* **Recupero Storico e Archiviazione:** Permette l'elaborazione retroattiva della telemetria da file CSV con geolocalizzazione automatica dei decolli, mantenendo un archivio cronologico consultabile degli ultimi 30 giorni[cite: 11, 12, 186].

## 🤖 Bot Telegram (@SkyTrack_Monitor_bot)

Il sistema include un bot Telegram ufficiale per ricevere aggiornamenti istantanei direttamente sul proprio smartphone:  
👉 **[@SkyTrack_Monitor_bot](https://t.me/SkyTrack_Monitor_bot)**

### 🔔 Notifiche inviate dal Bot:
* 🛫 **Decollo:** Avviso immediato non appena un velivolo inizia la salita in quota sopra la dropzone[cite: 7].
* 🪂 **Resoconto Jump Run:** Report istantaneo al termine della passata con quota di uscita, asse di volo (°), velocità al suolo (kt) e tempo di separazione calcolato[cite: 7].
* 🌅 **Riepilogo Serale:** Notifica automatica a fine giornata con il totale dei decolli effettuati[cite: 7].

### 📌 Comandi disponibili:
* `/start` — Avvia la chat con il bot e mostra il messaggio di benvenuto[cite: 7].
* `/stato` — Controlla lo stato operativo del monitoraggio radar[cite: 7].
* `/lista` — Mostra tutte le dropzone monitorate, il velivolo attualmente attivo e i comandi di iscrizione rapida[cite: 7].
* `/salerno` — Iscriviti alle notifiche per **SkyDive Salerno**[cite: 7].
* `/lucca` — Iscriviti alle notifiche per **SkyDive Lucca**[cite: 7].
* `/nettuno` — Iscriviti alle notifiche per **CrazyFly Nettuno**[cite: 7].
* `/orbetello` — Iscriviti alle notifiche per **SkyDive Costa D'Argento**[cite: 7].
* `/sicilia` — Iscriviti alle notifiche per **SkyDive Sicilia**[cite: 7].

*(È inoltre possibile seguire specifici velivoli digitandone la registrazione, ad es. `/DFSKY`, `/DFGMG`, `/S5CMA` o `/OKAFF`)*[cite: 7].

## ⚙️ Come funziona (Dietro le quinte)

SkyTrack si compone di tre elementi essenziali:

1. **Il Motore di Tracciamento & Geofencing:** Un servizio in background che analizza costantemente i vettori radar attorno alle dropzone monitorate[cite: 7, 186]. Quando rileva i parametri caratteristici di un passaggio di lancio (quota di lancio, rotta costante e discesa ripida post-uscita), estrae la traiettoria, calcola le metriche e aggiorna l'archivio[cite: 7, 186].
2. **Il Bot Telegram:** Un modulo integrato che gestisce le preferenze di notifica degli utenti e distribuisce istantaneamente gli avvisi operativi di decollo e di fine lancio[cite: 7].
3. **L'Interfaccia Web:** Una dashboard consultabile da browser, leggera e mobile-first, che mostra in tempo reale le dropzone attive, l'aereo in uso e le mappe interattive dei passaggi registrati[cite: 11, 186].

## 📩 Contatti

Sviluppato da **Tommaso Conti**[cite: 186].  
Se desideri richiedere l'inserimento del tuo aereo o della tua Dropzone all'interno del circuito di SkyTrack, puoi inviare una richiesta via email a: `tommasoconti98@gmail.com` indicando semplicemente le *Marche dell'aereo* e il *Nome della dropzone*[cite: 186].
