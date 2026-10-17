"""Blueprint «lul» — Libro Unico del Lavoro del mese: calendario delle presenze e sezione paga di ogni dipendente.

Una cartella per attività: le pagine HTML sono in templates/lul/."""
import calendar as _cal
from datetime import date

from flask import g, render_template, request

from ...riepiloghi import buste_del_mese, periodi, presenze_mese, totali_categorie
from ..comune import area

bp = area("lul")


@bp.route("/lul")
def libro():
    per = periodi(g.ws.id)
    anno = request.args.get("anno", type=int) or (per[0][0] if per else date.today().year)
    mese = request.args.get("mese", type=int) or (per[0][1] if per else date.today().month)
    schede = []
    for s in buste_del_mese(g.ws.id, anno, mese):
        schede.append({"slip": s, "giorni": presenze_mese(s.employee, anno, mese), "cat": totali_categorie(s),
                       "righe": [ln for ln in s.line_ids if ln.appears_on_payslip and abs(ln.total) >= 0.005]})
    ngiorni = _cal.monthrange(anno, mese)[1]
    return render_template("lul/libro.html", schede=schede, anno=anno, mese=mese, ngiorni=ngiorni,
                           settimana=[date(anno, mese, d).weekday() for d in range(1, ngiorni + 1)])
