# MasterPayroll Academy

Replica didattica **in Flask** del modulo **Payroll di Odoo** (OCA/payroll 19.0), con localizzazione
italiana, per le lezioni di informatica applicata alle paghe. Ogni allievo entra con il suo login e
lavora sulla sua copia dell'azienda fittizia **Ferro & Transenne Srl** (metalmeccanica): 8 dipendenti,
familiari a carico, contratti, orari, assenze, festività e il mese di settembre 2026 già elaborato.

> ⚠️ **Ambiente formativo, dati simulati.** Aliquote, minimi CCNL, detrazioni e codici tributo sono
> indicativi e servono per imparare. Non usare per paghe reali.

## Corrispondenza con Odoo

| Odoo (modello) | MasterPayroll | Cosa c'è |
|---|---|---|
| `hr.payslip` | Buste paga dipendente | stati Bozza → In attesa → Completata / Rifiutata, numerazione `SLIP/001`, Calcola scheda, Conferma, Storno (nota di credito), Annulla, Imposta a bozza, Riestrai dati, righe figlie nascoste, chatter con tracciamento |
| `hr.payslip.worked_days` | Giorni lavorati | calcolati dall'orario di lavoro, dalle festività (`GLOBAL`) e dalle assenze approvate; negativi o positivi secondo l'impostazione |
| `hr.payslip.input` / `hr.rule.input` | Apporti | creati dagli apporti delle regole della struttura |
| `hr.payslip.line` | Righe busta paga | copia della regola + quantità, tasso, importo, totale; analisi a tabella pivot |
| `hr.payslip.run` + wizard `hr.payslip.employees` | Gruppi buste paga | Genera buste paga, Chiudi lotto, struttura del gruppo (es. tredicesima), note di credito |
| wizard `hr.payslip.change.state` | Cambia stato | azione multipla sulle buste selezionate, con le stesse regole di Odoo |
| `hr.salary.rule` | Regole stipendio | condizione *Sempre vera / Intervallo / Espressione Python*, importo *Fisso / Percentuale / Codice Python*, quantità, regole padre/figlie, registro, apporti |
| `hr.salary.rule.category` | Categorie | gerarchia: i totali delle figlie si sommano nei padri |
| `hr.payroll.structure` | Strutture stipendio | struttura padre ereditata, regole condivise (molti-a-molti) |
| `hr.contribution.register` + report | Registri contributi | report PDF "Righe busta paga per registro contributi" |
| `res.config.settings` | Impostazioni | permessi positivi, annullare buste confermate, conferma senza ricalcolo, modifica righe, codice/categoria obbligatori |
| `report_payslip`, `report_payslipdetails` | Stampa | PDF (ReportLab) con filigrana "ambiente formativo" |
| `mail_template_hr_payslip` | Invia per email | posta in uscita simulata (o SMTP reale se configurato) |
| `hr.employee`, `hr.version`, `resource.calendar`, `hr.leave` | Dipendenti, Contratti, Orari, Assenze, Festività | le dipendenze del modulo |

Il motore (`masterpayroll/payroll.py`) usa gli stessi nomi dei metodi Odoo (`compute_sheet`,
`get_lines_dict`, `_satisfy_condition`, `_compute_rule`, `get_worked_day_lines`, `refund_sheet`…) e nelle
regole sono disponibili le stesse variabili: `payslip`, `employee`, `contract`, `categories`, `rules`,
`result_rules`, `worked_days`, `inputs`, `payroll`, `payslips`, `current_contract`, `tools`, più il codice di
ogni regola già calcolata. Come in Odoo le **trattenute sono negative**. I test di Odoo
(`payroll/tests`) sono stati portati in `tests/test_odoo_port.py`.

## Localizzazione italiana

* Strutture **CCNL Metalmeccanico Industria**: `BASE` → `IT_ORD` (mensile, eredita dalla BASE) e `IT13` (tredicesima).
* Regole: minimo, superminimo, scatti, paga oraria, straordinari 25/50%, permessi non retribuiti dai giorni lavorati,
  INPS 9,19% (+1% oltre la 1ª fascia come regola figlia), IRPEF a scaglioni, detrazioni lavoro dipendente e
  **familiari a carico** (coniuge, figli 21-30 anni, altri), cuneo fiscale, trattamento integrativo, addizionali,
  trasferte esenti, rimborsi, anticipi, contributi azienda, INAIL, TFR, costo aziendale; tredicesima con ratei e aliquota marginale.
* `tools.*` (estensione di `_get_tools_dict`) e `payroll.*` (estensione di `get_payroll_dict`): funzioni fiscali, parametri, scaglioni.
* **Versamenti F24** dai registri contributi (1001, 3802, 3848, crediti 1655 e cuneo, INPS), festività italiane con Pasqua calcolata.

## Struttura: una cartella per attività

Ogni attività è un blueprint Flask in `masterpayroll/blueprints/<attività>/`, con il suo `__init__.py` (le rotte) e
un HTML per ogni pagina in `templates/<attività>/`: `accesso`, `cruscotto`, `dipendenti`, `contratti`, `orari`,
`assenze`, `ferie_permessi`, `buste_paga`, `gruppi`, `cessazioni`, `regole`, `registri`, `impostazioni`, `f24`, `lul`,
`contabilita`, `cu`, `variazioni`, `visite_mediche`, `formazione`, `documenti`, `posta`, `esercizio`, `docente`. In `masterpayroll/templates/` restano solo `base.html` e `_macros.html`.

## Funzioni aggiunte (ottobre 2026)

* **Malattia**: giorni dell'evento per fascia (carenza 1-3 a carico azienda, 4-20 INPS 50%, 21-180 INPS 66,67%);
  regole `MAL_RID` (la quota INPS esce dal lordo, quindi dai contributi) e `MAL_INPS` (indennità anticipata, imponibile
  IRPEF), recuperata nell'F24 come credito INPS.
* **Ferie e permessi**: maturato in dodicesimi (160 h ferie, 104 h ROL ed ex festività, riproporzionati al part-time), goduto dalle assenze, residuo.
* **Cessazione e TFR**: prospetto del fondo anno per anno (quota ÷ 13,5, 0,50% IVS, rivalutazione e imposta sostitutiva),
  tassazione separata con l'aliquota media; busta di liquidazione `IT_CESS` con ferie non godute, ratei di tredicesima,
  conguaglio IRPEF di fine rapporto, ritenuta 1012 e sostitutiva 1713.
* **Conguaglio di fine anno** nella busta di dicembre: `CONG_IRPEF` (imposta dell'anno meno ritenute, detrazione da lavoro per
  i giorni lavorati) e `CONG_CUNEO`. I mesi gennaio-agosto arrivano come **progressivi** del gestionale precedente.
* **Libro unico del lavoro**, **contabilizzazione delle paghe** (prima nota in partita doppia), **Certificazione Unica**.
* F24: i contributi INPS si sommano per valore (dipendente + azienda) e l'indennità di malattia si scala come credito.
* Gli ambienti già creati si aggiornano da soli al primo accesso (`seed.upgrade_workspace`), senza perdere il lavoro.

## Moduli HR dal blocco OCA hr-19.0

* **Variazioni di orario e part-time** (`hr_employee_calendar_planning` + `hr.version`): storico degli orari del
  dipendente; una trasformazione part-time ↔ tempo pieno chiude il contratto il giorno prima e crea una nuova versione.
  Nel mese della variazione la busta ha una riga WORK100 per versione e la paga è pesata sui giorni
  (`payroll.part_time_mese`); ferie, permessi e ratei di tredicesima maturano mese per mese (`payroll.retribuzione_13`).
* **Visite mediche** (`hr_employee_medical_examination`): sorveglianza sanitaria D.Lgs. 81/08, giudizio di idoneità,
  prescrizioni, prossima visita.
* **Corsi di formazione** (`hr_course`): corsi con ore, costo, validità e partecipanti con esito; formazione per dipendente.
* **Documenti del dipendente** (`hr_employee_document`): file fino a 5 MB con scadenza.
* **Scadenzario del personale**: visite, corsi da rinnovare e documenti scaduti o in scadenza (preavviso nelle Tabelle),
  anche nel Cruscotto.

## Controllo del costo del personale (menu Controllo)

I numeri del controller sulle buste **completate** del periodo scelto (`masterpayroll/controllo.py`, blueprint `controllo`):

* **Cruscotto**: costo aziendale (regola COSTO), FTE, costo mensile per FTE, incidenza degli oneri sul lordo, ore pagate e ore
  lavorate davvero, **costo orario pagato ed effettivo** per dipendente, esportazione CSV.
* **Reparti e costo orario**: quota del costo per reparto e costo orario effettivo, base della tariffa di reparto.
* **Assenze e straordinari**: assenteismo (senza ferie, ROL e festività), costo stimato delle assenze, ore e incidenza degli
  straordinari, soglie di allarme.
* **Budget del personale**: budget mensile per reparto (anche proposto dalla media) e scostamento diviso in **effetto ore** ed
  **effetto costo orario**.
* **Turnover e formazione**: cessazioni dell'anno, turnover, costo stimato di un'uscita, costo e ore di formazione per FTE.
* **Premio di risultato**: simulazione con quota presenza, quota straordinari e obiettivo aziendale; costo per l'azienda.
  Aliquota sostitutiva e limite sono parametri da verificare con il consulente del lavoro.

Tre esercitazioni dedicate in Academy → Esercitazioni.

## Esercizio passo passo

Su ogni pagina c'è la finestra a destra **Esercizio passo passo** (ottobre–dicembre 2026, 35 passi): per ogni azione
indica la pagina («Apri la pagina»), i dati da scrivere e il risultato atteso. Le operazioni si spuntano da sole
controllando i dati dell'allievo; le letture si confermano con «Fatto». Panoramica in Academy → Esercizio passo passo;
nell'area docente la colonna «Guida» mostra a che punto è ogni allievo.

## Academy

Area docente: creazione della classe in blocco con password, **ore reali di attività**, consegne delle
esercitazioni (10 già pronte, dal primo cedolino alla tredicesima), accesso all'ambiente di ogni allievo,
ripristino, report CSV. Le formule scritte dagli allievi passano da un valutatore sicuro
(`masterpayroll/safe_eval.py`): niente import, accesso al database o ai dati degli altri.

## Avvio in locale

```bash
pip install -r requirements.txt
ADMIN_PASSWORD=una-password python app.py      # http://localhost:5000  utente: docente
python -m pytest                               # 44 test
```

## Deploy su Railway

1. Nuovo progetto → *Deploy from GitHub repo* → questo repository; aggiungi un database **PostgreSQL**.
2. Variabili: `DATABASE_URL` (riferimento al Postgres), `SECRET_KEY`, `ADMIN_PASSWORD`
   (facoltative: `ADMIN_USERNAME`, e `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM` per email reali).
3. *Generate domain*. Avvio con `gunicorn` (`railway.json` / `Procfile`). Le tabelle si creano al primo avvio.

## Crediti

Modello e logica ricalcano [OCA/payroll](https://github.com/OCA/payroll) (LGPL-3) di Odoo SA e Odoo
Community Association: questa è una riscrittura indipendente a scopo didattico. Interfaccia con
Bootstrap e Bootstrap Icons (MIT), PDF con ReportLab (BSD).

© Maurizio Gustinicchi Consulting — materiale didattico.
