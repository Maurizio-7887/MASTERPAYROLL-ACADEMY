"""Esercizio completo: ottobre-dicembre 2026 usando TUTTO il programma, AI Lab compreso.

Stessa struttura dei passi dell'esercizio «ottobre-dicembre» (vedi __init__.py): la finestra a destra e il documento PDF
scaricabile leggono questa stessa lista, quindi dicono sempre le stesse cose. Ogni passo comincia con il comando di menu
(«Menu») e indica campi e pulsanti con i nomi che si vedono sullo schermo.
Si parte da un ambiente ripristinato; il nuovo assunto (matricola 0009) entra in tutte le buste da ottobre in poi.
"""
import json
from datetime import date

from ...models import AiStato, ControlloPersonale, DocumentoDipendente, MailMail
from . import (DIC, NOV, OTT, _apporto, _assenza, _contab, _corso, _emp, _gruppo, _q, _tutte, _visita)

CODICE = "completo-2026"
TITOLO = "Esercizio completo: tutto il programma, AI Lab compreso (ott-dic 2026)"
P = []


def passo(pid, cap, titolo, ep, campi, attesa="", nota="", check=None, args=None):
    P.append({"id": pid, "cap": cap, "titolo": titolo, "ep": ep, "args": args or {}, "campi": campi,
              "attesa": attesa, "nota": nota, "check": check})


def _esito(lab):
    r = _q(AiStato).filter_by(chiave="esiti").first()
    return bool(r and json.loads(r.valore or "{}").get(lab, {}).get("superato"))


def _contratto_nuovo():
    e = _emp("0009")
    if not e:
        return False
    return any(c.state == "open" and c.date_start == date(2026, 10, 1) and c.livello and c.livello.codice == "C1"
               and c.struct and c.struct.code == "IT_ORD" for c in e.contract_ids)


def _documento_nuovo():
    e = _emp("0009")
    return bool(e) and _q(DocumentoDipendente).filter_by(employee_id=e.id, tipo="contratto").first() is not None


def _email_ottobre():
    run = _gruppo(*OTT)
    if not run:
        return False
    ids = {s.id for s in run.slip_ids}
    return len({m.payslip_id for m in _q(MailMail) if m.payslip_id in ids}) >= 9


def _budget():
    r = _q(ControlloPersonale).filter_by(anno=2026).first()
    return bool(r and json.loads(r.budget or "{}"))


def _chiuso(run, n):
    return _tutte(run, "done", n) and getattr(run, "state", "") == "close"


C1, C2, C3, C4, C5, C6 = ("1 · Si comincia", "2 · Un nuovo assunto", "3 · Le paghe di ottobre",
                          "4 · Il controllo del costo del personale", "5 · Novembre con l'AI Lab", "6 · Dicembre e fine anno")

# ------------------------------------------------------------------------------------------------ 1 · Si comincia
passo("pulito", C1, "Parti da un ambiente pulito", "cruscotto.dashboard",
      [("Menu", "clic sul logo MasterPayroll Academy (Cruscotto)"),
       ("In fondo alla pagina", "nella casella scrivi RIPRISTINA"), ("Pulsante", "Ripristina l'ambiente"),
       ("Dopo il ripristino", "8 dipendenti e il gruppo di settembre 2026 già confermato")],
      nota="Il ripristino cancella solo il TUO ambiente. Questo esercizio si fa dall'inizio alla fine nell'ordine dei passi.")
passo("tabelle", C1, "Leggi le tabelle del CCNL: livelli e minimi", "impostazioni.tabelle",
      [("Menu", "Configurazione → Parametri, IRPEF, livelli CCNL, azienda"),
       ("Sezione «Livelli CCNL»", "trova il livello C1 «Operaio qualificato»: minimo 2.000 €, scatto 24,50 €"),
       ("Sezione «Parametri»", "guarda la trasferta esente (46,48 € al giorno) e il divisore del TFR (13,5)")],
      nota="Sono i numeri che userai per il nuovo assunto. Sono tabelle didattiche: nel laboratorio «Seconda opinione» dell'AI Lab le confronterai con ccnl-engine.")
passo("ai-panoramica", C1, "Guarda la panoramica dell'AI Lab", "ai.index",
      [("Menu", "AI Lab → Panoramica dei laboratori"), ("Leggi", "i sei laboratori e la barra delle esercitazioni superate"),
       ("Badge in alto", "«Motore locale»: tutto funziona senza modello linguistico")],
      nota="L'AI non sostituisce il software paghe: lavora attorno al cedolino. Userai i laboratori nel capitolo 5.")

# ------------------------------------------------------------------------------------------------ 2 · Un nuovo assunto
passo("assunto", C2, "Assumi Alessio Santini: la scheda del dipendente", "dipendenti.employee",
      [("Menu", "Dipendenti → Dipendenti → pulsante «Nuovo»"), ("Matricola", "0009"), ("Cognome", "Santini"),
       ("Nome", "Alessio"), ("Mansione", "Addetto imballaggio e spedizione"), ("Reparto", "Packaging"),
       ("Qualifica", "operaio"), ("Email lavoro", "alessio.santini@ferroetransenne.example"), ("Attivo", "spuntato"),
       ("Tab «Informazioni di lavoro» · Orario di lavoro", "Tempo pieno 40 ore (lun-ven 8-12 / 13-17)"),
       ("Tab «Informazioni private»", "Codice fiscale SNTLSS99A01C745X (fittizio), data di nascita 01/01/1999"),
       ("Pulsante", "Salva (in alto a sinistra)")],
      attesa="La scheda di Santini salvata, con il messaggio «Ora crea il contratto».",
      check=lambda: bool(_emp("0009") and _emp("0009").active))
passo("contratto", C2, "Crea il contratto di Santini e mettilo «In corso»", "contratti.contract",
      [("Menu", "Dipendenti → Contratti → pulsante «Nuovo»"), ("Dipendente", "Santini Alessio"),
       ("Tipo di contratto", "indeterminato"), ("Reparto", "Packaging"), ("CCNL", "Metalmeccanico Industria"),
       ("Data inizio contratto", "01/10/2026"), ("Fine periodo di prova", "30/11/2026"),
       ("Orario di lavoro", "Tempo pieno 40 ore"), ("Struttura stipendio", "IT_ORD · CCNL Metalmeccanico Industria - mensile"),
       ("Livello CCNL", "C1 · Operaio qualificato, e spunta «prendi paga base e scatto dalla tabella livelli»"),
       ("Pulsante", "Salva, poi il pulsante «In corso»")],
      attesa="Contratto in corso dal 1° ottobre: paga base 2.000 €, nessuno scatto.",
      nota="Senza un contratto «In corso» il dipendente non entra nei gruppi di buste paga.", check=_contratto_nuovo)
passo("documento", C2, "Carica il contratto firmato nei documenti di Santini", "documenti.elenco",
      [("Menu", "Dipendenti → Documenti dei dipendenti"), ("Dipendente", "Santini Alessio"),
       ("Tipo", "Contratto / lettera di assunzione firmata"), ("Descrizione", "Contratto di assunzione firmato"),
       ("File", "un PDF qualsiasi (va bene anche questo documento dell'esercizio)"), ("Pulsante", "Carica")],
      attesa="Il documento compare nell'elenco di Santini e si scarica con il nome del file.", check=_documento_nuovo)
passo("visita", C2, "Registra la visita preventiva di Santini", "visite_mediche.elenco",
      [("Menu", "Dipendenti → Visite mediche"), ("Dipendente", "Santini Alessio"), ("Data della visita", "28/09/2026"),
       ("Tipo", "Preventiva (prima di adibire alla mansione)"), ("Esito (giudizio)", "Idoneo"),
       ("Prossima visita entro", "28/09/2027"), ("Medico competente", "Dott.ssa Rinaldi"), ("Pulsante", "Registra")],
      attesa="La visita è registrata e nello scadenzario Santini risulta in regola fino al 28/09/2027.",
      check=lambda: _visita("0009", date(2026, 9, 28), "idoneo", date(2027, 9, 28)))
passo("corso", C2, "Iscrivi Santini al corso di formazione generale sulla sicurezza", "formazione.corsi",
      [("Menu", "Dipendenti → Corsi di formazione"), ("Titolo", "Formazione generale dei lavoratori (4 ore)"),
       ("Categoria", "Sicurezza - formazione generale"), ("Ente / docente", "RSPP aziendale"), ("Dal / Al", "05/10/2026"),
       ("Ore", "4"), ("Costo totale €", "0"), ("Stato", "Svolto"), ("Pulsante", "Crea"),
       ("Poi, nella scheda del corso", "aggiungi Santini Alessio con esito «Superato»")],
      attesa="In Dipendenti → Corsi di formazione → formazione per dipendente, Santini ha il corso generale superato.",
      check=lambda: _corso("0009", "sicurezza_generale", date(2026, 10, 5)))

# ------------------------------------------------------------------------------------------------ 3 · Le paghe di ottobre
passo("malattia", C3, "Moretti Paolo è in malattia dal 12 al 30 ottobre", "assenze.leave",
      [("Menu", "Assenze → Assenze → pulsante «Nuovo»"), ("Dipendente", "Moretti Paolo"), ("Tipo di assenza", "Malattia"),
       ("Dal", "12/10/2026"), ("Al", "30/10/2026"), ("Approva subito", "lascia la spunta"), ("Pulsante", "Salva")],
      attesa="Assenza approvata: 3 giorni di carenza a carico dell'azienda, 16 indennizzati dall'INPS al 50%.",
      check=lambda: _assenza("0008", "MAL", date(2026, 10, 12), date(2026, 10, 30)))
passo("gruppo-ott", C3, "Crea il gruppo delle buste di ottobre", "gruppi.run_new",
      [("Menu", "Libro paga → Gruppi buste paga → pulsante «Nuovo»"), ("Nome", "Ottobre 2026"), ("Dal", "01/10/2026"),
       ("Al", "31/10/2026"), ("Struttura", "lasciala vuota (vale quella del contratto)"), ("Pulsante", "Salva")],
      attesa="Un gruppo in bozza, ancora senza buste.", check=lambda: _gruppo(*OTT) is not None)
passo("genera-ott", C3, "Genera le buste di tutti e 9 i dipendenti", "gruppi.runs",
      [("Menu", "Libro paga → Gruppi buste paga → apri «Ottobre 2026»"), ("Pulsante", "Genera buste paga"),
       ("Dipendenti", "tutti e 9 spuntati, Santini compreso"), ("Pulsante", "Genera")],
      attesa="9 buste calcolate (stato «In attesa»): festività, assenze e il nuovo assunto sono già dentro.",
      check=lambda: len(getattr(_gruppo(*OTT), "slip_ids", []) or []) >= 9)
passo("regola-str", C3, "Guarda come è fatta la regola dello straordinario", "regole.rules",
      [("Menu", "Configurazione → Regole stipendio"), ("Apri", "la regola STR25 «Straordinario feriale 25%»"),
       ("Leggi", "condizione: «inputs.STR25.amount > 0»; importo a PERCENTUALE: ore × 125% × paga oraria (ORARIA)")],
      nota="Le regole sono come quelle di Odoo: l'apporto STR25 che scrivi nella busta diventa la quantità della riga.")
passo("str-ott", C3, "Bianchi Marco ha fatto 10 ore di straordinario", "gruppi.runs",
      [("Menu", "Libro paga → Gruppi buste paga → «Ottobre 2026» → busta di Bianchi Marco"),
       ("Tab «Giorni lavorati e apporti»", "accanto a STR25 scrivi 10"), ("Pulsante", "Calcola scheda")],
      attesa="Nuova riga STR25: 10 ore × 125% × paga oraria. Salgono lordo, INPS e IRPEF.",
      check=lambda: _apporto(_gruppo(*OTT), "0001", "STR25", 10))
passo("trasf-ott", C3, "Esposito Giuseppe è stato 3 giorni in trasferta", "gruppi.runs",
      [("Menu", "«Ottobre 2026» → busta di Esposito Giuseppe"), ("Tab «Giorni lavorati e apporti»", "TRASF = 3"),
       ("Pulsante", "Calcola scheda")],
      attesa="3 × 46,48 = 139,44 € di trasferta ESENTE: entra nel netto ma non nei contributi né nell'IRPEF.",
      check=lambda: _apporto(_gruppo(*OTT), "0004", "TRASF", 3))
passo("leggi-santini", C3, "Leggi la prima busta di Santini", "gruppi.runs",
      [("Menu", "«Ottobre 2026» → busta di Santini Alessio → tab «Calcolo stipendio»"),
       ("BASIC", "2.000,00: mese intero, assunto il 1° ottobre"), ("INPS_DIP", "contributi del lavoratore, negativi"),
       ("NET", "il netto: la somma di tutte le righe")],
      nota="Le trattenute sono NEGATIVE, come in Odoo. Il TFR e i contributi dell'azienda non sono nella busta del dipendente.")
passo("conferma-ott", C3, "Conferma le 9 buste di ottobre e chiudi il gruppo", "gruppi.runs",
      [("Menu", "Libro paga → Gruppi buste paga → «Ottobre 2026»"), ("Elenco buste", "spunta tutte le buste"),
       ("Azione", "Cambia stato → Conferma"), ("Pulsante", "Esegui sui selezionati"), ("Poi", "pulsante «Chiudi lotto»")],
      attesa="9 buste «Completata» e gruppo chiuso: da ora entrano in F24, LUL, contabilità e controllo.",
      check=lambda: _chiuso(_gruppo(*OTT), 9))
passo("email-ott", C3, "Invia le buste di ottobre per email", "gruppi.runs",
      [("Menu", "«Ottobre 2026»"), ("Elenco buste", "spunta tutte le buste"), ("Azione", "Invia per email"),
       ("Pulsante", "Esegui sui selezionati"), ("Controlla", "Libro paga → Posta in uscita: 9 email con il PDF allegato")],
      attesa="9 email preparate (simulate se il server non ha la posta configurata).",
      nota="In produzione le email partono dall'indirizzo dell'azienda configurato sul server.", check=_email_ottobre)
passo("f24-ott", C3, "Prepara l'F24 di ottobre (scadenza 16 novembre)", "f24.f24",
      [("Menu", "Libro paga → Versamenti F24"), ("Mese", "Ottobre 2026"),
       ("Erario", "1001 IRPEF, 3802 e 3848 addizionali; a credito trattamento integrativo e cuneo"),
       ("INPS", "contributi dipendente + azienda MENO l'indennità di malattia anticipata a Moretti")])
passo("contab-ott", C3, "Registra le paghe di ottobre in contabilità", "contabilita.prima_nota_paghe",
      [("Menu", "Libro paga → Contabilizzazione paghe"), ("Mese", "Ottobre 2026"), ("Controlla", "la scritta «quadra»: Dare = Avere"),
       ("Pulsante", "Registra in contabilità")],
      attesa="Costi del personale in Dare; debiti verso dipendenti, INPS, Erario, INAIL e fondo TFR in Avere.",
      check=lambda: _contab(2026, 10))
passo("lul-ott", C3, "Controlla il Libro unico di ottobre", "lul.libro",
      [("Menu", "Libro paga → Libro unico del lavoro"), ("Mese", "Ottobre 2026"),
       ("Moretti", "MA dal 12 al 30"), ("Santini", "presente dal 1° ottobre, nella sezione presenze e nella sezione paga")])

# ------------------------------------------------------------------------------------------------ 4 · Controllo
passo("cruscotto", C4, "Leggi il cruscotto del costo del personale", "controllo.cruscotto",
      [("Menu", "Controllo → Cruscotto del costo del personale"), ("Periodo", "2026, da Settembre a Ottobre → «Analizza»"),
       ("Leggi", "costo aziendale, FTE, costo mensile per FTE, incidenza degli oneri, costo orario pagato ed effettivo")],
      nota="Il controllo legge solo le buste COMPLETATE: per questo ottobre va confermato prima.")
passo("reparti", C4, "Confronta il costo orario dei reparti", "controllo.reparti",
      [("Menu", "Controllo → Reparti e costo orario"), ("Periodo", "settembre-ottobre 2026"),
       ("Leggi", "quale reparto costa di più all'ora e dove è entrato Santini (Packaging)")])
passo("budget", C4, "Imposta il budget del personale 2026", "controllo.budget",
      [("Menu", "Controllo → Budget del personale"), ("Periodo", "2026, settembre-ottobre"),
       ("Pulsante", "Proponi dalla media del periodo"), ("Poi", "correggi a piacere e premi «Salva il budget»")],
      attesa="Budget salvato per reparto; la tabella mostra lo scostamento diviso in effetto ore ed effetto costo orario.",
      check=_budget)
passo("premio", C4, "Simula il premio di risultato", "controllo.premio_risultato",
      [("Menu", "Controllo → Premio di risultato"), ("Leggi", "quota presenza, quota straordinari e quota aziendale per dipendente"),
       ("Prova", "cambia l'obiettivo aziendale raggiunto nei parametri e guarda come cambia il costo")],
      nota="Aliquota sostitutiva e limite agevolabile sono parametri da verificare ogni anno con il consulente del lavoro.")

# ------------------------------------------------------------------------------------------------ 5 · Novembre con l'AI Lab
passo("ai-ccnl", C5, "AI Lab 1 · Rispondi ai dubbi sul contratto con l'assistente CCNL", "ai.ccnl",
      [("Menu", "AI Lab → 1. Assistente CCNL"), ("Prova una domanda", "«Quanto dura il comporto di malattia nella logistica?» → «Cerca»"),
       ("Leggi la scheda", "valore, articolo, pagina, citazione e stato di verifica"),
       ("Esercitazione", "in fondo alla pagina: 10 domande, scegli il valore e premi «Verifica» (almeno 8 giuste)")],
      attesa="Badge «Esercitazione superata» in alto.", check=lambda: _esito("ccnl"))
passo("ai-presenze", C5, "AI Lab 2 · Presenze e note spese di novembre nelle buste", "ai.presenze",
      [("Menu", "AI Lab → 2. Presenze e note spese"), ("Riquadro 1", "scarica e apri i 4 file: Excel, badge, note spese, scontrino"),
       ("Riquadro 2, «otto»", "Verdi 18/11: scrivi 8"), ("«ESPOSITO PINO»", "scegli 0004 Esposito Giuseppe"),
       ("Uscita mancante", "Moretti 19/11: scrivi 17:00"), ("Scontrino del taxi", "leggi l'importo dalla foto e scrivilo"),
       ("Pulsante", "Salva le correzioni"),
       ("Riquadro 3, pulsante", "Registra le assenze e scrivi gli apporti nelle buste di novembre")],
      attesa="Gruppo «Novembre 2026» con 9 buste calcolate: Bianchi STR25 12,5; Verdi STR25 1 e STR50 6; Esposito TRASF 3; "
             "Conti e Moretti straordinari dal badge; rimborsi di Rossi e Galli. Ferie, permesso e malattia registrati.",
      nota="La procedura si ferma sui casi dubbi: è voluto. Una proposta non viene mai applicata da sola.",
      check=lambda: _esito("presenze"))
passo("leggi-nov", C5, "Controlla una busta di novembre creata dall'AI Lab", "gruppi.runs",
      [("Menu", "Libro paga → Gruppi buste paga → «Novembre 2026» → busta di Verdi Luca"),
       ("Tab «Giorni lavorati e apporti»", "STR25 = 1, STR50 = 6 (il 13 novembre è il patrono), malattia il 26-27"),
       ("Tab «Calcolo stipendio»", "righe STR25 e STR50 con le maggiorazioni")])
passo("chiudi-nov", C5, "Conferma le 9 buste di novembre e chiudi il gruppo", "gruppi.runs",
      [("Menu", "«Novembre 2026»"), ("Azione", "spunta tutte → Cambia stato → Conferma → Esegui sui selezionati"),
       ("Poi", "pulsante «Chiudi lotto»")], check=lambda: _chiuso(_gruppo(*NOV), 9))
passo("ai-anomalie", C5, "AI Lab 3 · Trova le 7 anomalie nascoste nello storico", "ai.anomalie",
      [("Menu", "AI Lab → 3. Anomalie prima della chiusura"),
       ("Riquadro di destra", "reparto Saldatura, base 2026-07, mese 2026-09 → «Scomponi»: leggi le 3 cause"),
       ("Esercitazione", "per ogni riga segnalata scegli il tipo (o «legittima») → «Verifica le segnalazioni»"),
       ("Per approfondire", "scarica il CSV e prova l'Isolation Forest in Python o su Colab")],
      attesa="Almeno 6 anomalie su 7 con il tipo giusto e al massimo 2 falsi allarmi.",
      nota="Le regole non vedono gli straordinari «gonfiati»: li trovano la statistica e l'Isolation Forest.",
      check=lambda: _esito("anomalie"))
passo("ai-confronto", C5, "AI Lab 5 · Seconda opinione: confronta le buste con ccnl-engine", "ai.confronto",
      [("Menu", "AI Lab → 5. Seconda opinione (ccnl-engine)"),
       ("Leggi", "minimo e scatti di MasterPayroll contro quelli del motore, aliquota INPS, dati mancanti"),
       ("Per ogni dipendente", "scegli la causa della differenza più grande (per l'apprendista, la sua percentuale)"),
       ("Pulsante", "Verifica")], attesa="Al massimo una causa sbagliata.",
      nota="Santini (C1, assunto a ottobre) ha solo la differenza di minimo: nessuno scatto ancora maturato.",
      check=lambda: _esito("confronto"))
passo("ai-sportello", C5, "AI Lab 4 · Metti alla prova lo sportello HR", "ai.sportello",
      [("Menu", "AI Lab → 4. Sportello HR"), ("Stai scrivendo come", "scegli un dipendente, poi un altro"),
       ("Domande", "almeno 8 tue: ferie e permessi residui, ultimo netto, rimborso km, malattia…"),
       ("Prova di riservatezza", "chiedi le ferie di un collega: deve rifiutare"),
       ("Prova di inoltro", "una domanda a cui non sa rispondere: la passa all'ufficio paghe"), ("Pulsante", "Invia")],
      attesa="Nel riquadro in basso: stato «superata».", check=lambda: _esito("sportello"))
passo("ferie-nov", C5, "Leggi ferie e permessi residui al 30 novembre", "ferie_permessi.contatori",
      [("Menu", "Assenze → Ferie e permessi: maturato e residuo"), ("Situazione al", "30/11/2026"),
       ("Rossi", "ferie godute: anche i 2 giorni di novembre registrati dall'AI Lab"),
       ("Santini", "ha maturato 2/12 dell'anno: ottobre e novembre")], args={"al": "2026-11-30"})
passo("tfr-galli", C5, "Simula il TFR in caso di dimissioni di Galli (senza confermare)", "cessazioni.elenco",
      [("Menu", "Dipendenti → Cessazioni e TFR"), ("Dipendente", "Galli Sara"), ("Ultimo giorno", "31/12/2026"),
       ("Motivo", "Dimissioni del lavoratore"), ("Pulsante", "Calcola il prospetto del TFR"),
       ("Attenzione", "NON confermare la cessazione: è solo una simulazione")],
      nota="Il prospetto mostra il fondo anno per anno dal 2015, le rivalutazioni e la tassazione separata.")

# ------------------------------------------------------------------------------------------------ 6 · Dicembre e fine anno
passo("tredicesima", C6, "Tredicesima: genera, conferma e chiudi", "gruppi.run_new",
      [("Menu", "Libro paga → Gruppi buste paga → «Nuovo»"), ("Nome", "Tredicesima 2026"),
       ("Periodo", "01/12/2026 – 31/12/2026"), ("Struttura", "IT13 · CCNL Metalmeccanico Industria - tredicesima"),
       ("Poi", "Salva → Genera buste paga (9) → spunta tutte → Cambia stato → Conferma → Chiudi lotto")],
      attesa="Santini ha 3 ratei (ottobre-dicembre), Moretti 7, gli altri 12. IRPEF all'aliquota marginale.",
      check=lambda: _chiuso(_gruppo(*DIC, struct="IT13"), 9))
passo("dicembre", C6, "Buste di dicembre: genera, conferma e chiudi", "gruppi.run_new",
      [("Menu", "Libro paga → Gruppi buste paga → «Nuovo»"), ("Nome", "Dicembre 2026"),
       ("Periodo", "01/12/2026 – 31/12/2026"), ("Struttura", "vuota"),
       ("Poi", "Genera buste paga (9) → leggi il CONGUAGLIO di Moretti e Santini → Conferma tutte → Chiudi lotto")],
      attesa="Nelle buste di dicembre compare il conguaglio di fine anno (CONG_IRPEF, CONG_CUNEO).",
      check=lambda: _chiuso(_gruppo(*DIC), 9))
passo("contab-dic", C6, "Registra le paghe di dicembre in contabilità", "contabilita.prima_nota_paghe",
      [("Menu", "Libro paga → Contabilizzazione paghe"), ("Mese", "Dicembre 2026"), ("Pulsante", "Registra in contabilità")],
      check=lambda: _contab(2026, 12))
passo("cu", C6, "Leggi la Certificazione Unica di Santini", "cu.certificazione",
      [("Menu", "Libro paga → Certificazione Unica"), ("Anno", "2026"), ("Dipendente", "Santini Alessio"),
       ("Leggi", "redditi da ottobre, ritenute dopo il conguaglio, giorni di lavoro")])
passo("scadenzario", C6, "Controlla lo scadenzario del personale al 31 dicembre", "visite_mediche.scadenzario_hr",
      [("Menu", "Dipendenti → Scadenzario del personale"), ("Situazione al", "31/12/2026"),
       ("Santini", "visita preventiva e formazione generale in regola, con le loro scadenze"),
       ("Altri", "visite e corsi scaduti o in scadenza da programmare")], args={"al": "2026-12-31"})
passo("ai-regole", C6, "AI Lab 6 · Regole e rischi dell'AI sui dati dei lavoratori", "ai.regole",
      [("Menu", "AI Lab → 6. Regole e rischi"), ("Leggi", "la lezione: AI Act, GDPR, art. 4 dello Statuto, L. 132/2025"),
       ("Esercitazione", "10 domande → «Verifica» (almeno 8 giuste)")], check=lambda: _esito("regole"))
passo("consegna", C6, "Hai finito: avvisa il docente", "cruscotto.esercitazioni",
      [("Menu", "Academy → Esercitazioni"), ("Cosa", "segna come svolta l'esercitazione e scrivi una nota: quale anomalia "
                                                    "ti ha sorpreso e quale laboratorio useresti in un vero ufficio paghe?")])
