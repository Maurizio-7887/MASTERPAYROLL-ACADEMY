"""Variazioni di orario e trasformazioni del contratto (OCA hr_employee_calendar_planning + hr.version di Odoo 19).

* Solo l'orario cambia (es. turni diversi, stessa percentuale): si aggiunge una riga allo storico degli orari.
* Cambia la percentuale di part-time (trasformazione part-time ↔ tempo pieno): il contratto in corso si chiude il
  giorno prima e nasce una NUOVA VERSIONE dal giorno della variazione con la nuova percentuale e il nuovo orario.
  Nel mese della variazione la busta vede due righe di giorni lavorati (una per versione) e la paga del mese è
  pesata sui giorni (payroll.part_time_mese); ferie, permessi e ratei di tredicesima maturano mese per mese.
"""
from datetime import timedelta

from . import payroll
from .models import Contract, EmployeeCalendar, Payslip, db


def storico(employee):
    return (EmployeeCalendar.query.filter_by(employee_id=employee.id)
            .order_by(EmployeeCalendar.date_start.is_(None).desc(), EmployeeCalendar.date_start).all())


def contratto_al(employee, giorno):
    for c in sorted(employee.contract_ids, key=lambda c: c.date_start, reverse=True):
        if c.state == "open" and c.date_start <= giorno and (c.date_end is None or c.date_end >= giorno):
            return c
    return None


def _inizio_rapporto(employee):
    return min((c.date_start for c in employee.contract_ids if c.state in ("open", "close")), default=None)


def assicura_storico(employee, ws_id):
    """Prima riga dello storico: l'orario attuale dall'inizio del rapporto (se lo storico è vuoto)."""
    if EmployeeCalendar.query.filter_by(employee_id=employee.id).first():
        return
    cal = employee.resource_calendar or (employee.contract_id.resource_calendar if employee.contract_id else None)
    if cal:
        db.session.add(EmployeeCalendar(workspace_id=ws_id, employee=employee, calendar=cal,
                                        date_start=_inizio_rapporto(employee), motivo="Orario iniziale"))
        db.session.flush()


def varia(employee, dal, calendar, part_time, motivo, ws, author=""):
    """Registra la variazione dal giorno ``dal``. Restituisce la nuova versione del contratto (o None se cambia
    solo l'orario)."""
    if not dal or not calendar:
        raise payroll.UserError("Indica la data della variazione e il nuovo orario di lavoro.")
    c = contratto_al(employee, dal)
    if c is None:
        raise payroll.UserError(f"{employee.name} non ha un contratto in corso al {dal.strftime('%d/%m/%Y')}.")
    confermate = Payslip.query.filter(Payslip.workspace_id == ws.id, Payslip.employee_id == employee.id,
                                      Payslip.state == "done", Payslip.date_to >= dal).first()
    if confermate:
        raise payroll.UserError(f"La busta {confermate.number or confermate.name} copre giorni dopo la variazione ed è "
                                "già confermata: la variazione va registrata prima di confermare le buste del mese.")
    part_time = float(part_time or c.part_time or 100)
    if not 0 < part_time <= 100:
        raise payroll.UserError("La percentuale di part-time va da 1 a 100.")
    if dal <= c.date_start and part_time != (c.part_time or 100):
        raise payroll.UserError("La trasformazione deve cominciare dopo l'inizio del contratto in corso.")
    assicura_storico(employee, ws.id)
    # storico orari: si chiude la riga in vigore e se ne apre una nuova
    for ec in storico(employee):
        if (ec.date_start is None or ec.date_start < dal) and (ec.date_end is None or ec.date_end >= dal):
            ec.date_end = dal - timedelta(days=1)
        elif ec.date_start is not None and ec.date_start >= dal:
            db.session.delete(ec)  # una variazione successiva già registrata viene sostituita
    db.session.add(EmployeeCalendar(workspace_id=ws.id, employee=employee, calendar=calendar, date_start=dal,
                                    motivo=motivo or "Variazione di orario"))
    employee.resource_calendar = calendar
    nuova = None
    if part_time != (c.part_time or 100):
        etichetta = "tempo pieno" if part_time >= 100 else f"part-time {part_time:g}%"
        nuova = Contract(
            workspace_id=ws.id, employee=employee, state="open", contract_type=c.contract_type, job_title=c.job_title,
            department=c.department, date_start=dal, date_end=c.date_end, trial_date_end=None,
            resource_calendar=calendar, wage=c.wage, struct=c.struct, schedule_pay=c.schedule_pay, notes=motivo or "",
            ccnl=c.ccnl, livello=c.livello, superminimo=c.superminimo, scatti_n=c.scatti_n,
            scatto_importo=c.scatto_importo, part_time=part_time, mensilita=c.mensilita,
            divisore_orario=c.divisore_orario, add_reg_rata=c.add_reg_rata, add_com_rata=c.add_com_rata,
            name=f"{employee.name} - {c.contract_type} {c.livello.codice if c.livello else ''} - {etichetta}".strip())
        db.session.add(nuova)
        c.date_end = dal - timedelta(days=1)
        c.state = "close"
        db.session.flush()
        payroll.log_message(ws.id, "hr.version", c.id, author=author, tracking=[
            f"Data di fine: → {c.date_end.strftime('%d/%m/%Y')}", "Stato: In corso → Scaduto"],
            body=f"Trasformazione: dal {dal.strftime('%d/%m/%Y')} vale la nuova versione «{nuova.name}».")
        payroll.log_message(ws.id, "hr.version", nuova.id, author=author,
                            body=f"Nuova versione del contratto dal {dal.strftime('%d/%m/%Y')}: {etichetta}, "
                                 f"orario «{calendar.name}». {motivo or ''}".strip())
    payroll.log_message(ws.id, "hr.employee", employee.id, author=author,
                        body=f"Variazione di orario dal {dal.strftime('%d/%m/%Y')}: «{calendar.name}»"
                             + (f", part-time {part_time:g}%" if nuova else "") + ".")
    db.session.flush()
    # buste non confermate che coprono la variazione: si aggiornano contratto, giorni lavorati e calcolo
    aperte = Payslip.query.filter(Payslip.workspace_id == ws.id, Payslip.employee_id == employee.id,
                                  Payslip.state.in_(("draft", "verify")), Payslip.date_to >= dal).all()
    for s in aperte:
        if nuova is not None and s.contract_id == c.id:
            s.contract_id = nuova.id
            for i in s.input_line_ids:
                i.contract_id = nuova.id
        db.session.flush()
        db.session.refresh(s)
        payroll.onchange_dates(s)
        try:
            payroll.compute_sheet(s, author)
        except payroll.UserError:
            pass
    db.session.commit()
    return nuova, len(aperte)
