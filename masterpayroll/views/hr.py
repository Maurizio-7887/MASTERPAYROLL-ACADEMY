"""Dipendenti (hr.employee), contratti (hr.version), orari (resource.calendar), assenze (hr.leave)."""
from datetime import date

from flask import flash, g, redirect, render_template, request, url_for

from .. import payroll
from ..hr_service import WEEKDAYS, leave_duration
from ..models import (CONTRACT_STATES, Contract, Employee, Familiare, Leave, LeaveType, Livello, PayrollStructure,
                      Payslip, ResourceCalendar, ResourceCalendarAttendance, ResourceCalendarLeave, db)
from .common import (author, bp, f_bool, f_date, f_float, f_id, f_int, f_str, f_text, handle_user_error,
                     messages_for, post_note, ws_get, ws_query)

QUALIFICHE = ["operaio", "impiegato", "apprendista", "quadro"]
CONTRACT_TYPES = ["indeterminato", "determinato", "apprendistato"]


def _calendars():
    return ws_query(ResourceCalendar).order_by(ResourceCalendar.name).all()


# ===========================================================================
# Dipendenti
# ===========================================================================
@bp.route("/employees")
def employees():
    q = ws_query(Employee)
    if request.args.get("archiviati"):
        q = q.filter(Employee.active.is_(False))
    else:
        q = q.filter(Employee.active.is_(True))
    rows = q.order_by(Employee.registration_number).all()
    s = (request.args.get("q") or "").strip().lower()
    if s:
        rows = [e for e in rows if s in e.name.lower() or s in (e.job_title or "").lower()
                or s in (e.department or "").lower()]
    return render_template("employee_list.html", rows=rows, q=s, archiviati=request.args.get("archiviati"))


def _save_employee(e):
    e.registration_number = f_str("registration_number")
    e.last_name, e.first_name = f_str("last_name"), f_str("first_name")
    e.job_title, e.department = f_str("job_title"), f_str("department")
    e.qualifica = f_str("qualifica", "operaio")
    e.work_email, e.work_phone = f_str("work_email"), f_str("work_phone")
    e.private_street, e.private_city, e.private_email = f_str("private_street"), f_str("private_city"), \
        f_str("private_email")
    e.identification_id = f_str("identification_id").upper()
    e.birthday, e.place_of_birth = f_date("birthday"), f_str("place_of_birth")
    e.bank_account = f_str("bank_account").replace(" ", "").upper()
    cid = f_id("resource_calendar_id")
    e.resource_calendar = ws_get(ResourceCalendar, cid) if cid else None
    e.active = f_bool("active")
    # familiari a carico
    for fam in list(e.familiari):
        if f_bool(f"fam_del_{fam.id}"):
            e.familiari.remove(fam)
            continue
        if f"fam_nome_{fam.id}" in request.form:
            fam.relazione = f_str(f"fam_rel_{fam.id}", fam.relazione)
            fam.nome = f_str(f"fam_nome_{fam.id}")
            fam.codice_fiscale = f_str(f"fam_cf_{fam.id}").upper()
            fam.data_nascita = f_date(f"fam_nascita_{fam.id}")
            fam.percentuale = f_float(f"fam_perc_{fam.id}", 100)
    if f_str("fam_new_nome"):
        e.familiari.append(Familiare(relazione=f_str("fam_new_rel", "figlio"), nome=f_str("fam_new_nome"),
                                     codice_fiscale=f_str("fam_new_cf").upper(),
                                     data_nascita=f_date("fam_new_nascita"),
                                     percentuale=f_float("fam_new_perc", 100)))


@bp.route("/employees/new", methods=["GET", "POST"])
@bp.route("/employees/<int:emp_id>", methods=["GET", "POST"])
@handle_user_error
def employee(emp_id=None):
    e = ws_get(Employee, emp_id) if emp_id else None
    if request.method == "POST":
        action = request.form.get("action", "save")
        if e and action == "note":
            post_note("hr.employee", e.id)
            return redirect(url_for("main.employee", emp_id=e.id) + "#chatter")
        if e and action == "delete":
            if any(s.state == "done" for s in e.slip_ids):
                raise payroll.UserError("Il dipendente ha buste paga confermate: archivialo (togli 'Attivo').")
            db.session.delete(e)
            db.session.commit()
            flash("Dipendente eliminato.", "success")
            return redirect(url_for("main.employees"))
        if not f_str("last_name") or not f_str("first_name"):
            raise payroll.UserError("Cognome e nome sono obbligatori.")
        new = e is None
        if new:
            e = Employee(workspace_id=g.ws.id)
            db.session.add(e)
        _save_employee(e)
        db.session.flush()
        if new:
            payroll.log_message(g.ws.id, "hr.employee", e.id, body="Dipendente creato", author=author())
        db.session.commit()
        flash("Dipendente salvato.", "success")
        if new:
            flash("Ora crea il contratto: senza contratto in corso non si possono calcolare buste paga.", "info")
        return redirect(url_for("main.employee", emp_id=e.id, tab=request.form.get("tab", "")))
    nxt = 1 + max([int(x.registration_number) for x in ws_query(Employee) if (x.registration_number or "").isdigit()]
                  or [0])
    return render_template("employee_form.html", e=e, calendars=_calendars(), qualifiche=QUALIFICHE,
                           nuova_matricola=f"{nxt:04d}", tab=request.args.get("tab") or "work",
                           messages=messages_for("hr.employee", e.id) if e else [], oggi=date.today())


# ===========================================================================
# Contratti
# ===========================================================================
@bp.route("/contracts")
def contracts():
    q = ws_query(Contract)
    stato = request.args.get("state")
    if stato:
        q = q.filter(Contract.state == stato)
    rows = q.order_by(Contract.date_start.desc()).all()
    return render_template("contract_list.html", rows=rows, stato=stato, states=CONTRACT_STATES)


@bp.route("/contracts/new", methods=["GET", "POST"])
@bp.route("/contracts/<int:con_id>", methods=["GET", "POST"])
@handle_user_error
def contract(con_id=None):
    c = ws_get(Contract, con_id) if con_id else None
    if request.method == "POST":
        action = request.form.get("action", "save")
        if c and action == "note":
            post_note("hr.version", c.id)
            return redirect(url_for("main.contract", con_id=c.id) + "#chatter")
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
            return redirect(url_for("main.contract", con_id=c.id))
        if c and action == "delete":
            if Payslip.query.filter_by(contract_id=c.id).first():
                raise payroll.UserError("Il contratto è usato in buste paga: annullalo invece di eliminarlo.")
            emp_id = c.employee_id
            db.session.delete(c)
            db.session.commit()
            return redirect(url_for("main.employee", emp_id=emp_id))
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
        return redirect(url_for("main.contract", con_id=c.id))
    emp = c.employee if c else (ws_get(Employee, request.args.get("employee_id", type=int))
                                if request.args.get("employee_id") else None)
    return render_template(
        "contract_form.html", c=c, emp=emp, employees=ws_query(Employee).order_by(Employee.last_name).all(),
        livelli=ws_query(Livello).order_by(Livello.codice).all(), structures=ws_query(PayrollStructure).all(),
        calendars=_calendars(), types=CONTRACT_TYPES, states=CONTRACT_STATES,
        messages=messages_for("hr.version", c.id) if c else [])


# ===========================================================================
# Orari di lavoro
# ===========================================================================
@bp.route("/calendars")
def calendars():
    return render_template("calendar_list.html", rows=_calendars())


@bp.route("/calendars/new", methods=["GET", "POST"])
@bp.route("/calendars/<int:cal_id>", methods=["GET", "POST"])
@handle_user_error
def calendar(cal_id=None):
    cal = ws_get(ResourceCalendar, cal_id) if cal_id else None
    if request.method == "POST":
        if cal and request.form.get("action") == "delete":
            if Contract.query.filter_by(resource_calendar_id=cal.id).first() or \
                    Employee.query.filter_by(resource_calendar_id=cal.id).first():
                raise payroll.UserError("L'orario è usato da dipendenti o contratti.")
            db.session.delete(cal)
            db.session.commit()
            return redirect(url_for("main.calendars"))
        if not f_str("name"):
            raise payroll.UserError("Il nome è obbligatorio.")
        if cal is None:
            cal = ResourceCalendar(workspace_id=g.ws.id)
            db.session.add(cal)
        cal.name, cal.hours_per_day = f_str("name"), f_float("hours_per_day", 8)
        for a in list(cal.attendance_ids):
            if f_bool(f"at_del_{a.id}"):
                cal.attendance_ids.remove(a)
            elif f"at_day_{a.id}" in request.form:
                a.dayofweek, a.name = f_int(f"at_day_{a.id}"), f_str(f"at_name_{a.id}")
                a.hour_from, a.hour_to = f_float(f"at_from_{a.id}"), f_float(f"at_to_{a.id}")
        if f_str("at_new_from") and f_str("at_new_to"):
            cal.attendance_ids.append(ResourceCalendarAttendance(
                dayofweek=f_int("at_new_day"), name=f_str("at_new_name"),
                hour_from=f_float("at_new_from"), hour_to=f_float("at_new_to")))
        for a in cal.attendance_ids:
            if a.hour_to <= a.hour_from:
                raise payroll.UserError("In ogni fascia l'ora di fine deve essere dopo l'ora di inizio.")
        db.session.commit()
        flash("Orario salvato.", "success")
        return redirect(url_for("main.calendar", cal_id=cal.id))
    return render_template("calendar_form.html", cal=cal, weekdays=WEEKDAYS)


# ===========================================================================
# Assenze, tipi di assenza, festività
# ===========================================================================
@bp.route("/leaves", methods=["GET", "POST"])
@handle_user_error
def leaves():
    if request.method == "POST":
        lv = ws_get(Leave, f_id("leave_id"))
        action = request.form.get("action")
        if action in ("validate", "refuse", "confirm"):
            lv.state = action
        elif action == "delete":
            db.session.delete(lv)
        db.session.commit()
        flash("Assenza aggiornata. Nelle buste in bozza premi 'Riestrai dati busta paga'.", "success")
        return redirect(request.referrer or url_for("main.leaves"))
    q = ws_query(Leave)
    stato = request.args.get("state")
    if stato:
        q = q.filter(Leave.state == stato)
    emp_id = request.args.get("employee_id", type=int)
    if emp_id:
        q = q.filter(Leave.employee_id == emp_id)
    rows = q.order_by(Leave.date_from.desc()).all()
    durate = {lv.id: leave_duration(lv) for lv in rows}
    return render_template("leave_list.html", rows=rows, durate=durate, stato=stato, emp_id=emp_id,
                           employees=ws_query(Employee).order_by(Employee.last_name).all())


@bp.route("/leaves/new", methods=["GET", "POST"])
@bp.route("/leaves/<int:leave_id>", methods=["GET", "POST"])
@handle_user_error
def leave(leave_id=None):
    lv = ws_get(Leave, leave_id) if leave_id else None
    if request.method == "POST":
        d1, d2 = f_date("date_from"), f_date("date_to") or f_date("date_from")
        if not d1 or d2 < d1:
            raise payroll.UserError("Controlla le date dell'assenza.")
        emp = ws_get(Employee, f_id("employee_id"))
        ltype = ws_get(LeaveType, f_id("holiday_status_id"))
        if lv is None:
            lv = Leave(workspace_id=g.ws.id, state="confirm", date_from=d1, date_to=d2)
            db.session.add(lv)
        lv.employee, lv.holiday_status = emp, ltype
        lv.date_from, lv.date_to = d1, d2
        lv.request_unit_hours = f_bool("request_unit_hours")
        lv.hour_from = f_float("hour_from") if lv.request_unit_hours else None
        lv.hour_to = f_float("hour_to") if lv.request_unit_hours else None
        if lv.request_unit_hours and (lv.hour_to or 0) <= (lv.hour_from or 0):
            raise payroll.UserError("L'ora di fine deve essere dopo l'ora di inizio.")
        lv.name = f_str("name")
        if f_bool("approva"):
            lv.state = "validate"
        db.session.commit()
        flash("Assenza salvata.", "success")
        return redirect(url_for("main.leaves"))
    return render_template("leave_form.html", lv=lv, employees=ws_query(Employee).filter_by(active=True)
                           .order_by(Employee.last_name).all(),
                           types=ws_query(LeaveType).filter_by(active=True).order_by(LeaveType.sequence).all(),
                           emp_id=request.args.get("employee_id", type=int))


@bp.route("/leave-types", methods=["GET", "POST"])
def leave_types():
    if request.method == "POST":
        for t in ws_query(LeaveType):
            t.name = f_str(f"n_{t.id}", t.name)
            t.code = f_str(f"c_{t.id}", t.code).upper()
            t.sequence = f_int(f"s_{t.id}", t.sequence)
            t.color = f_str(f"col_{t.id}", t.color)
            t.unpaid = f_bool(f"u_{t.id}")
            t.active = f_bool(f"a_{t.id}")
        if f_str("new_name") and f_str("new_code"):
            db.session.add(LeaveType(workspace_id=g.ws.id, name=f_str("new_name"), code=f_str("new_code").upper(),
                                     sequence=f_int("new_seq", 20), unpaid=f_bool("new_unpaid")))
        db.session.commit()
        flash("Tipi di assenza salvati.", "success")
        return redirect(url_for("main.leave_types"))
    return render_template("leave_types.html", rows=ws_query(LeaveType).order_by(LeaveType.sequence).all())


@bp.route("/holidays", methods=["GET", "POST"])
def holidays():
    if request.method == "POST":
        if request.form.get("action") == "delete":
            db.session.delete(ws_get(ResourceCalendarLeave, f_id("id")))
        elif f_date("date") and f_str("name"):
            cid = f_id("calendar_id")
            db.session.add(ResourceCalendarLeave(workspace_id=g.ws.id, name=f_str("name"), date=f_date("date"),
                                                 calendar_id=ws_get(ResourceCalendar, cid).id if cid else None))
        db.session.commit()
        return redirect(url_for("main.holidays", anno=request.form.get("anno")))
    anno = request.args.get("anno", type=int) or date.today().year
    rows = [h for h in ws_query(ResourceCalendarLeave).order_by(ResourceCalendarLeave.date) if h.date.year == anno]
    return render_template("holidays.html", rows=rows, anno=anno, calendars=_calendars())
