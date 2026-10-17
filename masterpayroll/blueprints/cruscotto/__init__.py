"""Blueprint «cruscotto» — Cruscotto, esercitazioni, guida e ripristino dell'ambiente.

Una cartella per attività: le pagine HTML sono in templates/cruscotto/."""
from flask import abort, flash, g, redirect, render_template, request, url_for
from ...fiscale import HELPER_DOCS
from ...models import Parametro, SalaryRuleCategory
from ...models import Employee, Esercitazione, EsercitazioneSvolta, Payslip, PayslipRun, db, now
from ..comune import f_str, ws_query

from ..comune import area

bp = area("cruscotto")

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


@bp.route("/guida")
def guida():
    cats = ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code).all()
    params = ws_query(Parametro).order_by(Parametro.id).all()
    return render_template("cruscotto/guida.html", helpers=HELPER_DOCS, cats=cats, params=params)


@bp.route("/")
def dashboard():
    n_dip = ws_query(Employee).filter_by(active=True).count()
    runs = ws_query(PayslipRun).order_by(PayslipRun.date_start.desc(), PayslipRun.id.desc()).limit(5).all()
    ultimo = runs[0] if runs else None
    tot = None
    if ultimo:
        slips = [s for s in ultimo.slip_ids if s.state in ("verify", "done")]
        sign = lambda s: -1 if s.credit_note else 1  # noqa: E731
        tot = {k: sum(sign(s) * s.get_salary_line_total(k) for s in slips) for k in ("GROSS", "NET", "COSTO")}
        tot["n"] = len(slips)
    stati = {k: ws_query(Payslip).filter_by(state=k).count() for k in ("draft", "verify", "done", "cancel")}
    esercitazioni = Esercitazione.query.filter_by(attiva=True).order_by(Esercitazione.ordine).all()
    svolte = {s.esercitazione_id for s in EsercitazioneSvolta.query.filter_by(user_id=g.ws.owner_id)}
    from ...scadenze import STATI, scadenzario
    scadenze = scadenzario(g.ws.id, solo_da_guardare=True)
    return render_template("cruscotto/dashboard.html", n_dip=n_dip, runs=runs, ultimo=ultimo, tot=tot, stati=stati,
                           esercitazioni=esercitazioni, svolte=svolte, scadenze=scadenze, stati_scad=STATI)


@bp.route("/ambiente/reset", methods=["POST"])
def reset_ambiente():
    from ...seed import reset_workspace
    if g.ws_altrui:
        abort(403)
    if request.form.get("conferma") != "RIPRISTINA":
        flash("Per ripristinare scrivi RIPRISTINA nella casella di conferma.", "warning")
        return redirect(url_for("cruscotto.dashboard"))
    reset_workspace(g.ws)
    flash("Ambiente ripristinato ai dati iniziali di Ferro & Transenne Srl.", "success")
    return redirect(url_for("cruscotto.dashboard"))


@bp.route("/esercitazioni", methods=["GET", "POST"])
def esercitazioni():
    uid = g.ws.owner_id
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        es_id = request.form.get("esercitazione_id", type=int)
        rec = EsercitazioneSvolta.query.filter_by(user_id=uid, esercitazione_id=es_id).first()
        if request.form.get("azione") == "annulla":
            if rec:
                db.session.delete(rec)
        else:
            if not db.session.get(Esercitazione, es_id):
                abort(404)
            if not rec:
                rec = EsercitazioneSvolta(user_id=uid, esercitazione_id=es_id)
                db.session.add(rec)
            rec.nota = f_str("nota")
            rec.consegnata_at = now()
        db.session.commit()
        flash("Esercitazione aggiornata.", "success")
        return redirect(url_for("cruscotto.esercitazioni"))
    elenco = Esercitazione.query.filter_by(attiva=True).order_by(Esercitazione.ordine).all()
    svolte = {s.esercitazione_id: s for s in EsercitazioneSvolta.query.filter_by(user_id=uid)}
    return render_template("cruscotto/esercitazioni.html", elenco=elenco, svolte=svolte)
