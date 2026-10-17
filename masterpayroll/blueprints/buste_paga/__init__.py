"""Blueprint «buste_paga» — Buste paga dipendente (hr.payslip): elenco, nuova, calcolo, stampa, analisi righe.

Una cartella per attività: le pagine HTML sono in templates/buste_paga/."""
from collections import OrderedDict, defaultdict
from datetime import date
from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from ... import mailer, payroll, reports
from ...models import (ContributionRegister, Contract, Employee, PayrollStructure, Payslip, PayslipInput,
                      PayslipLine, PayslipRun, PayslipWorkedDays, SalaryRuleCategory, db, month_bounds)
from ..comune import (author, f_bool, f_date, f_float, f_id, f_str, f_text, group_rows, handle_user_error,
                     messages_for, post_note, ws_get, ws_query)

from ..comune import area

bp = area("buste_paga")

STATE_FILTERS = [("draft", "Bozza"), ("verify", "Revisione in attesa"), ("done", "Completata"),
                 ("cancel", "Rifiutata")]

def _pdf_response(data, filename):
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@bp.route("/payslips")
def payslips():
    q = ws_query(Payslip)
    stati = request.args.getlist("state")
    if stati:
        q = q.filter(Payslip.state.in_(stati))
    if request.args.get("credit_note"):
        q = q.filter(Payslip.credit_note.is_(True))
    emp_id = request.args.get("employee_id", type=int)
    if emp_id:
        q = q.filter(Payslip.employee_id == emp_id)
    run_id = request.args.get("run_id", type=int)
    if run_id:
        q = q.filter(Payslip.payslip_run_id == run_id)
    mese = request.args.get("mese")  # AAAA-MM
    if mese:
        try:
            d1, d2 = month_bounds(date.fromisoformat(mese + "-01"))
            q = q.filter(Payslip.date_from >= d1, Payslip.date_to <= d2)
        except ValueError:
            pass
    search = (request.args.get("q") or "").strip()
    rows = q.order_by(Payslip.id.desc()).all()
    if search:
        s = search.lower()
        rows = [r for r in rows if s in (r.name or "").lower() or s in (r.number or "").lower()
                or s in r.employee.name.lower()]
    group = request.args.get("group", "")
    keyfns = {
        "employee": (lambda r: r.employee.name, None),
        "run": (lambda r: r.payslip_run.name if r.payslip_run else "Nessun gruppo", None),
        "state": (lambda r: r.state, lambda k: payroll.STATE_LABEL[k]),
        "month": (lambda r: (r.date_from.year, r.date_from.month),
                  lambda k: f"{payroll.MESI[k[1]].capitalize()} {k[0]}"),
    }
    groups = group_rows(rows, *keyfns[group]) if group in keyfns else [(None, rows)]
    employees = ws_query(Employee).order_by(Employee.last_name).all()
    runs = ws_query(PayslipRun).order_by(PayslipRun.date_start.desc()).all()
    return render_template("buste_paga/payslip_list.html", groups=groups, n=len(rows), stati=stati, group=group,
                           search=search, employees=employees, runs=runs, emp_id=emp_id, run_id=run_id,
                           mese=mese, state_filters=STATE_FILTERS)


@bp.route("/payslips/bulk", methods=["POST"])
@handle_user_error
def payslips_bulk():
    ids = request.form.getlist("ids", type=int)
    slips = [ws_get(Payslip, i) for i in ids]
    action = request.form.get("action")
    back = request.form.get("next") or url_for("buste_paga.payslips")
    if not slips:
        flash("Seleziona almeno una busta paga.", "warning")
        return redirect(back)
    if action in ("draft", "verify", "done", "cancel"):
        payroll.change_state(slips, action, author())
        db.session.commit()
        flash(f"Cambio stato eseguito su {len(slips)} buste paga.", "success")
    elif action == "pdf":
        return _pdf_response(reports.payslip_pdf(g.ws, slips), "buste_paga.pdf")
    elif action == "details":
        return _pdf_response(reports.payslip_details_pdf(g.ws, slips), "dettaglio_buste_paga.pdf")
    elif action == "email":
        n = sum(1 for s in slips if mailer.send_payslip(g.ws, s, author()))
        db.session.commit()
        flash(f"{n} email preparate: le trovi in Libro paga → Posta in uscita.", "success")
    elif action == "delete":
        for s in slips:
            payroll.check_unlink(s)
            db.session.delete(s)
        db.session.commit()
        flash(f"Eliminate {len(slips)} buste paga.", "success")
    return redirect(back)


@bp.route("/payslips/new", methods=["GET", "POST"])
@handle_user_error
def payslip_new():
    if request.method == "POST":
        emp = ws_get(Employee, f_id("employee_id"))
        d1, d2 = f_date("date_from"), f_date("date_to")
        if not d1 or not d2:
            flash("Indica il periodo.", "danger")
            return redirect(url_for("buste_paga.payslip_new"))
        if d1 > d2:
            raise payroll.UserError("La data 'Dalla data' deve essere precedente ad 'Alla data'.")
        slip = Payslip(workspace_id=g.ws.id, employee=emp, date_from=d1, date_to=d2,
                       contract_id=f_id("contract_id"), struct_id=f_id("struct_id"),
                       payslip_run_id=f_id("payslip_run_id"), credit_note=f_bool("credit_note"))
        if slip.contract_id:
            ws_get(Contract, slip.contract_id)
        if slip.struct_id:
            ws_get(PayrollStructure, slip.struct_id)
        db.session.add(slip)
        db.session.flush()
        payroll.onchange_employee(slip, keep_contract=bool(slip.contract_id), keep_struct=bool(slip.struct_id))
        if not slip.name:
            payroll.compute_name(slip)
        payroll.log_message(g.ws.id, "hr.payslip", slip.id, body="Busta paga creata", author=author())
        db.session.commit()
        if not slip.contract_id:
            flash("Il dipendente non ha un contratto in corso nel periodo: la busta non potrà essere calcolata.",
                  "warning")
        return redirect(url_for("buste_paga.payslip", slip_id=slip.id))
    oggi = date.today()
    d1, d2 = month_bounds(oggi)
    return render_template("buste_paga/payslip_new.html", employees=ws_query(Employee).filter_by(active=True)
                           .order_by(Employee.last_name).all(),
                           contracts=ws_query(Contract).filter(Contract.state.in_(["open", "close"])).all(),
                           structures=ws_query(PayrollStructure).all(),
                           runs=ws_query(PayslipRun).filter_by(state="draft").all(), d1=d1, d2=d2,
                           emp_id=request.args.get("employee_id", type=int))


@bp.route("/payslips/<int:slip_id>", methods=["GET", "POST"])
@handle_user_error
def payslip(slip_id):
    slip = ws_get(Payslip, slip_id)
    if request.method == "POST":
        action = request.form.get("action", "save")
        a = author()
        if action == "note":
            post_note("hr.payslip", slip.id)
            return redirect(url_for("buste_paga.payslip", slip_id=slip.id, tab=request.form.get("tab")) + "#chatter")
        if action == "save" or action == "compute_sheet":
            _save_payslip_form(slip)
        if action == "compute_sheet":
            if slip.state not in ("draft", "verify"):
                raise payroll.UserError("Si possono calcolare solo buste in bozza o in attesa.")
            payroll.compute_sheet(slip, a)
            flash("Scheda calcolata.", "success")
        elif action == "action_payslip_done":
            payroll.action_payslip_done(slip, a)
            flash("Busta paga confermata.", "success")
        elif action == "refund_sheet":
            refund = payroll.refund_sheet(slip, a)
            db.session.commit()
            flash("Creato lo storno (nota di credito).", "success")
            return redirect(url_for("buste_paga.payslip", slip_id=refund.id))
        elif action == "action_payslip_draft":
            payroll.action_payslip_draft(slip, a)
        elif action == "action_payslip_cancel":
            payroll.action_payslip_cancel(slip, a)
        elif action == "onchange_employee":
            _save_payslip_form(slip)
            payroll.onchange_employee(slip, keep_contract=True, keep_struct=True)
            payroll.log_message(g.ws.id, "hr.payslip", slip.id, body="Dati busta paga riestratti", author=a)
            flash("Dati riestratti: giorni lavorati e apporti aggiornati.", "info")
        elif action == "delete":
            payroll.check_unlink(slip)
            db.session.delete(slip)
            db.session.commit()
            flash("Busta paga eliminata.", "success")
            return redirect(url_for("buste_paga.payslips"))
        elif action == "email":
            mailer.send_payslip(g.ws, slip, a)
            flash("Email preparata: la trovi in Libro paga → Posta in uscita.", "success")
        elif action == "save_lines":
            if not g.ws.allow_edit_payslip_lines:
                abort(403)
            for ln in slip.line_ids:
                ln.name = f_str(f"ln_name_{ln.id}", ln.name)
                ln.quantity = f_float(f"ln_qty_{ln.id}", ln.quantity)
                ln.rate = f_float(f"ln_rate_{ln.id}", ln.rate)
                ln.amount = f_float(f"ln_amount_{ln.id}", ln.amount)
                ln.compute_total()
            payroll.log_message(g.ws.id, "hr.payslip", slip.id, body="Righe modificate a mano", author=a)
            flash("Righe aggiornate.", "success")
        elif action == "save":
            flash("Salvato.", "success")
        db.session.commit()
        return redirect(url_for("buste_paga.payslip", slip_id=slip.id, tab=request.form.get("tab", "")))
    editable = slip.state in ("draft", "verify")
    return render_template("buste_paga/payslip_form.html", slip=slip, editable=editable, tab=request.args.get("tab") or "input",
        contracts=[c for c in slip.employee.contract_ids if c.state in ("open", "close")],
        structures=ws_query(PayrollStructure).all(), runs=ws_query(PayslipRun).all(),
        messages=messages_for("hr.payslip", slip.id), cat_totals=_category_totals(slip),
        refund_of=Payslip.query.filter_by(refunded_id=slip.id).first())


def _category_totals(slip):
    """Valori finali di categories.CODICE (le categorie figlie si sommano nei padri)."""
    tot = OrderedDict()
    for ln in slip.line_ids:
        c, guard = ln.category, 0
        while c is not None and guard < 20:
            if c.code:
                tot[c.code] = tot.get(c.code, 0.0) + ln.total
            c, guard = c.parent, guard + 1
    return list(tot.items())


def _save_payslip_form(slip):
    if slip.state not in ("draft", "verify"):
        if "note" in request.form:
            old = payroll.snapshot(slip)
            slip.note = f_text("note")
            slip.hide_child_lines = f_bool("hide_child_lines")
            slip.hide_invisible_lines = f_bool("hide_invisible_lines")
            payroll.track_payslip(slip, old, author())
        return
    old = payroll.snapshot(slip)
    if "name" in request.form:
        slip.name = f_str("name")
        d1, d2 = f_date("date_from") or slip.date_from, f_date("date_to") or slip.date_to
        if d1 > d2:
            raise payroll.UserError("La data 'Dalla data' deve essere precedente ad 'Alla data'.")
        slip.date_from, slip.date_to = d1, d2
        cid = f_id("contract_id")
        slip.contract_id = ws_get(Contract, cid).id if cid else None
        sid = f_id("struct_id")
        slip.struct_id = ws_get(PayrollStructure, sid).id if sid else None
        rid = f_id("payslip_run_id")
        slip.payslip_run_id = ws_get(PayslipRun, rid).id if rid else None
        slip.credit_note = f_bool("credit_note")
        slip.note = f_text("note")
        slip.hide_child_lines = f_bool("hide_child_lines")
        slip.hide_invisible_lines = f_bool("hide_invisible_lines")
    # giorni lavorati
    for wd in list(slip.worked_days_line_ids):
        if f_bool(f"wd_del_{wd.id}"):
            slip.worked_days_line_ids.remove(wd)
            continue
        if f"wd_code_{wd.id}" in request.form:
            wd.name = f_str(f"wd_name_{wd.id}", wd.name)
            wd.code = f_str(f"wd_code_{wd.id}", wd.code).upper()
            wd.sequence = int(f_float(f"wd_seq_{wd.id}", wd.sequence))
            wd.number_of_days = f_float(f"wd_days_{wd.id}", wd.number_of_days)
            wd.number_of_hours = f_float(f"wd_hours_{wd.id}", wd.number_of_hours)
    if f_str("wd_new_code"):
        slip.worked_days_line_ids.append(PayslipWorkedDays(
            name=f_str("wd_new_name") or f_str("wd_new_code"), code=f_str("wd_new_code").upper(),
            sequence=int(f_float("wd_new_seq", 10)), number_of_days=f_float("wd_new_days"),
            number_of_hours=f_float("wd_new_hours"), contract_id=slip.contract_id))
    # apporti
    for i in list(slip.input_line_ids):
        if f_bool(f"in_del_{i.id}"):
            slip.input_line_ids.remove(i)
            continue
        if f"in_amount_{i.id}" in request.form:
            i.amount = f_float(f"in_amount_{i.id}", i.amount)
            i.amount_qty = f_float(f"in_qty_{i.id}", i.amount_qty)
    if f_str("in_new_code"):
        slip.input_line_ids.append(PayslipInput(
            name=f_str("in_new_name") or f_str("in_new_code"), code=f_str("in_new_code").upper(),
            sequence=int(f_float("in_new_seq", 10)), amount=f_float("in_new_amount"),
            amount_qty=f_float("in_new_qty"), contract_id=slip.contract_id))
    db.session.flush()
    payroll.track_payslip(slip, old, author())


@bp.route("/payslips/<int:slip_id>/lines")
def payslip_lines_of(slip_id):
    slip = ws_get(Payslip, slip_id)
    return render_template("buste_paga/payslip_lines_detail.html", slip=slip)


@bp.route("/payslips/<int:slip_id>/pdf")
def payslip_pdf(slip_id):
    slip = ws_get(Payslip, slip_id)
    kind = request.args.get("report", "payslip")
    name = (slip.number or f"bozza_{slip.id}").replace("/", "_")
    if kind == "details":
        return _pdf_response(reports.payslip_details_pdf(g.ws, [slip]), f"dettaglio_{name}.pdf")
    return _pdf_response(reports.payslip_pdf(g.ws, [slip]), f"busta_{name}.pdf")


@bp.route("/payslip-lines")
def payslip_lines():
    q = (db.session.query(PayslipLine).join(Payslip, PayslipLine.slip_id == Payslip.id)
         .filter(Payslip.workspace_id == g.ws.id))
    stati = request.args.getlist("state") or ["done"]
    q = q.filter(Payslip.state.in_(stati))
    mese_da = request.args.get("da")
    mese_a = request.args.get("a")
    if mese_da:
        q = q.filter(Payslip.date_from >= date.fromisoformat(mese_da + "-01"))
    if mese_a:
        q = q.filter(Payslip.date_to <= month_bounds(date.fromisoformat(mese_a + "-01"))[1])
    code = (request.args.get("code") or "").strip().upper()
    if code:
        q = q.filter(PayslipLine.code == code)
    cat_id = request.args.get("category_id", type=int)
    if cat_id:
        q = q.filter(PayslipLine.category_id == cat_id)
    reg_id = request.args.get("register_id", type=int)
    if reg_id:
        q = q.filter(PayslipLine.register_id == reg_id)
    emp_id = request.args.get("employee_id", type=int)
    if emp_id:
        q = q.filter(PayslipLine.employee_id == emp_id)
    if request.args.get("solo_stampa"):
        q = q.filter(PayslipLine.appears_on_payslip.is_(True))
    lines = q.order_by(Payslip.date_from, PayslipLine.sequence).all()
    righe = request.args.get("righe", "rule")
    colonne = request.args.get("colonne", "month")

    def key(dim, ln):
        if dim == "rule":
            return (ln.sequence or 0, ln.code or "", ln.name or "")
        if dim == "category":
            return ln.category.code if ln.category else "—"
        if dim == "employee":
            return ln.employee.name if ln.employee else "—"
        if dim == "month":
            return ln.slip.date_from.strftime("%Y-%m")
        if dim == "register":
            return ln.register.name if ln.register else "—"
        return "Totale"

    pivot = OrderedDict()
    cols = []
    for ln in lines:
        rk, ck = key(righe, ln), key(colonne, ln)
        if ck not in cols:
            cols.append(ck)
        v = -ln.total if ln.slip.credit_note else ln.total
        pivot.setdefault(rk, defaultdict(float))[ck] += v
    cols = sorted(cols)
    rows = sorted(pivot.items(), key=lambda kv: kv[0])
    return render_template("buste_paga/payslip_line_analysis.html", rows=rows, cols=cols, righe=righe, colonne=colonne, n=len(lines),
        stati=stati, code=code, cat_id=cat_id, reg_id=reg_id, emp_id=emp_id, mese_da=mese_da, mese_a=mese_a,
        categories=ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code).all(),
        registers=ws_query(ContributionRegister).all(),
        employees=ws_query(Employee).order_by(Employee.last_name).all(), state_filters=STATE_FILTERS,
        solo_stampa=request.args.get("solo_stampa"))
