"""Scadenzario del personale: visite mediche (D.Lgs. 81/08), corsi di formazione da rinnovare, documenti.

Una scadenza è «scaduta» se la data è passata, «in scadenza» se cade entro il preavviso (parametro
SCADENZE_PREAVVISO_GG della pagina Tabelle, 60 giorni), altrimenti «in regola»."""
from datetime import date, timedelta

from .models import Corso, CorsoPartecipante, DocumentoDipendente, Employee, Parametro, VisitaMedica

TIPI_VISITA = [("preventiva", "Preventiva (prima di adibire alla mansione)"), ("periodica", "Periodica"),
               ("cambio_mansione", "Per cambio della mansione"),
               ("rientro", "Al rientro dopo un'assenza per malattia oltre 60 giorni"),
               ("su_richiesta", "Su richiesta del lavoratore"), ("cessazione", "Alla cessazione del rapporto")]
ESITI_VISITA = [("idoneo", "Idoneo"), ("idoneo_prescrizioni", "Idoneo con prescrizioni o limitazioni"),
                ("non_idoneo_temp", "Temporaneamente non idoneo"), ("non_idoneo", "Non idoneo")]
CATEGORIE_CORSO = [("sicurezza_generale", "Sicurezza - formazione generale"),
                   ("sicurezza_specifica", "Sicurezza - formazione specifica"),
                   ("aggiornamento", "Sicurezza - aggiornamento quinquennale"),
                   ("antincendio", "Addetto antincendio"), ("primo_soccorso", "Addetto primo soccorso"),
                   ("abilitazione", "Abilitazione attrezzature (carrelli, PLE, gru)"),
                   ("preposto", "Preposto / dirigente"), ("tecnico", "Tecnico / professionale")]
ESITI_CORSO = [("iscritto", "Iscritto"), ("superato", "Superato"), ("non_superato", "Non superato"),
               ("assente", "Assente")]
STATI_CORSO = [("programmato", "Programmato"), ("svolto", "Svolto"), ("annullato", "Annullato")]
TIPI_DOCUMENTO = [("contratto", "Contratto / lettera di assunzione firmata"),
                  ("identita", "Documento d'identità"), ("permesso", "Permesso di soggiorno"),
                  ("idoneita", "Giudizio di idoneità alla mansione"), ("attestato", "Attestato di formazione"),
                  ("patente", "Patente / abilitazione"), ("privacy", "Informativa privacy firmata"),
                  ("altro", "Altro")]

STATI = {"scaduta": ("Scaduta", "danger"), "in_scadenza": ("In scadenza", "warning"),
         "ok": ("In regola", "success"), "manca": ("Da fare", "secondary")}


def preavviso(ws_id):
    p = Parametro.query.filter_by(workspace_id=ws_id, codice="SCADENZE_PREAVVISO_GG").first()
    return int(p.valore) if p else 60


def stato_scadenza(scad, al, giorni):
    if scad is None:
        return "ok"
    if scad < al:
        return "scaduta"
    if scad <= al + timedelta(days=giorni):
        return "in_scadenza"
    return "ok"


def ultima_visita(employee):
    return (VisitaMedica.query.filter_by(employee_id=employee.id)
            .order_by(VisitaMedica.data.desc(), VisitaMedica.id.desc()).first())


def scadenzario(ws_id, al=None, solo_da_guardare=False):
    """Righe dello scadenzario per i dipendenti attivi, ordinate per data."""
    al = al or date.today()
    gg = preavviso(ws_id)
    righe = []
    attivi = Employee.query.filter_by(workspace_id=ws_id, active=True).order_by(Employee.last_name).all()
    for e in attivi:
        v = ultima_visita(e)
        if v is None:
            righe.append({"area": "Visita medica", "employee": e, "cosa": "Nessuna visita registrata",
                          "scadenza": None, "stato": "manca", "link": ("visite_mediche.elenco", {"employee_id": e.id})})
        elif v.scadenza:
            righe.append({"area": "Visita medica", "employee": e,
                          "cosa": f"Visita {dict(TIPI_VISITA).get(v.tipo, v.tipo).split(' (')[0].lower()} del "
                                  f"{v.data.strftime('%d/%m/%Y')} · {dict(ESITI_VISITA).get(v.esito, v.esito)}",
                          "scadenza": v.scadenza, "stato": stato_scadenza(v.scadenza, al, gg),
                          "link": ("visite_mediche.visita", {"vis_id": v.id})})
    # corsi: per dipendente e categoria vale l'ultimo superato
    ids = {e.id for e in attivi}
    ultimi = {}
    for p in (CorsoPartecipante.query.join(Corso).filter(Corso.workspace_id == ws_id,
                                                         CorsoPartecipante.esito == "superato")):
        if p.employee_id not in ids or not p.scadenza:
            continue
        k = (p.employee_id, p.corso.categoria)
        if k not in ultimi or p.corso.data_fine > ultimi[k].corso.data_fine:
            ultimi[k] = p
    for p in ultimi.values():
        righe.append({"area": "Formazione", "employee": p.employee, "cosa": p.corso.titolo, "scadenza": p.scadenza,
                      "stato": stato_scadenza(p.scadenza, al, gg), "link": ("formazione.corso", {"corso_id": p.corso_id})})
    for d in DocumentoDipendente.query.filter(DocumentoDipendente.workspace_id == ws_id,
                                              DocumentoDipendente.scadenza.isnot(None)):
        if d.employee_id in ids:
            righe.append({"area": "Documento", "employee": d.employee, "cosa": d.nome, "scadenza": d.scadenza,
                          "stato": stato_scadenza(d.scadenza, al, gg),
                          "link": ("documenti.elenco", {"employee_id": d.employee_id})})
    if solo_da_guardare:
        righe = [r for r in righe if r["stato"] != "ok"]
    ordine = {"scaduta": 0, "manca": 1, "in_scadenza": 2, "ok": 3}
    righe.sort(key=lambda r: (ordine[r["stato"]], r["scadenza"] or date.min, r["employee"].name))
    return righe
