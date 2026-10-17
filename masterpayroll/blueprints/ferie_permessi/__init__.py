"""Blueprint «ferie_permessi» — contatori di ferie e permessi (ROL + ex festività): maturato, goduto, residuo.

Una cartella per attività: le pagine HTML sono in templates/ferie_permessi/."""
from datetime import date

from flask import g, render_template, request

from ...hr_service import contatori_ferie
from ...models import Employee, Parametro, Payslip, month_bounds
from ..comune import area, ws_query

bp = area("ferie_permessi")


def _par(codice, default):
    p = ws_query(Parametro).filter_by(codice=codice).first()
    return p.valore if p else default


@bp.route("/ferie-permessi")
def contatori():
    try:
        al = date.fromisoformat(request.args.get("al", ""))
    except ValueError:   # di norma: fine del mese dell'ultima busta completata
        ultima = ws_query(Payslip).filter_by(state="done").order_by(Payslip.date_to.desc()).first()
        al = month_bounds(ultima.date_to)[1] if ultima else date.today()
    ore_f, ore_r = _par("FERIE_ORE_ANNO", 160.0), _par("ROL_ORE_ANNO", 104.0)
    righe = []
    for e in ws_query(Employee).order_by(Employee.last_name, Employee.first_name):
        if not any(c.state in ("open", "close") and c.date_start <= al and (c.date_end is None or c.date_end >= date(al.year, 1, 1))
                   for c in e.contract_ids):
            continue
        righe.append((e, contatori_ferie(e, al.year, al, ore_f, ore_r)))
    return render_template("ferie_permessi/contatori.html", righe=righe, al=al, ore_f=ore_f, ore_r=ore_r, ws=g.ws)
