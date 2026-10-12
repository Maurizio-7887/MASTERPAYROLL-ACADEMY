# MasterPayroll Academy

Gestionale paghe **didattico** per le lezioni di elaborazione paghe (UF4 e corsi affini).
Ogni allievo entra con il proprio login e lavora su una copia tutta sua dell'azienda fittizia
**Ferro & Transenne Srl** (metalmeccanica, CCNL Metalmeccanica Industria): 8 dipendenti,
contratti, un mese d'esempio già elaborato, esercitazioni guidate.

> ⚠️ **Ambiente formativo — dati simulati.** Parametri contributivi e fiscali, minimi CCNL e
> codici tributo sono indicativi e servono per imparare. Non usare per paghe reali.

## Cosa si fa in aula

| Area | Cosa insegna |
|---|---|
| **Dipendenti e contratti** | livelli CCNL, minimo, superminimo, scatti, part-time, tempo determinato, apprendistato |
| **Elaborazioni** | il mese paghe: griglia delle variabili (straordinari, assenze, ferie, ROL, premi, rimborsi, anticipi), calcolo, conferma |
| **Cedolino** | lordo → contributi INPS → imponibile fiscale → IRPEF lorda → detrazioni → cuneo fiscale → addizionali → netto; costo aziendale; ferie/ROL; stampa con filigrana |
| **Strutture e regole** | il motore a regole: ogni voce è una regola con condizione e formula, modificabile dagli allievi |
| **Tabelle** | aliquote INPS, scaglioni IRPEF, minimi CCNL, categorie: si cambiano e si misura l'effetto |
| **Versamenti F24** | codici tributo 1001 / 3802 / 3848, crediti da compensare, contributi INPS, scadenza del 16 |
| **Tredicesima** | ratei, tassazione ad aliquota marginale senza detrazioni |
| **Area docente** | creazione allievi in blocco, ore reali di attività, consegne delle esercitazioni, accesso all'ambiente di ogni allievo, ripristino, report CSV |

## Il motore a regole

Il modello è quello del modulo **Payroll di OCA/Odoo** (strutture → regole → categorie), riscritto da zero in Flask
per essere leggibile in aula. Le regole sono eseguite in ordine di sequenza; ogni risultato è disponibile alle regole
successive:

```
categories.BASE          totale della categoria fin qui
rules.IMP_FISC           risultato di una regola precedente
contract.minimo          dati del contratto
inputs.STR25             variabili del mese
param.INPS_DIP           parametri della pagina Tabelle
irpef_annua(reddito)     funzioni fiscali (vedi Guida nell'app)
```

Le formule sono valutate in modo sicuro (`masterpayroll/safe_eval.py`): solo aritmetica, condizioni e le funzioni
della guida; niente import, accesso a file o attributi interni.

## Avvio in locale

```bash
pip install -r requirements.txt
ADMIN_PASSWORD=una-password python app.py      # http://localhost:5000  utente: docente
python -m pytest                               # test del motore e dei flussi
```

Senza `DATABASE_URL` usa SQLite (`masterpayroll.db`).

## Deploy su Railway

1. Nuovo progetto → *Deploy from GitHub repo* → questo repository.
2. Aggiungi un database **PostgreSQL** al progetto (crea `DATABASE_URL`).
3. Variabili del servizio:
   - `DATABASE_URL` → riferimento al Postgres
   - `SECRET_KEY` → stringa casuale lunga
   - `ADMIN_USERNAME` → (facoltativo, default `docente`)
   - `ADMIN_PASSWORD` → password del docente
4. *Generate domain*. Avvio con `gunicorn` (vedi `railway.json` / `Procfile`).

Le tabelle si creano da sole al primo avvio; l'ambiente di ogni utente viene popolato al primo accesso.

## Struttura del codice

```
app.py                      avvio
masterpayroll/
  __init__.py               app factory, CSRF, tracciamento attività, utente docente
  models.py                 utenti, ambienti, anagrafiche, regole, cedolini
  engine.py                 calcolo del cedolino
  safe_eval.py              valutatore sicuro delle formule
  fiscale.py                IRPEF, detrazioni, cuneo fiscale, trattamento integrativo
  seed.py                   Ferro & Transenne Srl, regole, esercitazioni
  views.py / docente.py / auth.py
  templates/ static/        interfaccia (Bootstrap incluso nel repo, nessuna CDN)
tests/
```

## Crediti

Modello concettuale ispirato a [OCA/payroll](https://github.com/OCA/payroll) (LGPL-3).
Interfaccia con [Bootstrap](https://getbootstrap.com) e [Bootstrap Icons](https://icons.getbootstrap.com) (MIT).

© Maurizio Gustinicchi Consulting — materiale didattico.
