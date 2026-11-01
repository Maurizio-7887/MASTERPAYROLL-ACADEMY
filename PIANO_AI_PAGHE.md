# Piano · MasterPayroll «AI per le paghe e le risorse umane»

Bozza dell'1/11/2026, da completare in sessione. Base di partenza: MasterPayroll Academy (replica Flask di OCA/payroll di Odoo
con localizzazione italiana, Ferro & Transenne Srl, 8 dipendenti, CCNL metalmeccanico, controllo del costo del personale).

## 1. Che cosa aggiungiamo: il taglio AI

Il software paghe resta quello che è (calcolo, F24, LUL, CU). L'AI lavora **attorno** al cedolino: interpretare il CCNL,
acquisire presenze e note spese, controllare le anomalie prima della chiusura, rispondere ai dipendenti. Il corso lo deve
dire chiaramente: gli invii ufficiali (UniEmens, F24, CU) restano al software paghe e al consulente del lavoro.

| Laboratorio | Problema | Cosa costruiamo in MasterPayroll | Verifica automatica |
|---|---|---|---|
| L1 Assistente CCNL | dubbi su trasferte, maggiorazioni, malattia, preavvisi: ore sui PDF | ricerca nei testi dei CCNL con risposta e **articolo citato**; LLM facoltativo | 10 domande con articolo atteso |
| L2 Presenze e note spese | presenze in Excel disordinati, CSV del badge, PDF, foto di scontrini | importatore che legge, normalizza, segnala gli errori e crea gli apporti della busta (STR25, STR50, trasferte, rimborsi) | apporti corretti nelle buste di novembre |
| L3 Anomalie prima della chiusura | straordinari raddoppiati, scatti mancati, rimborsi fuori soglia; controlli a campione | storico di 24 mesi con anomalie nascoste; regole + statistica (z-score, IQR) + Isolation Forest; cruscotto «il costo del reparto B è salito del 14% a parità di ore: ecco le 3 cause» | anomalie trovate su quelle nascoste |
| L4 Sportello HR | il 40% del tempo sulle stesse domande (ferie residue, CU, bonus) | sportello che risponde dai dati del dipendente (ferie e permessi, buste, CU) e dalle policy aziendali, con registro delle domande | risposte giuste su 10 domande tipo |
| L5 Seconda opinione | «la busta è giusta?» | confronto busta di MasterPayroll ↔ **ccnl-engine** (lordo, netto, costo) e spiegazione delle differenze | differenze riconciliate |
| L6 Regole e rischi | AI Act, GDPR, Statuto dei lavoratori | modulo di teoria con casi: che cosa si può fare e che cosa no | quiz |

## 2. Dalle repository ricevute

**ccnl-engine** (Lucas Puerari, licenza **MIT**, versione 0.6.0 alpha, Python ≥ 3.12, dipende solo da pydantic)
- Provato qui: gira e calcola l'anno 2026 del metalmeccanico Federmeccanica (livelli D1…A1). Per C1, 8 dipendenti:
  lordo 26.044,51 €, netto 21.519,25 €, costo 36.256,05 €; `is_payable = False` con 13 dati mancanti (detrazione ulteriore,
  fondo di tesoreria, categoria INPS, scatti, fondo pensione) che il nostro gestionale conosce già.
- Contiene 135 schede di CCNL in `docs/contracts/*.md` con articoli e fonti: sono la **base documentale del laboratorio L1**
  (MIT: si possono usare citando la fonte).
- Uso previsto: dipendenza `ccnl-engine==0.6.0` (versione bloccata) per il laboratorio L5. È alpha: le API possono cambiare
  e molti CCNL «estratti, non ancora revisionati» → nel corso è una seconda opinione, non la verità.
- Attenzione: i minimi del nostro seed (D1 1.800 €…) sono indicativi; il confronto con ccnl-engine mostrerà differenze.
  Decidere se allineare le tabelle del seed ai valori dell'engine (citati ma non revisionati) o tenerle e farne un esercizio.

**ERPNext develop** (GPL-3)
- Il modulo paghe **non c'è più**: dalla versione 14 HR e Payroll sono stati spostati nell'app separata Frappe HRMS
  (patch `v14_0/remove_hr_and_payroll_modules`). Restano anagrafica dipendente (istruzione, esperienze precedenti, gruppi),
  calendari festività e timesheet.
- Utile solo come idea per l'anagrafica (storico formazione ed esperienze) e per il timesheet che alimenta L2. Licenza GPL:
  niente codice copiato, solo funzioni riscritte. Se servono le paghe di Frappe, va caricato il repository `frappe/hrms`.

**Odoo / OCA payroll**: resta il modello di riferimento (già replicato). Nessuna modifica al motore.

## 3. Scelte tecniche

- **AI senza chiave e con chiave.** Tutto deve funzionare anche senza modello linguistico: ricerca testuale (BM25/TF-IDF)
  con citazione per L1, parser deterministici per L2, statistica per L3, intenti e dati per L4. Se si imposta una chiave
  (variabile `LLM_API_KEY`, fornitore da decidere), si attiva la risposta in linguaggio naturale sopra gli stessi risultati.
  Così i costi sono sotto controllo e in aula funziona anche senza rete.
- **Privacy.** Dati simulati. Con LLM esterno si inviano solo testi di CCNL e domande, mai dati dei dipendenti, salvo
  scelta esplicita del docente; registro di ogni chiamata.
- **Librerie nuove**: `ccnl-engine` (L5), `scikit-learn` (Isolation Forest in L3), `openpyxl` e `pdfplumber` (L2).
  Python 3.12 su Railway è compatibile.
- **Struttura**: un blueprint per laboratorio (`masterpayroll/blueprints/ai_ccnl`, `ai_presenze`, `ai_anomalie`,
  `ai_sportello`, `ai_confronto`), logica in `masterpayroll/ai/`, file d'esempio in `masterpayroll/static/ai/`.
- **Seed**: storico ottobre 2024 → settembre 2026 per gli 8 dipendenti con 6-8 anomalie nascoste e documentate per il
  docente; presenze di novembre 2026 in 4 formati sporchi; 15 note spese (PDF e immagini).

## 4. Il corso

Titolo provvisorio «AI per le paghe e le risorse umane» (ruolo: HR Data & AI Specialist), circa 30 ore: 6 moduli (uno per
laboratorio) con lezione, quiz, esercitazione corretta in automatico, esercizio passo passo e materiali per il docente.
Prezzo da decidere (riferimento: gli altri corsi avanzati a 297 €). Nel marketing niente promesse tipo «taglia l'80% del
lavoro»: numeri solo se misurati nel laboratorio.

Contenuti del modulo L6 (da verificare alla stesura):
- AI Act: i sistemi usati per decisioni sul rapporto di lavoro, assegnazione dei compiti o monitoraggio e valutazione dei
  lavoratori sono **ad alto rischio** (allegato III, punto 4); obblighi di trasparenza per i chatbot; date di applicazione
  rinviate dal pacchetto Omnibus → ricontrollare.
- GDPR: base giuridica, minimizzazione, art. 22 (decisioni automatizzate), valutazione d'impatto.
- Statuto dei lavoratori, art. 4 (controlli a distanza) e accordi sindacali.

## 5. Ordine di lavoro (stasera e seguenti)

1. Decidere i punti aperti (sotto).
2. Seed: storico 24 mesi con anomalie + file sporchi di presenze e note spese.
3. L3 Anomalie (si appoggia al controllo già esistente: effetto ore / effetto costo orario).
4. L2 Presenze e note spese → apporti delle buste di novembre.
5. L5 Seconda opinione con ccnl-engine.
6. L1 Assistente CCNL sui testi di ccnl-engine.
7. L4 Sportello HR.
8. L6, quiz, esercitazioni, esercizio passo passo, area docente, test, README, scheda sul sito.

## 6. Decisioni (1/11/2026)

- **Estensione di MasterPayroll**: nuovo menu «AI Lab» nello stesso ambiente, stessi allievi, stessa Ferro & Transenne.
- **Modello linguistico: facoltativo, spento di default.** Tutto funziona con il motore locale. Variabile `LLM_API_KEY`
  (più `LLM_PROVIDER`): se il docente la imposta su Railway si attiva la risposta in linguaggio naturale; tetto mensile di
  chiamate per allievo e registro delle chiamate. La chiave e il costo sono del docente, gli allievi non ne hanno bisogno.
- **Minimi CCNL: si lasciano quelli indicativi del seed** e si aggiunge la tabella dei minimi 2026 di ccnl-engine come
  confronto; l'esercizio di L5 chiede di spiegare le differenze.
- **Contratti**: metalmeccanico Federmeccanica, commercio Confcommercio, logistica e trasporto Confetra (schede già in
  ccnl-engine). Per L5 e per gli esempi di commercio e logistica si aggiungono due aziende «ospiti» con pochi dipendenti
  nello stesso ambiente, senza toccare Ferro & Transenne.
