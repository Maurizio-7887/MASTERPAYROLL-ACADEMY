"""Blueprint «orari» — Orari di lavoro (resource.calendar).

Una cartella per attività: le pagine HTML sono in templates/orari/."""
from flask import flash, g, redirect, render_template, request, url_for
from ... import payroll
from ...hr_service import WEEKDAYS
from ...models import (Contract, Employee, ResourceCalendar, ResourceCalendarAttendance, db)
from ..comune import (f_bool, f_float, f_int, f_str, handle_user_error, ws_get, ws_query)

from ..comune import area

bp = area("orari")

QUALIFICHE = ["operaio", "impiegato", "apprendista", "quadro"]

CONTRACT_TYPES = ["indeterminato", "determinato", "apprendistato"]

def _calendars():
    return ws_query(ResourceCalendar).order_by(ResourceCalendar.name).all()


@bp.route("/calendars")
def calendars():
    return render_template("orari/calendar_list.html", rows=_calendars())


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
            return redirect(url_for("orari.calendars"))
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
        return redirect(url_for("orari.calendar", cal_id=cal.id))
    return render_template("orari/calendar_form.html", cal=cal, weekdays=WEEKDAYS)
