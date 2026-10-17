"""Blueprint «registri» — Registri contributi e report.

Una cartella per attività: le pagine HTML sono in templates/registri/."""
from datetime import date
from flask import flash, g, redirect, render_template, request, url_for
from ... import payroll, reports
from ...models import (ContributionRegister, Partner, Payslip, PayslipLine, db, month_bounds)
from ..comune import (f_date, f_str, f_text, handle_user_error, ws_get, ws_query)
from ..buste_paga import _pdf_response

from ..comune import area

bp = area("registri")

SETTINGS = [
    ("leaves_positive", "Permessi con valore positivo",
     "Nei giorni lavorati della busta, giorni e ore di assenza hanno valori positivi (di default sono negativi)."),
    ("allow_cancel_payslips", "Consente annullamento buste paga confermate",
     "Permette di annullare (rifiutare) anche le buste in stato Completata."),
    ("prevent_compute_on_confirm", "Conferma la busta paga senza ricalcolare",
     "Quando si conferma una busta non viene ricalcolata (default attivo)."),
    ("allow_edit_payslip_lines", "Consente modifica righe busta paga",
     "Permette di correggere a mano nome, quantità, tasso e importo delle righe calcolate."),
    ("require_code_and_category", "Richiede codice/categoria nelle regole, categorie e strutture",
     "Rende obbligatori codice e categoria delle regole, il codice delle categorie e delle strutture."),
]

DEFAULT_PY_CONDITION = """# Variabili disponibili: vedi il tab Aiuto
# result = worked_days.WORK100 and worked_days.WORK100.number_of_days > 0
result = True"""

DEFAULT_PY_COMPUTE = """# Variabili disponibili: vedi il tab Aiuto
# result: importo; result_qty: quantità; result_rate: tasso %; result_name: nome della riga
result = contract.wage * 0.10"""


@bp.route("/registers")
def registers():
    rows = ws_query(ContributionRegister).order_by(ContributionRegister.name).all()
    d1, d2 = month_bounds(date.today().replace(day=1))
    return render_template("registri/register_list.html", rows=rows, d1=d1, d2=d2)


@bp.route("/registers/new", methods=["GET", "POST"])
@bp.route("/registers/<int:reg_id>", methods=["GET", "POST"])
@handle_user_error
def register(reg_id=None):
    reg = ws_get(ContributionRegister, reg_id) if reg_id else None
    if request.method == "POST":
        if reg and request.form.get("action") == "delete":
            db.session.delete(reg)
            db.session.commit()
            return redirect(url_for("registri.registers"))
        if not f_str("name"):
            raise payroll.UserError("Il nome è obbligatorio.")
        if reg is None:
            reg = ContributionRegister(workspace_id=g.ws.id)
            db.session.add(reg)
        reg.name, reg.note = f_str("name"), f_text("note")
        pname = f_str("partner_name")
        if pname:
            p = ws_query(Partner).filter_by(name=pname).first()
            if not p:
                p = Partner(workspace_id=g.ws.id, name=pname)
                db.session.add(p)
            reg.partner = p
        else:
            reg.partner = None
        reg.f24_sezione = request.form.get("f24_sezione", "")
        reg.f24_codice = f_str("f24_codice")
        reg.f24_tipo = request.form.get("f24_tipo", "debito")
        db.session.commit()
        flash("Registro salvato.", "success")
        return redirect(url_for("registri.register", reg_id=reg.id))
    lines = []
    if reg:
        lines = (db.session.query(PayslipLine).join(Payslip, PayslipLine.slip_id == Payslip.id)
                 .filter(PayslipLine.register_id == reg.id, Payslip.state == "done")
                 .order_by(Payslip.date_from.desc(), PayslipLine.slip_id, PayslipLine.sequence).limit(300).all())
    partners = ws_query(Partner).order_by(Partner.name).all()
    return render_template("registri/register_form.html", reg=reg, lines=lines, partners=partners)


@bp.route("/registers/report", methods=["GET", "POST"])
def register_report():
    """Wizard payslip.lines.contribution.register + report PDF."""
    if request.method == "POST":
        ids = request.form.getlist("ids", type=int)
        regs = [ws_get(ContributionRegister, i) for i in ids]
        d1, d2 = f_date("date_from"), f_date("date_to")
        if not regs or not d1 or not d2:
            flash("Seleziona i registri e il periodo.", "warning")
            return redirect(url_for("registri.registers"))
        return _pdf_response(reports.contribution_register_pdf(g.ws, regs, d1, d2), "registro_contributi.pdf")
    return redirect(url_for("registri.registers"))
