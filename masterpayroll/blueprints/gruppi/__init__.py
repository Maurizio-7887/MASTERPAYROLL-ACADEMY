"""Blueprint «gruppi» — Gruppi buste paga (hr.payslip.run).

Una cartella per attività: le pagine HTML sono in templates/gruppi/."""
from datetime import date
from flask import Response, flash, g, redirect, render_template, request, url_for
from ... import payroll
from ...models import (Employee, PayrollStructure, PayslipRun, db, month_bounds)
from ..comune import (author, f_bool, f_date, f_id, f_str, handle_user_error, messages_for, post_note, ws_get,
                     ws_query)

from ..comune import area

bp = area("gruppi")

STATE_FILTERS = [("draft", "Bozza"), ("verify", "Revisione in attesa"), ("done", "Completata"),
                 ("cancel", "Rifiutata")]

def _pdf_response(data, filename):
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@bp.route("/runs")
def runs():
    rows = ws_query(PayslipRun).order_by(PayslipRun.date_start.desc(), PayslipRun.id.desc()).all()
    stato = request.args.get("state")
    if stato:
        rows = [r for r in rows if r.state == stato]
    return render_template("gruppi/run_list.html", rows=rows, stato=stato)


@bp.route("/runs/new", methods=["GET", "POST"])
def run_new():
    if request.method == "POST":
        d1, d2 = f_date("date_start"), f_date("date_end")
        if not f_str("name") or not d1 or not d2 or d1 > d2:
            flash("Nome e periodo (dalla data ≤ alla data) sono obbligatori.", "danger")
            return redirect(url_for("gruppi.run_new"))
        sid = f_id("struct_id")
        run = PayslipRun(workspace_id=g.ws.id, name=f_str("name"), date_start=d1, date_end=d2,
                         credit_note=f_bool("credit_note"), struct_id=ws_get(PayrollStructure, sid).id if sid else None)
        db.session.add(run)
        db.session.flush()
        payroll.log_message(g.ws.id, "hr.payslip.run", run.id, body="Gruppo creato", author=author())
        db.session.commit()
        return redirect(url_for("gruppi.run", run_id=run.id))
    d1, d2 = month_bounds(date.today())
    nome = f"{payroll.MESI[d1.month].capitalize()} {d1.year}"
    return render_template("gruppi/run_new.html", d1=d1, d2=d2, nome=nome, structures=ws_query(PayrollStructure).all())


@bp.route("/runs/<int:run_id>", methods=["GET", "POST"])
@handle_user_error
def run(run_id):
    run = ws_get(PayslipRun, run_id)
    if request.method == "POST":
        action = request.form.get("action")
        a = author()
        if action == "note":
            post_note("hr.payslip.run", run.id)
            return redirect(url_for("gruppi.run", run_id=run.id) + "#chatter")
        if action == "close_payslip_run":
            run.state = "close"
            payroll.log_message(g.ws.id, "hr.payslip.run", run.id, tracking=["Stato: Bozza → Chiuso"], author=a)
        elif action == "draft_payslip_run":
            run.state = "draft"
            payroll.log_message(g.ws.id, "hr.payslip.run", run.id, tracking=["Stato: Chiuso → Bozza"], author=a)
        elif action == "generate":
            if run.state != "draft":
                raise payroll.UserError("Il gruppo è chiuso.")
            ids = request.form.getlist("employee_ids", type=int)
            emps = [ws_get(Employee, i) for i in ids]
            slips, errors = payroll.generate_payslips(run, emps, a)
            db.session.commit()
            flash(f"Generate {len(slips)} buste paga.", "success")
            for e in errors:
                flash(e, "danger")
            return redirect(url_for("gruppi.run", run_id=run.id))
        elif action == "save":
            if run.state == "draft":
                run.name = f_str("name") or run.name
                run.date_start = f_date("date_start") or run.date_start
                run.date_end = f_date("date_end") or run.date_end
                sid = f_id("struct_id")
                run.struct_id = ws_get(PayrollStructure, sid).id if sid else None
                run.credit_note = f_bool("credit_note")
            flash("Salvato.", "success")
        elif action == "delete":
            if any(s.state not in ("draft", "cancel") for s in run.slip_ids):
                raise payroll.UserError("Il gruppo contiene buste non in bozza o rifiutate.")
            for s in list(run.slip_ids):
                db.session.delete(s)
            db.session.delete(run)
            db.session.commit()
            flash("Gruppo eliminato.", "success")
            return redirect(url_for("gruppi.runs"))
        db.session.commit()
        return redirect(url_for("gruppi.run", run_id=run.id))
    slips = sorted(run.slip_ids, key=lambda s: s.employee.name)
    in_run = {s.employee_id for s in slips}
    employees = ws_query(Employee).filter_by(active=True).order_by(Employee.last_name).all()
    tot = {k: sum(s.get_salary_line_total(k) * (-1 if s.credit_note else 1) for s in slips if s.state != "cancel")
           for k in ("GROSS", "NET", "COSTO")}
    return render_template("gruppi/run_form.html", run=run, slips=slips, employees=employees, in_run=in_run,
                           structures=ws_query(PayrollStructure).all(), tot=tot,
                           messages=messages_for("hr.payslip.run", run.id))
