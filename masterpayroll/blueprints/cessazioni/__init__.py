"""Blueprint «cessazioni» — fine del rapporto di lavoro: prospetto del TFR e busta di liquidazione (IT_CESS).

Una cartella per attività: le pagine HTML sono in templates/cessazioni/."""
import json
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for

from ... import tfr
from ...models import Cessazione, Employee
from ..comune import area, author, f_date, f_id, f_str, handle_user_error, ws_get, ws_query

bp = area("cessazioni")


def _contratto_in_corso(e, al=None):
    al = al or date.today()
    aperti = [c for c in e.contract_ids if c.state == "open"]
    return sorted(aperti, key=lambda c: c.date_start)[-1] if aperti else None


@bp.route("/cessazioni", methods=["GET", "POST"])
@handle_user_error
def elenco():
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        e = ws_get(Employee, f_id("employee_id"))
        data = f_date("data")
        c = _contratto_in_corso(e)
        if not data or not c:
            flash("Scegli un dipendente con un contratto in corso e la data di cessazione.", "danger")
            return redirect(url_for("cessazioni.elenco"))
        ces = tfr.cessa(e, c, data, f_str("motivo") or "dimissioni", g.ws, author())
        flash(f"Cessazione di {e.name} registrata: creata la busta di liquidazione {ces.payslip.number}. "
              "Controllala e confermala.", "success")
        return redirect(url_for("cessazioni.scheda", ces_id=ces.id))
    attivi = [e for e in ws_query(Employee).filter_by(active=True).order_by(Employee.last_name) if _contratto_in_corso(e)]
    anteprima = None
    emp_id, data_s = request.args.get("employee_id", type=int), request.args.get("data", "")
    if emp_id and data_s:
        e = ws_get(Employee, emp_id)
        c = _contratto_in_corso(e)
        try:
            d = date.fromisoformat(data_s)
        except ValueError:
            d = None
        if c and d:
            anteprima = {"employee": e, "contract": c, "data": d, "p": tfr.prospetto(e, c, d, g.ws.id)}
    righe = ws_query(Cessazione).order_by(Cessazione.data.desc()).all()
    return render_template("cessazioni/elenco.html", attivi=attivi, righe=righe, anteprima=anteprima,
                           motivi=tfr.MOTIVI, emp_id=emp_id, data_s=data_s, motivo=request.args.get("motivo", "dimissioni"))


@bp.route("/cessazioni/<int:ces_id>")
def scheda(ces_id):
    c = ws_get(Cessazione, ces_id)
    return render_template("cessazioni/scheda.html", c=c, p=json.loads(c.prospetto or "{}"), motivi=dict(tfr.MOTIVI))
