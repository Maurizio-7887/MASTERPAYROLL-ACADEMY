"""Blueprint «dipendenti» — Dipendenti e familiari a carico (hr.employee).

Una cartella per attività: le pagine HTML sono in templates/dipendenti/."""
from datetime import date
from flask import flash, g, redirect, render_template, request, url_for
from ... import payroll
from ...models import (CorsoPartecipante, DocumentoDipendente, Employee, EmployeeCalendar, Familiare, ResourceCalendar,
                       VisitaMedica, db)
from ..comune import (author, f_bool, f_date, f_float, f_id, f_str, handle_user_error, messages_for, post_note,
                     ws_get, ws_query)

from ..comune import area

bp = area("dipendenti")

QUALIFICHE = ["operaio", "impiegato", "apprendista", "quadro"]

CONTRACT_TYPES = ["indeterminato", "determinato", "apprendistato"]

def _calendars():
    return ws_query(ResourceCalendar).order_by(ResourceCalendar.name).all()


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
    return render_template("dipendenti/employee_list.html", rows=rows, q=s, archiviati=request.args.get("archiviati"))


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
            return redirect(url_for("dipendenti.employee", emp_id=e.id) + "#chatter")
        if e and action == "delete":
            if any(s.state == "done" for s in e.slip_ids):
                raise payroll.UserError("Il dipendente ha buste paga confermate: archivialo (togli 'Attivo').")
            db.session.delete(e)
            db.session.commit()
            flash("Dipendente eliminato.", "success")
            return redirect(url_for("dipendenti.employees"))
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
        return redirect(url_for("dipendenti.employee", emp_id=e.id, tab=request.form.get("tab", "")))
    nxt = 1 + max([int(x.registration_number) for x in ws_query(Employee) if (x.registration_number or "").isdigit()]
                  or [0])
    hr = {}
    if e:
        hr = {"visite": VisitaMedica.query.filter_by(employee_id=e.id).count(),
              "corsi": CorsoPartecipante.query.filter_by(employee_id=e.id).count(),
              "documenti": DocumentoDipendente.query.filter_by(employee_id=e.id).count(),
              "storico": EmployeeCalendar.query.filter_by(employee_id=e.id).order_by(EmployeeCalendar.date_start).all()}
    return render_template("dipendenti/employee_form.html", e=e, calendars=_calendars(), qualifiche=QUALIFICHE, hr=hr,
                           nuova_matricola=f"{nxt:04d}", tab=request.args.get("tab") or "work",
                           messages=messages_for("hr.employee", e.id) if e else [], oggi=date.today())
