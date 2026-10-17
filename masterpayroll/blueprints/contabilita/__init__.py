"""Blueprint «contabilita» — prima nota delle paghe del mese: costi del personale, debiti verso dipendenti, INPS, Erario, INAIL, fondo TFR.

Una cartella per attività: le pagine HTML sono in templates/contabilita/."""
import json
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for

from ...models import Contabilizzazione, db, month_bounds
from ...riepiloghi import buste_del_mese, periodi, prima_nota
from ..comune import area, ws_query

bp = area("contabilita")


@bp.route("/contabilita", methods=["GET", "POST"])
def prima_nota_paghe():
    per = periodi(g.ws.id)
    anno = request.values.get("anno", type=int) or (per[0][0] if per else date.today().year)
    mese = request.values.get("mese", type=int) or (per[0][1] if per else date.today().month)
    slips = buste_del_mese(g.ws.id, anno, mese)
    righe = prima_nota(slips)
    reg = ws_query(Contabilizzazione).filter_by(anno=anno, mese=mese).first()
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        if not righe:
            flash("Nessuna busta completata nel mese: niente da registrare.", "warning")
        elif reg:
            flash("Le paghe di questo mese sono già registrate in contabilità.", "warning")
        else:
            db.session.add(Contabilizzazione(workspace_id=g.ws.id, anno=anno, mese=mese,
                                             data=month_bounds(date(anno, mese, 1))[1], righe=json.dumps(righe)))
            db.session.commit()
            flash("Scrittura delle paghe registrata in contabilità generale.", "success")
        return redirect(url_for("contabilita.prima_nota_paghe", anno=anno, mese=mese))
    dare = round(sum(r["dare"] for r in righe), 2)
    avere = round(sum(r["avere"] for r in righe), 2)
    return render_template("contabilita/prima_nota.html", righe=righe, dare=dare, avere=avere, anno=anno, mese=mese,
                           reg=reg, n=len(slips), registrate=ws_query(Contabilizzazione).order_by(
                               Contabilizzazione.anno.desc(), Contabilizzazione.mese.desc()).all())
