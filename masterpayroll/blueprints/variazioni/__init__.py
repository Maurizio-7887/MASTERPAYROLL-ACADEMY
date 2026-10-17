"""Blueprint «variazioni» — storico degli orari e trasformazioni part-time ↔ tempo pieno (hr.employee.calendar).

Una cartella per attività: le pagine HTML sono in templates/variazioni/."""
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for

from ... import variazioni
from ...models import Contract, Employee, EmployeeCalendar, ResourceCalendar
from ..comune import area, author, f_date, f_float, f_id, f_str, handle_user_error, ws_get, ws_query

bp = area("variazioni")


@bp.route("/variazioni", methods=["GET", "POST"])
@handle_user_error
def elenco():
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        e = ws_get(Employee, f_id("employee_id"))
        cal = ws_get(ResourceCalendar, f_id("calendar_id"))
        nuova, n = variazioni.varia(e, f_date("dal"), cal, f_float("part_time", 0) or None, f_str("motivo"), g.ws,
                                    author())
        msg = (f"Variazione registrata: dal {f_date('dal').strftime('%d/%m/%Y')} vale la nuova versione del contratto "
               f"«{nuova.name}»." if nuova else "Variazione di orario registrata nello storico.")
        if n:
            msg += f" Ricalcolate {n} buste non ancora confermate."
        flash(msg, "success")
        return redirect(url_for("variazioni.elenco", employee_id=e.id))
    emp_id = request.args.get("employee_id", type=int)
    attivi = ws_query(Employee).filter_by(active=True).order_by(Employee.last_name).all()
    q = ws_query(EmployeeCalendar)
    if emp_id:
        q = q.filter_by(employee_id=emp_id)
    righe = sorted(q.all(), key=lambda r: (r.employee.name, r.date_start or date.min))
    # versioni dei contratti nate da una trasformazione (stesso dipendente, contratti contigui)
    versioni = []
    for c in ws_query(Contract).order_by(Contract.date_start).all():
        prec = [x for x in c.employee.contract_ids if x.id != c.id and x.date_end and
                (c.date_start - x.date_end).days == 1]
        if prec and (not emp_id or c.employee_id == emp_id):
            versioni.append((prec[-1], c))
    attuale = {e.id: e.contract_id for e in attivi}
    return render_template("variazioni/elenco.html", attivi=attivi, righe=righe, versioni=versioni, emp_id=emp_id,
                           calendari=ws_query(ResourceCalendar).order_by(ResourceCalendar.name).all(), attuale=attuale)
