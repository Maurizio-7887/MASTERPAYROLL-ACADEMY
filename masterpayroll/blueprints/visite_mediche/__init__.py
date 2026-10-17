"""Blueprint «visite_mediche» — sorveglianza sanitaria (D.Lgs. 81/08 art. 41), modulo OCA
hr_employee_medical_examination, e scadenzario del personale (visite, corsi, documenti).

Una cartella per attività: le pagine HTML sono in templates/visite_mediche/."""
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for

from ... import payroll
from ...models import Employee, VisitaMedica, db
from ...scadenze import ESITI_VISITA, STATI, TIPI_VISITA, preavviso, scadenzario
from ..comune import area, author, f_date, f_id, f_str, f_text, handle_user_error, ws_get, ws_query

bp = area("visite_mediche")


def _salva(v):
    e = ws_get(Employee, f_id("employee_id"))
    d = f_date("data")
    if not d:
        raise payroll.UserError("La data della visita è obbligatoria.")
    scad = f_date("scadenza")
    if scad and scad <= d:
        raise payroll.UserError("La prossima visita deve essere dopo la data della visita.")
    v.employee, v.data, v.scadenza = e, d, scad
    v.tipo, v.esito = f_str("tipo", "periodica"), f_str("esito", "idoneo")
    v.prescrizioni, v.medico, v.note = f_str("prescrizioni"), f_str("medico"), f_text("note")
    if v.esito == "idoneo_prescrizioni" and not v.prescrizioni:
        raise payroll.UserError("Con l'esito «idoneo con prescrizioni» scrivi le prescrizioni o le limitazioni.")


@bp.route("/visite-mediche", methods=["GET", "POST"])
@handle_user_error
def elenco():
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        v = VisitaMedica(workspace_id=g.ws.id)
        _salva(v)
        db.session.add(v)
        db.session.flush()
        payroll.log_message(g.ws.id, "hr.employee", v.employee.id, author=author(),
                            body=f"Visita medica {v.tipo} del {v.data.strftime('%d/%m/%Y')}: "
                                 f"{dict(ESITI_VISITA).get(v.esito)}" + (f", prossima entro il {v.scadenza.strftime('%d/%m/%Y')}" if v.scadenza else ""))
        db.session.commit()
        flash(f"Visita di {v.employee.name} registrata.", "success")
        return redirect(url_for("visite_mediche.elenco"))
    emp_id = request.args.get("employee_id", type=int)
    q = ws_query(VisitaMedica)
    if emp_id:
        q = q.filter_by(employee_id=emp_id)
    visite = q.order_by(VisitaMedica.data.desc()).all()
    medico = next((v.medico for v in visite if v.medico), "")
    return render_template("visite_mediche/elenco.html", visite=visite, emp_id=emp_id, medico=medico,
                           attivi=ws_query(Employee).filter_by(active=True).order_by(Employee.last_name).all(),
                           tipi=TIPI_VISITA, esiti=ESITI_VISITA)


@bp.route("/visite-mediche/<int:vis_id>", methods=["GET", "POST"])
@handle_user_error
def visita(vis_id):
    v = ws_get(VisitaMedica, vis_id)
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        if request.form.get("action") == "delete":
            db.session.delete(v)
            db.session.commit()
            flash("Visita eliminata.", "success")
            return redirect(url_for("visite_mediche.elenco"))
        _salva(v)
        db.session.commit()
        flash("Visita salvata.", "success")
        return redirect(url_for("visite_mediche.visita", vis_id=v.id))
    return render_template("visite_mediche/visita.html", v=v, tipi=TIPI_VISITA, esiti=ESITI_VISITA,
                           attivi=ws_query(Employee).order_by(Employee.last_name).all())


@bp.route("/scadenzario")
def scadenzario_hr():
    try:
        al = date.fromisoformat(request.args.get("al", ""))
    except ValueError:
        al = date.today()
    tutte = request.args.get("tutte") == "1"
    righe = scadenzario(g.ws.id, al, solo_da_guardare=not tutte)
    return render_template("visite_mediche/scadenzario.html", righe=righe, al=al, tutte=tutte, stati=STATI,
                           preavviso=preavviso(g.ws.id))
