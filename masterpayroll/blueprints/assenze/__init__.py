"""Blueprint «assenze» — Assenze, tipi di assenza e festività (hr.leave).

Una cartella per attività: le pagine HTML sono in templates/assenze/."""
from datetime import date
from flask import flash, g, redirect, render_template, request, url_for
from ... import payroll
from ...hr_service import leave_duration
from ...models import (Employee, Leave, LeaveType, ResourceCalendar, ResourceCalendarLeave, db)
from ..comune import (f_bool, f_date, f_float, f_id, f_int, f_str, handle_user_error, ws_get, ws_query)

from ..comune import area

bp = area("assenze")

QUALIFICHE = ["operaio", "impiegato", "apprendista", "quadro"]

CONTRACT_TYPES = ["indeterminato", "determinato", "apprendistato"]

def _calendars():
    return ws_query(ResourceCalendar).order_by(ResourceCalendar.name).all()


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
        return redirect(request.referrer or url_for("assenze.leaves"))
    q = ws_query(Leave)
    stato = request.args.get("state")
    if stato:
        q = q.filter(Leave.state == stato)
    emp_id = request.args.get("employee_id", type=int)
    if emp_id:
        q = q.filter(Leave.employee_id == emp_id)
    rows = q.order_by(Leave.date_from.desc()).all()
    durate = {lv.id: leave_duration(lv) for lv in rows}
    return render_template("assenze/leave_list.html", rows=rows, durate=durate, stato=stato, emp_id=emp_id,
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
        return redirect(url_for("assenze.leaves"))
    return render_template("assenze/leave_form.html", lv=lv, employees=ws_query(Employee).filter_by(active=True)
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
        return redirect(url_for("assenze.leave_types"))
    return render_template("assenze/leave_types.html", rows=ws_query(LeaveType).order_by(LeaveType.sequence).all())


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
        return redirect(url_for("assenze.holidays", anno=request.form.get("anno")))
    anno = request.args.get("anno", type=int) or date.today().year
    rows = [h for h in ws_query(ResourceCalendarLeave).order_by(ResourceCalendarLeave.date) if h.date.year == anno]
    return render_template("assenze/holidays.html", rows=rows, anno=anno, calendars=_calendars())
