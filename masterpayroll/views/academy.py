"""Cruscotto, esercitazioni e ripristino dell'ambiente."""
from flask import abort, flash, g, redirect, render_template, request, url_for

from ..models import Employee, Esercitazione, EsercitazioneSvolta, Payslip, PayslipRun, db, now
from .common import bp, f_str, ws_query


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
    return render_template("dashboard.html", n_dip=n_dip, runs=runs, ultimo=ultimo, tot=tot, stati=stati,
                           esercitazioni=esercitazioni, svolte=svolte)


@bp.route("/ambiente/reset", methods=["POST"])
def reset_ambiente():
    from ..seed import reset_workspace
    if g.ws_altrui:
        abort(403)
    if request.form.get("conferma") != "RIPRISTINA":
        flash("Per ripristinare scrivi RIPRISTINA nella casella di conferma.", "warning")
        return redirect(url_for("main.dashboard"))
    reset_workspace(g.ws)
    flash("Ambiente ripristinato ai dati iniziali di Ferro & Transenne Srl.", "success")
    return redirect(url_for("main.dashboard"))


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
        return redirect(url_for("main.esercitazioni"))
    elenco = Esercitazione.query.filter_by(attiva=True).order_by(Esercitazione.ordine).all()
    svolte = {s.esercitazione_id: s for s in EsercitazioneSvolta.query.filter_by(user_id=uid)}
    return render_template("esercitazioni.html", elenco=elenco, svolte=svolte)
