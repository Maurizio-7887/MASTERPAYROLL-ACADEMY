"""Blueprint «cu» — Certificazione Unica: i dati di sintesi dell'anno per ogni dipendente (redditi, ritenute, contributi, TFR).

Una cartella per attività: le pagine HTML sono in templates/cu/."""
from datetime import date

from flask import g, render_template, request

from ...models import Employee
from ...riepiloghi import dati_cu, dipendenti_anno
from ..comune import area, ws_get

bp = area("cu")


@bp.route("/cu")
def certificazione():
    anno = request.args.get("anno", type=int) or 2026
    dip = dipendenti_anno(g.ws.id, anno)
    emp_id = request.args.get("employee_id", type=int)
    e = ws_get(Employee, emp_id) if emp_id else (dip[0] if dip else None)
    dati = dati_cu(e, anno, g.ws.id) if e else {}
    riepilogo = [(x, dati_cu(x, anno, g.ws.id)) for x in dip]
    return render_template("cu/certificazione.html", anno=anno, dip=dip, e=e, d=dati, riepilogo=riepilogo,
                           oggi=date.today())
