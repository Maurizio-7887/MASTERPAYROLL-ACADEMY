"""Blueprint «f24» — Versamenti F24 dai registri contributi.

Una cartella per attività: le pagine HTML sono in templates/f24/."""
from collections import defaultdict
from datetime import date
from flask import Response, render_template, request
from ...models import (ContributionRegister, Payslip, month_bounds)
from ..comune import ws_query

from ..comune import area

bp = area("f24")

STATE_FILTERS = [("draft", "Bozza"), ("verify", "Revisione in attesa"), ("done", "Completata"),
                 ("cancel", "Rifiutata")]

def _pdf_response(data, filename):
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@bp.route("/f24")
def f24():
    periodi = sorted({(s.date_from.year, s.date_from.month) for s in ws_query(Payslip).filter_by(state="done")},
                     reverse=True)
    anno = request.args.get("anno", type=int) or (periodi[0][0] if periodi else date.today().year)
    mese = request.args.get("mese", type=int) or (periodi[0][1] if periodi else date.today().month)
    d1, d2 = month_bounds(date(anno, mese, 1))
    slips = (ws_query(Payslip).filter(Payslip.state == "done", Payslip.date_from >= d1, Payslip.date_to <= d2)
             .all())
    per_reg = defaultdict(float)
    for s in slips:
        sign = -1 if s.credit_note else 1
        for ln in s.line_ids:
            if ln.register_id:   # trattenute negative e contributi azienda positivi sono entrambi debiti: si somma il valore
                per_reg[ln.register_id] += sign * abs(ln.total)
    regs = {r.id: r for r in ws_query(ContributionRegister)}
    erario_debito, erario_credito, altri = [], [], []
    inps = inail = inps_credito = 0.0
    for rid, tot in per_reg.items():
        r = regs.get(rid)
        if not r:
            continue
        imp = abs(tot)
        if r.f24_sezione == "erario":
            (erario_credito if r.f24_tipo == "credito" else erario_debito).append((r, imp))
        elif r.f24_sezione == "inps":
            if r.f24_tipo == "credito":
                inps_credito += imp   # indennità anticipate per conto dell'INPS: si recuperano nel DM10
            else:
                inps += imp
        elif r.f24_sezione == "inail":
            inail += imp
        else:
            altri.append((r, imp))
    tot_deb = sum(i for _, i in erario_debito)
    tot_cred = sum(i for _, i in erario_credito)
    scad = date(anno + (mese == 12), mese % 12 + 1, 16)
    riep = []
    for s in sorted(slips, key=lambda s: (s.employee.name, s.id)):
        riep.append(s)
    return render_template("f24/f24.html", anno=anno, mese=mese, periodi=periodi, erario_debito=erario_debito,
                           erario_credito=erario_credito, inps=inps, inail=inail, altri=altri, tot_deb=tot_deb,
                           tot_cred=tot_cred, saldo=tot_deb - tot_cred + inps - inps_credito, scadenza=scad, slips=riep,
                           inps_credito=inps_credito)
