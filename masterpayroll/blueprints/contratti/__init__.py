"""Blueprint «contratti» — Contratti di lavoro (hr.version).

Una cartella per attività: le pagine HTML sono in templates/contratti/."""
from datetime import date
from flask import flash, g, redirect, render_template, request, url_for
from ... import payroll
from ...models import (CONTRACT_STATES, Contract, Employee, Livello, PayrollStructure, Payslip, ResourceCalendar, db)
from ..comune import (author, f_bool, f_date, f_float, f_id, f_int, f_str, f_text, handle_user_error,
                     messages_for, post_note, ws_get, ws_query)

from ..comune import area

bp = area("contratti")

QUALIFICHE = ["operaio", "impiegato", "apprendista", "quadro"]

CONTRACT_TYPES = ["indeterminato", "determinato", "apprendistato"]

def _calendars():
    return ws_query(ResourceCalendar).order_by(ResourceCalendar.name).all()


@bp.route("/contracts")
def contracts():
    q = ws_query(Contract)
    stato = request.args.get("state")
    if stato:
        q = q.filter(Contract.state == stato)
    rows = q.order_by(Contract.date_start.desc()).all()
    return render_template("contratti/contract_list.html", rows=rows, stato=stato, states=CONTRACT_STATES)


@bp.route("/contracts/new", methods=["GET", "POST"])
@bp.route("/contracts/<int:con_id>", methods=["GET", "POST"])
@handle_user_error
def contract(con_id=None):
    c = ws_get(Contract, con_id) if con_id else None
    if request.method == "POST":
        action = request.form.get("action", "save")
        if c and action == "note":
            post_note("hr.version", c.id)
            return redirect(url_for("contratti.contract", con_id=c.id) + "#chatter")
        if c and action in ("open", "close", "cancel", "draft"):
            old = c.state
            if action == "open":
                others = [x for x in c.employee.contract_ids if x.id != c.id and x.state == "open"
                          and x.is_overlapping_period(c.date_start, c.date_end or date(9999, 12, 31))]
                if others:
                    raise payroll.UserError("Il dipendente ha già un contratto in corso nello stesso periodo: "
                                            "chiudilo prima (o imposta la data di fine).")
            c.state = action
            labels = dict(CONTRACT_STATES)
            payroll.log_message(g.ws.id, "hr.version", c.id, tracking=[f"Stato: {labels[old]} → {labels[action]}"],
                                author=author())
            db.session.commit()
            return redirect(url_for("contratti.contract", con_id=c.id))
        if c and action == "delete":
            if Payslip.query.filter_by(contract_id=c.id).first():
                raise payroll.UserError("Il contratto è usato in buste paga: annullalo invece di eliminarlo.")
            emp_id = c.employee_id
            db.session.delete(c)
            db.session.commit()
            return redirect(url_for("dipendenti.employee", emp_id=emp_id))
        d1 = f_date("date_start")
        if not d1:
            raise payroll.UserError("La data di inizio è obbligatoria.")
        new = c is None
        if new:
            emp = ws_get(Employee, f_id("employee_id"))
            c = Contract(workspace_id=g.ws.id, employee=emp, state="draft", date_start=d1)
            db.session.add(c)
        d2 = f_date("date_end")
        if d2 and d2 < d1:
            raise payroll.UserError("La data di fine deve essere successiva alla data di inizio.")
        c.date_start, c.date_end, c.trial_date_end = d1, d2, f_date("trial_date_end")
        c.contract_type = f_str("contract_type", "indeterminato")
        c.job_title, c.department = f_str("job_title"), f_str("department")
        lid = f_id("livello_id")
        c.livello = ws_get(Livello, lid) if lid else None
        if f_bool("usa_tabella") and c.livello:
            c.wage, c.scatto_importo = c.livello.minimo, c.livello.scatto_importo
        else:
            c.wage, c.scatto_importo = f_float("wage"), f_float("scatto_importo")
        c.superminimo, c.scatti_n = f_float("superminimo"), f_int("scatti_n")
        c.part_time = f_float("part_time", 100) or 100
        c.mensilita = f_float("mensilita", 13) or 13
        c.divisore_orario = f_float("divisore_orario", 173) or 173
        c.add_reg_rata, c.add_com_rata = f_float("add_reg_rata"), f_float("add_com_rata")
        sid = f_id("struct_id")
        c.struct = ws_get(PayrollStructure, sid) if sid else None
        c.schedule_pay = f_str("schedule_pay", "monthly")
        cid = f_id("resource_calendar_id")
        c.resource_calendar = ws_get(ResourceCalendar, cid) if cid else None
        c.ccnl, c.notes = f_str("ccnl"), f_text("notes")
        c.name = f_str("name") or f"{c.employee.name} - {c.contract_type} {c.livello.codice if c.livello else ''}"
        db.session.flush()
        if new:
            payroll.log_message(g.ws.id, "hr.version", c.id, body="Contratto creato", author=author())
        db.session.commit()
        flash("Contratto salvato." + (" Premi 'In corso' per attivarlo." if c.state == "draft" else ""), "success")
        return redirect(url_for("contratti.contract", con_id=c.id))
    emp = c.employee if c else (ws_get(Employee, request.args.get("employee_id", type=int))
                                if request.args.get("employee_id") else None)
    return render_template("contratti/contract_form.html", c=c, emp=emp, employees=ws_query(Employee).order_by(Employee.last_name).all(),
        livelli=ws_query(Livello).order_by(Livello.codice).all(), structures=ws_query(PayrollStructure).all(),
        calendars=_calendars(), types=CONTRACT_TYPES, states=CONTRACT_STATES,
        messages=messages_for("hr.version", c.id) if c else [])
