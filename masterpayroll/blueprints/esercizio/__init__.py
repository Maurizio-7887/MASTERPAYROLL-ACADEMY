"""Blueprint «esercizio» — esercizio guidato con la finestra a destra: un'azione alla volta.

Ogni passo dice DOVE andare, COSA scrivere e CHE COSA deve succedere. I passi operativi si spuntano da soli
controllando i dati dell'ambiente dell'allievo; le letture si confermano con «Fatto».
Una cartella per attività: la finestra è in templates/esercizio/_pannello.html, inclusa da base.html.
"""
from datetime import date

from flask import abort, g, redirect, render_template, request, url_for
from flask_login import current_user

from ...models import (Cessazione, Contabilizzazione, Contract, Corso, CorsoPartecipante, Employee, EsercizioSpunta,
                       Leave, LeaveType, PayslipRun, VisitaMedica, db)
from ..comune import area

bp = area("esercizio")

CODICE = "ottobre-dicembre-2026"
TITOLO = "Paghe da ottobre a dicembre 2026, passo passo"


# ── aiuti per i controlli: si cercano i dati per dipendente (matricola) e periodo, non per nome del gruppo ──
_W = {"ws": None}   # ambiente che si sta controllando (anche quello di un allievo, dall'area docente)


def _q(model):
    return model.query.filter_by(workspace_id=_W["ws"].id)


def _emp(matr):
    return _q(Employee).filter_by(registration_number=matr).first()


def _assenza(matr, codice, d1, d2):
    e = _emp(matr)
    if not e:
        return False
    return (_q(Leave).join(LeaveType, Leave.holiday_status_id == LeaveType.id)
            .filter(Leave.employee_id == e.id, LeaveType.code == codice, Leave.state == "validate",
                    Leave.date_from == d1, Leave.date_to == d2).first() is not None)


def _gruppo(d1, d2, struct=None):
    for r in _q(PayslipRun).filter_by(date_start=d1, date_end=d2).order_by(PayslipRun.id):
        if (r.struct.code if r.struct else None) == struct:
            return r
    return None


def _busta(run, matr):
    if not run:
        return None
    return next((s for s in run.slip_ids if s.employee.registration_number == matr), None)


def _apporto(run, matr, codice, valore, riga=None):
    s = _busta(run, matr)
    if not s:
        return False
    ok = any(i.code == codice and abs((i.amount or 0) - valore) < 0.001 for i in s.input_line_ids)
    return ok and any(ln.code == (riga or codice) for ln in s.line_ids)


def _tutte(run, stato, n=None):
    if not run:
        return False
    slips = [s for s in run.slip_ids if not s.credit_note]
    return bool(slips) and (n is None or len(slips) >= n) and all(s.state == stato for s in slips)


OTT = (date(2026, 10, 1), date(2026, 10, 31))
NOV = (date(2026, 11, 1), date(2026, 11, 30))
DIC = (date(2026, 12, 1), date(2026, 12, 31))


def _visita(matr, d, esito, scad):
    e = _emp(matr)
    return bool(e) and _q(VisitaMedica).filter_by(employee_id=e.id, data=d, esito=esito, scadenza=scad).first() is not None


def _trasformazione(matr, dal, pt):
    e = _emp(matr)
    return bool(e) and _q(Contract).filter_by(employee_id=e.id, date_start=dal, part_time=pt, state="open").first() is not None


def _corso(matr, categoria, dal):
    e = _emp(matr)
    if not e:
        return False
    return (CorsoPartecipante.query.join(Corso).filter(Corso.workspace_id == _W["ws"].id, Corso.categoria == categoria,
                                                       Corso.data_inizio == dal, CorsoPartecipante.employee_id == e.id,
                                                       CorsoPartecipante.esito == "superato").first() is not None)


def _cess():
    e = _emp("0004")
    return _q(Cessazione).filter_by(employee_id=e.id).first() if e else None


def _contab(anno, mese):
    return _q(Contabilizzazione).filter_by(anno=anno, mese=mese).first() is not None


# ── i passi: (id, capitolo, titolo, endpoint, campi, risultato atteso, nota, controllo o None = lettura) ──
P = []


def passo(pid, cap, titolo, ep, campi, attesa="", nota="", check=None, args=None):
    P.append({"id": pid, "cap": cap, "titolo": titolo, "ep": ep, "args": args or {}, "campi": campi,
              "attesa": attesa, "nota": nota, "check": check})


C1, C2, C3, C4, C5, C6, C7 = ("1 · Si comincia", "2 · Le assenze di ottobre", "3 · Le buste di ottobre",
                              "4 · Dopo le paghe di ottobre", "5 · Novembre: una trasformazione e una cessazione",
                              "6 · Dicembre: tredicesima e conguaglio", "7 · Fine anno")
passo("pulito", C1, "Parti da un ambiente pulito", "cruscotto.dashboard",
      [("Se hai già lavorato", "in fondo al Cruscotto scrivi RIPRISTINA e premi «Ripristina l'ambiente»"),
       ("Dopo il ripristino", "c'è solo il gruppo di settembre 2026, già confermato")],
      nota="Il ripristino cancella solo il TUO ambiente. L'esercizio si può rifare da capo quante volte vuoi.")
passo("leggi-settembre", C1, "Leggi una busta di settembre", "buste_paga.payslips",
      [("Apri", "la busta di Rossi Laura di settembre 2026"), ("Tab «Calcolo stipendio»", "segui le righe dall'alto: paga base, lordo, INPS, IRPEF, netto")],
      nota="Le trattenute sono NEGATIVE, come in Odoo: il netto è la somma delle righe.")
passo("malattia", C2, "Moretti Paolo è in malattia dal 12 al 30 ottobre", "assenze.leave",
      [("Dipendente", "Moretti Paolo"), ("Tipo di assenza", "Malattia"), ("Dal", "12/10/2026"), ("Al", "30/10/2026"),
       ("Approva subito", "lascia la spunta"), ("Pulsante", "Salva")],
      attesa="Un'assenza approvata di 19 giorni di calendario: 3 di carenza (paga l'azienda), 16 indennizzati dall'INPS al 50%.",
      check=lambda: _assenza("0008", "MAL", date(2026, 10, 12), date(2026, 10, 30)))
passo("rol", C2, "Verdi Luca prende 4 ore di permesso il 16 ottobre", "assenze.leave",
      [("Dipendente", "Verdi Luca"), ("Tipo di assenza", "Permessi retribuiti (ROL)"), ("Dal / Al", "16/10/2026"),
       ("Ore (solo una parte del giorno)", "spunta, dalle 13 alle 17"), ("Approva subito", "sì"), ("Pulsante", "Salva")],
      attesa="4 ore di ROL: la paga non cambia, il contatore dei permessi scende di 4 ore.",
      check=lambda: _assenza("0003", "ROL", date(2026, 10, 16), date(2026, 10, 16)))
passo("ferie", C2, "Bianchi Marco va in ferie il 29 e 30 ottobre", "assenze.leave",
      [("Dipendente", "Bianchi Marco"), ("Tipo di assenza", "Ferie"), ("Dal", "29/10/2026"), ("Al", "30/10/2026"),
       ("Approva subito", "sì"), ("Pulsante", "Salva")],
      attesa="2 giorni di ferie (16 ore). Rossi Laura è già in ferie dal 19 al 23 ottobre: c'era nei dati iniziali.",
      check=lambda: _assenza("0001", "FERIE", date(2026, 10, 29), date(2026, 10, 30)))
passo("gruppo-ott", C3, "Crea il gruppo delle buste di ottobre", "gruppi.run_new",
      [("Nome", "Ottobre 2026"), ("Dal", "01/10/2026"), ("Al", "31/10/2026"), ("Struttura", "lasciala vuota (quella del contratto)"),
       ("Pulsante", "Salva")], attesa="Un gruppo in bozza, ancora senza buste.",
      check=lambda: _gruppo(*OTT) is not None)
passo("genera-ott", C3, "Genera le buste di tutti i dipendenti", "gruppi.runs",
      [("Apri", "il gruppo Ottobre 2026"), ("Pulsante", "Genera buste paga"), ("Dipendenti", "tutti e 8 spuntati"), ("Conferma", "Genera")],
      attesa="8 buste calcolate (stato «In attesa»): giorni lavorati, festività e assenze sono già dentro.",
      check=lambda: len(getattr(_gruppo(*OTT), "slip_ids", []) or []) >= 8)
passo("str-ott", C3, "Bianchi Marco ha fatto 10 ore di straordinario", "gruppi.runs",
      [("Apri", "gruppo Ottobre 2026 → busta di Bianchi Marco"), ("Tab «Giorni lavorati e apporti»", "accanto a STR25 scrivi 10"),
       ("Pulsante", "Calcola scheda")], attesa="Nuova riga STR25: 10 ore × 125% × paga oraria. Salgono lordo, INPS e IRPEF.",
      check=lambda: _apporto(_gruppo(*OTT), "0001", "STR25", 10))
passo("trasf-ott", C3, "Esposito Giuseppe è stato 3 giorni in trasferta", "gruppi.runs",
      [("Busta", "Esposito Giuseppe di ottobre"), ("Apporto TRASF", "3"), ("Pulsante", "Calcola scheda")],
      attesa="3 × 46,48 = 139,44 € di trasferta ESENTE: entra nel netto ma non nei contributi né nell'IRPEF.",
      check=lambda: _apporto(_gruppo(*OTT), "0004", "TRASF", 3))
passo("premio-ott", C3, "Conti Davide riceve un premio di 300 €", "gruppi.runs",
      [("Busta", "Conti Davide di ottobre"), ("Apporto PREMIO", "300"), ("Pulsante", "Calcola scheda")],
      attesa="Riga PREMIO 300 €: è retribuzione, quindi paga contributi e IRPEF.",
      check=lambda: _apporto(_gruppo(*OTT), "0006", "PREMIO", 300))
passo("leggi-malattia", C3, "Leggi la busta di Moretti: la malattia", "gruppi.runs",
      [("Busta", "Moretti Paolo di ottobre, tab «Calcolo stipendio»"),
       ("MAL_RID", "−520,00: per i 16 giorni pagati dall'INPS l'azienda non deve lo stipendio"),
       ("MAL_INPS", "+520,00: indennità INPS (16 × 1.950/30 × 50%), anticipata dall'azienda"),
       ("Effetto", "il lordo contributivo scende a 1.430: sull'indennità non si pagano contributi, ma l'IRPEF sì")],
      nota="I primi 3 giorni (carenza) e l'integrazione al 100% sono a carico dell'azienda per il CCNL metalmeccanico.")
passo("conferma-ott", C3, "Conferma tutte le buste di ottobre", "gruppi.runs",
      [("Nel gruppo", "spunta tutte le buste"), ("Azione", "Cambia stato → Conferma"), ("Pulsante", "Esegui sui selezionati")],
      attesa="8 buste «Completata»: da ora entrano in F24, LUL e contabilità.", check=lambda: _tutte(_gruppo(*OTT), "done", 8))
passo("chiudi-ott", C3, "Chiudi il gruppo di ottobre", "gruppi.runs", [("Pulsante", "Chiudi lotto")],
      check=lambda: getattr(_gruppo(*OTT), "state", "") == "close")
passo("f24-ott", C4, "Prepara l'F24 di ottobre (scadenza 16 novembre)", "f24.f24",
      [("Mese", "Ottobre 2026"), ("Erario", "1001 IRPEF, 3802 e 3848 addizionali; a credito trattamento integrativo e cuneo"),
       ("INPS", "contributi dipendente + azienda MENO l'indennità di malattia anticipata (520 €)")],
      nota="L'indennità INPS pagata a Moretti non è un costo: l'azienda la recupera riducendo i contributi da versare.")
passo("contab-ott", C4, "Registra le paghe di ottobre in contabilità", "contabilita.prima_nota_paghe",
      [("Mese", "Ottobre 2026"), ("Controlla", "Dare = Avere"), ("Pulsante", "Registra in contabilità")],
      attesa="Costi del personale in Dare; debiti verso dipendenti, INPS, Erario, INAIL e fondo TFR in Avere.",
      check=lambda: _contab(2026, 10))
passo("lul-ott", C4, "Controlla il Libro unico di ottobre", "lul.libro",
      [("Mese", "Ottobre 2026"), ("Moretti", "MA dal 12 al 30"), ("Rossi", "FE dal 19 al 23"), ("Verdi", "il 16: L4+PR (4 ore lavorate e 4 di permesso)")],
      nota="Il LUL ha due sezioni: presenze (giorno per giorno) e paga (le voci della busta).")
passo("ferie-ott", C4, "Leggi i contatori di ferie e permessi al 31 ottobre", "ferie_permessi.contatori",
      [("Situazione al", "31/10/2026"), ("Bianchi", "ferie godute 16 ore"), ("Verdi", "permessi goduti 4 ore")],
      nota="Si maturano 160 ore di ferie e 104 di permessi l'anno, in dodicesimi.")
passo("visita-bianchi", C4, "Bianchi Marco fa la visita medica periodica il 20 ottobre", "visite_mediche.elenco",
      [("Dipendente", "Bianchi Marco"), ("Data della visita", "20/10/2026"), ("Tipo", "Periodica"), ("Esito", "Idoneo"),
       ("Prossima visita entro", "20/10/2027"), ("Pulsante", "Registra")],
      attesa="La visita del 2025 scadeva proprio il 20/10/2026: nello scadenzario Bianchi torna «in regola».",
      nota="Chi lavora al taglio laser è esposto a rumore: il medico competente fissa la visita ogni anno (D.Lgs. 81/08 art. 41).",
      check=lambda: _visita("0001", date(2026, 10, 20), "idoneo", date(2027, 10, 20)))
passo("trasf-ferri", C5, "Ferri Anna passa al tempo pieno dal 16 novembre", "variazioni.elenco",
      [("Dove", "Dipendenti → Variazioni di orario e part-time"), ("Dipendente", "Ferri Anna"), ("Dal giorno", "16/11/2026"),
       ("Nuovo orario", "Tempo pieno 40 ore (lun-ven 8-12 / 13-17)"), ("% part-time", "100"),
       ("Motivo", "trasformazione a tempo pieno su richiesta della lavoratrice"), ("Pulsante", "Registra la variazione")],
      attesa="Il contratto part-time 50% si chiude il 15/11; dal 16/11 c'è una nuova versione al 100% con il nuovo orario.",
      nota="La trasformazione si fa PRIMA di generare le buste del mese: la busta legge versioni e orari dal calendario.",
      check=lambda: _trasformazione("0005", date(2026, 11, 16), 100.0))
passo("gruppo-nov", C5, "Crea il gruppo di novembre e genera le buste", "gruppi.run_new",
      [("Nome", "Novembre 2026"), ("Periodo", "01/11/2026 – 30/11/2026"), ("Poi", "Genera buste paga per tutti e 8")],
      attesa="8 buste calcolate.", check=lambda: len(getattr(_gruppo(*NOV), "slip_ids", []) or []) >= 8)
passo("leggi-ferri", C5, "Leggi la busta di novembre di Ferri: due versioni nello stesso mese", "gruppi.runs",
      [("Busta", "Ferri Anna di novembre"),
       ("Tab «Giorni lavorati e apporti»", "due righe WORK100: una per il part-time (1-15) e una per il tempo pieno (16-30)"),
       ("BASIC", "2.110 × 75% = 1.582,50: 15 giorni al 50% e 15 al 100% su un mese di 30"),
       ("Effetto", "il reddito annuo presunto passa a 24.909 €: niente più trattamento integrativo né somma esente del "
                   "cuneo; scatta l'ulteriore detrazione del cuneo (83,33 € al mese)")],
      nota="Le ferie e i permessi di novembre maturano al 75%; da dicembre al 100%.")
passo("chiudi-nov", C5, "Conferma le buste di novembre e chiudi il gruppo", "gruppi.runs",
      [("Azione", "Cambia stato → Conferma su tutte"), ("Poi", "Chiudi lotto")],
      check=lambda: _tutte(_gruppo(*NOV), "done", 8) and getattr(_gruppo(*NOV), "state", "") == "close")
passo("corso-moretti", C5, "Moretti frequenta il corso per i carrelli elevatori il 9 e 10 novembre", "formazione.corsi",
      [("Titolo", "Abilitazione all'uso dei carrelli elevatori (12 ore)"), ("Categoria", "Abilitazione attrezzature"),
       ("Ente", "Ente bilaterale metalmeccanici Umbria"), ("Dal / Al", "09/11/2026 – 10/11/2026"), ("Ore", "12"),
       ("Costo totale €", "240"), ("Validità", "5 anni"), ("Stato", "Svolto"),
       ("Poi", "nella scheda del corso aggiungi Moretti Paolo con esito «Superato»")],
      attesa="Nella formazione per dipendente Moretti ha il corso con scadenza 10/11/2031.",
      nota="Le ore di formazione obbligatoria sono orario di lavoro: in busta non cambia nulla, il costo del corso è "
           "un costo dell'azienda (non va nelle paghe).",
      check=lambda: _corso("0008", "abilitazione", date(2026, 11, 9)))
passo("cessazione", C5, "Esposito Giuseppe si dimette: ultimo giorno 30 novembre", "cessazioni.elenco",
      [("Dipendente", "Esposito Giuseppe"), ("Ultimo giorno", "30/11/2026"), ("Motivo", "Dimissioni del lavoratore"),
       ("Prima", "Calcola il prospetto del TFR e leggilo"), ("Poi", "Conferma la cessazione e crea la busta di liquidazione")],
      attesa="Fondo TFR dal 2009, rivalutazioni, tassazione separata con l'aliquota media. Il contratto si chiude e Esposito va in archivio.",
      check=lambda: _cess() is not None)
passo("liquidazione", C5, "Controlla e conferma la busta di liquidazione", "cessazioni.elenco",
      [("Apri", "la cessazione → Busta di liquidazione"),
       ("Righe", "FERIE_NG ferie e permessi non goduti · RATEI13 · IRPEF_CESS conguaglio · TFR_LIQ · RIT_TFR (1012) · SOST_TFR (1713)"),
       ("Pulsante", "Conferma")], attesa="Busta completata: il TFR netto è nel netto in busta.",
      check=lambda: bool(_cess() and _cess().payslip and _cess().payslip.state == "done"))
passo("f24-nov", C5, "Guarda l'F24 di novembre: i codici del TFR", "f24.f24",
      [("Mese", "Novembre 2026"), ("Nuovi codici", "1012 ritenute sul TFR, 1713 imposta sostitutiva sulla rivalutazione")])
passo("gruppo-13", C6, "Crea il gruppo della tredicesima", "gruppi.run_new",
      [("Nome", "Tredicesima 2026"), ("Periodo", "01/12/2026 – 31/12/2026"),
       ("Struttura", "IT13 · CCNL Metalmeccanico Industria - tredicesima"), ("Pulsante", "Salva")],
      attesa="Il gruppo usa la struttura IT13 per tutte le sue buste.", check=lambda: _gruppo(*DIC, struct="IT13") is not None)
passo("conferma-13", C6, "Genera, conferma e chiudi la tredicesima", "gruppi.runs",
      [("Genera buste paga", "i 7 dipendenti in servizio (Esposito è in archivio: ha già avuto i ratei)"),
       ("Poi", "Cambia stato → Conferma su tutte, e Chiudi lotto")],
      attesa="Moretti ha 7 ratei (da giugno), gli altri 12. Per Ferri ogni rateo vale la paga del suo mese: 10 al 50%, "
             "novembre al 75%, dicembre al 100%. L'IRPEF è all'aliquota marginale, senza detrazioni.",
      check=lambda: _tutte(_gruppo(*DIC, struct="IT13"), "done", 7) and getattr(_gruppo(*DIC, struct="IT13"), "state", "") == "close")
passo("gruppo-dic", C6, "Crea il gruppo di dicembre e genera le buste", "gruppi.run_new",
      [("Nome", "Dicembre 2026"), ("Periodo", "01/12/2026 – 31/12/2026"), ("Struttura", "vuota"), ("Poi", "Genera buste paga per i 7 dipendenti")],
      attesa="Nelle buste di dicembre compare il CONGUAGLIO di fine anno.", check=lambda: len(getattr(_gruppo(*DIC), "slip_ids", []) or []) >= 7)
passo("leggi-conguaglio", C6, "Leggi il conguaglio di Moretti", "gruppi.runs",
      [("Busta", "Moretti Paolo di dicembre"),
       ("CONG_IRPEF", "IRPEF vera dell'anno meno le ritenute fatte: è negativo, Moretti ha lavorato solo da giugno"),
       ("CONG_CUNEO", "positivo: sul reddito vero dell'anno gli spetta la somma esente del cuneo fiscale")],
      nota="Il conguaglio rifà i conti sull'anno intero: a dicembre si trattiene o si rimborsa la differenza.")
passo("chiudi-dic", C6, "Conferma le buste di dicembre e chiudi il gruppo", "gruppi.runs",
      [("Azione", "Cambia stato → Conferma su tutte"), ("Poi", "Chiudi lotto")],
      check=lambda: _tutte(_gruppo(*DIC), "done", 7) and getattr(_gruppo(*DIC), "state", "") == "close")
passo("contab-dic", C7, "Registra le paghe di dicembre in contabilità", "contabilita.prima_nota_paghe",
      [("Mese", "Dicembre 2026"), ("Pulsante", "Registra in contabilità")],
      attesa="La scrittura comprende tredicesima, conguagli e cuneo.", check=lambda: _contab(2026, 12))
passo("cu", C7, "Leggi la Certificazione Unica 2026", "cu.certificazione",
      [("Anno", "2026"), ("Moretti", "redditi da giugno, ritenute dopo il conguaglio"), ("Esposito", "anche il TFR con le sue ritenute")],
      nota="La CU va all'Agenzia delle Entrate entro il 16 marzo e si consegna al dipendente.")
passo("scadenzario", C7, "Controlla lo scadenzario del personale al 31 dicembre", "visite_mediche.scadenzario_hr",
      [("Situazione al", "31/12/2026"), ("Galli", "visita periodica scaduta il 15/09/2026 e primo soccorso scaduto"),
       ("Rossi", "antincendio scaduto il 20/11/2026: va rifatto l'aggiornamento"),
       ("Ferri", "nessuna visita: ora lavora 40 ore al videoterminale, serve la visita"),
       ("Esposito", "non c'è più: è in archivio")],
      nota="Le scadenze di visite e corsi non toccano la busta ma sono obblighi del datore di lavoro: chi fa le paghe spesso "
           "tiene anche questo scadenzario.", args={"al": "2026-12-31"})
passo("consegna", C7, "Hai finito: avvisa il docente", "cruscotto.esercitazioni",
      [("Dove", "Academy → Esercitazioni"), ("Cosa", "segna come svolta l'esercitazione e scrivi una nota: cosa ti ha sorpreso del conguaglio?")])


def stato_passi(ws):
    """Stato di ogni passo per l'ambiente: 'auto' fatto dai dati, 'mano' spuntato, '' da fare."""
    _W["ws"] = ws
    spunte = {s.passo for s in EsercizioSpunta.query.filter_by(workspace_id=ws.id, esercizio=CODICE)}
    out = []
    for p in P:
        if p["check"] is not None:
            try:
                fatto = bool(p["check"]())
            except Exception:  # un dato strano non deve rompere la pagina
                fatto = False
            out.append("auto" if fatto else ("mano" if p["id"] in spunte else ""))
        else:
            out.append("mano" if p["id"] in spunte else "")
    return out


@bp.app_context_processor
def _finestra():
    if not current_user.is_authenticated or getattr(g, "ws", None) is None or request.blueprint in ("accesso", "docente"):
        return {}
    stati = stato_passi(g.ws)
    corrente = next((i for i, s in enumerate(stati) if not s), len(P) - 1)
    passi = []
    for p, s in zip(P, stati):
        try:
            href = url_for(p["ep"], **p["args"])
        except Exception:
            href = "#"
        passi.append(dict(p, stato=s, href=href, check=p["check"] is not None, qui=request.endpoint == p["ep"]))
    return {"guida": {"codice": CODICE, "titolo": TITOLO, "passi": passi, "corrente": corrente,
                      "fatti": sum(1 for s in stati if s), "totale": len(P)}}


@bp.route("/esercizio")
def panoramica():
    return render_template("esercizio/panoramica.html")


@bp.route("/esercizio/spunta", methods=["POST"])
def spunta():
    if g.ws_altrui:
        abort(403)
    pid = request.form.get("passo", "")
    if pid not in {p["id"] for p in P}:
        abort(404)
    rec = EsercizioSpunta.query.filter_by(workspace_id=g.ws.id, esercizio=CODICE, passo=pid).first()
    if request.form.get("azione") == "annulla":
        if rec:
            db.session.delete(rec)
    elif not rec:
        db.session.add(EsercizioSpunta(workspace_id=g.ws.id, esercizio=CODICE, passo=pid))
    db.session.commit()
    return redirect(request.form.get("torna") or request.referrer or url_for("cruscotto.dashboard"))


def progresso(ws):
    """Per l'area docente: passi fatti su totali."""
    stati = stato_passi(ws)
    return sum(1 for s in stati if s), len(P)


__all__ = ["bp", "P", "stato_passi", "progresso"]
