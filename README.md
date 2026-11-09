# ✈️ SkyTrack - Dropzone Run Tracker

SkyTrack è un sistema di monitoraggio automatizzato e in tempo reale per le operazioni di lancio paracadutistico (dropzones). Il sistema traccia la telemetria degli aerei da lancio, riconosce automaticamente le fasi di *run-in* (passaggio in asse) e picchiata, e pubblica i dati di ogni decollo su una dashboard web accessibile da qualsiasi dispositivo.

## ✨ Cosa fa il progetto

* **Rilevamento 100% Autonomo:** Sfrutta i dati di telemetria (coordinate, quota, ground speed) per intercettare l'inizio del lancio e la successiva picchiata, registrando l'intera operazione senza alcun intervento manuale da parte dei piloti o dello staff in terra.
* **Variometro Matematico Intelligente:** Calcola in autonomia la velocità verticale reale ($\text{V/S}$ in ft/min) per identificare la picchiata post-lancio con estrema precisione, superando i limiti di quegli aerei che non trasmettono questo dato tramite il transponder.
* **Supporto Multi-Dropzone:** Monitora simultaneamente il traffico di molteplici aerei situati in dropzone diverse in tutto il mondo, elaborando i dati in parallelo.
* **Dashboard Web Interattiva:** Offre un'interfaccia chiara e moderna per visualizzare i dati. Per ogni lancio calcola e mostra:
  * Traccia GPS esatta disegnata su mappa satellitare.
  * Quota di uscita ($m$ e $ft$).
  * Asse di lancio (Prua / Heading) calcolato tramite trigonometria vettoriale.
  * Velocità al suolo (Ground Speed).
  * Tempo di separazione tra i gruppi consigliato (es. a $300\text{m}$).
* **Fuso Orario Dinamico:** Riconosce le coordinate geografiche della dropzone e adatta automaticamente l'orario dei lanci al fuso orario locale (ignorando il fuso orario del dispositivo da cui si guarda).
* **Recupero Storico e Archiviazione:** Permette l'elaborazione retroattiva della telemetria per ricostruire giornate di lancio passate, e gestisce in autonomia un archivio cronologico degli ultimi 90 giorni di attività.

## ⚙️ Come funziona (Dietro le quinte)

SkyTrack si compone di due elementi essenziali:
1. **Il Motore di Tracciamento:** Un servizio invisibile che analizza in tempo reale i vettori di volo dal radar. Una volta intercettate le condizioni matematiche di una "jump run" (ingresso, livellamento, velocità costante e caduta finale), pacchetta i dati e li invia in cloud.
2. **L'Interfaccia Web:** Un portale interattivo e ottimizzato per smartphone che raccoglie in tempo reale i dati elaborati dal motore, rendendoli fruibili graficamente a piloti, manifest e paracadutisti.

## 📩 Contatti

Sviluppato da **Tommaso Conti**.
Se desideri richiedere l'inserimento del tuo aereo o della tua Dropzone all'interno del circuito di SkyTrack, puoi inviare una richiesta via email a: `tommasoconti98@gmail.com` indicando semplicemente le *Marche dell'aereo* e il *Nome della dropzone*.