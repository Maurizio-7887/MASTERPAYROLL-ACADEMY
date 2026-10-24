"""Blueprint «controllo» — Controllo del costo del personale: i numeri del controller sulle buste completate.

Pagine: cruscotto, reparti, assenze e straordinari, budget del personale, turnover e formazione, premio di risultato.
Una cartella per attività: le pagine HTML sono in templates/controllo/."""
import csv
import io
import json
from datetime import date

from flask import Response, flash, g, redirect, render_template, request, url_for

from ...controllo import (MESI_BREVI, PARAMETRI_DEFAULT, analisi, budget_da_consuntivo, confronto_budget,
                          periodi_disponibili, premio, tipi_assenza, turnover_formazione)
from ...models import ControlloPersonale, db
from ..comune import area, parse_float

bp = area("controllo")


def _periodo():
    per = periodi_disponibili(g.ws.id)
    anno = request.args.get("anno", type=int) or (per[0][0] if per else date.today().year)
    mesi_anno = sorted(m for a, m in per if a == anno)
    da = request.args.get("da", type=int) or (mesi_anno[0] if mesi_anno else 1)
    a = request.args.get("a", type=int) or (mesi_anno[-1] if mesi_anno else 12)
    da, a = max(1, min(12, da)), max(1, min(12, a))
    if da > a:
        da, a = a, da
    return anno, da, a, per


def _rec(anno, crea=False):
    r = ControlloPersonale.query.filter_by(workspace_id=g.ws.id, anno=anno).first()
    if r is None and crea:
        r = ControlloPersonale(workspace_id=g.ws.id, anno=anno, budget="{}", parametri="{}")
        db.session.add(r)
    return r


def _parametri(anno):
    r = _rec(anno)
    par = dict(PARAMETRI_DEFAULT)
    if r and r.parametri:
        par.update({k: v for k, v in json.loads(r.parametri).items() if k in PARAMETRI_DEFAULT})
    return par


def _budget(anno):
    r = _rec(anno)
    return json.loads(r.budget) if r and r.budget else {}


def _ctx(pagina):
    anno, da, a, per = _periodo()
    an = analisi(g.ws.id, anno, da, a)
    return {"pagina": pagina, "anno": anno, "da": da, "a": a, "per": per, "an": an, "t": an["totale"],
            "MESI_BREVI": MESI_BREVI, "par": _parametri(anno), "q": {"anno": anno, "da": da, "a": a},
            "anni": sorted({x for x, _ in per} | {anno}, reverse=True)}


@bp.route("/controllo")
def cruscotto():
    return render_template("controllo/cruscotto.html", **_ctx("cruscotto"))


@bp.route("/controllo/reparti")
def reparti():
    return render_template("controllo/reparti.html", **_ctx("reparti"))


@bp.route("/controllo/assenze")
def assenze():
    c = _ctx("assenze")
    codici = sorted({k for d in c["an"]["dipendenti"] for k in d["ass"]})
    return render_template("controllo/assenze.html", codici=codici, nomi=tipi_assenza(g.ws.id), **c)


@bp.route("/controllo/budget", methods=["GET", "POST"])
def budget():
    c = _ctx("budget")
    if request.method == "POST":
        rec = _rec(c["anno"], crea=True)
        if request.form.get("azione") == "proponi":
            rec.budget = json.dumps(budget_da_consuntivo(c["an"]))
            flash("Budget proposto dalla media del periodo: ora correggilo reparto per reparto.", "success")
        else:
            dati = {}
            for i in range(int(request.form.get("n", 0)) + 1):
                rep = (request.form.get(f"r{i}_reparto") or "").strip()
                if rep:
                    dati[rep[:80]] = {"fte": parse_float(request.form.get(f"r{i}_fte")),
                                      "ore_mese": parse_float(request.form.get(f"r{i}_ore")),
                                      "costo_mese": parse_float(request.form.get(f"r{i}_costo"))}
            rec.budget = json.dumps(dati)
            flash("Budget del personale salvato.", "success")
        db.session.commit()
        return redirect(url_for(".budget", **c["q"]))
    bud = _budget(c["anno"])
    righe, tot = confronto_budget(c["an"], bud)
    return render_template("controllo/budget.html", bud=bud, righe=righe, tot=tot, **c)


@bp.route("/controllo/turnover")
def turnover():
    c = _ctx("turnover")
    return render_template("controllo/turnover.html", tf=turnover_formazione(g.ws.id, c["anno"], c["an"], c["par"]), **c)


@bp.route("/controllo/premio")
def premio_risultato():
    c = _ctx("premio")
    righe, tot = premio(c["an"], c["par"])
    return render_template("controllo/premio.html", righe=righe, tot=tot, **c)


@bp.route("/controllo/parametri", methods=["POST"])
def parametri():
    anno = request.form.get("anno", type=int) or date.today().year
    rec = _rec(anno, crea=True)
    par = _parametri(anno)
    for k in PARAMETRI_DEFAULT:
        if k in request.form:
            par[k] = parse_float(request.form.get(k), PARAMETRI_DEFAULT[k])
    rec.parametri = json.dumps(par)
    db.session.commit()
    flash("Parametri aggiornati.", "success")
    torna = request.form.get("torna") or "cruscotto"
    return redirect(url_for(f".{torna}", anno=anno, da=request.form.get("da"), a=request.form.get("a")))


@bp.route("/controllo/export.csv")
def export_csv():
    c = _ctx("cruscotto")
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["matricola", "dipendente", "reparto", "fte", "lordo", "contributi_azienda", "tfr", "costo_aziendale",
                "ore_pagate", "ore_lavorate", "ore_straordinario", "costo_orario_pagato", "costo_orario_effettivo",
                "assenteismo_pct"])
    f = lambda x, d=2: ("" if x is None else f"{x:.{d}f}".replace(".", ","))  # noqa: E731
    for d in c["an"]["dipendenti"]:
        w.writerow([d["e"].registration_number, d["e"].name, d["reparto"], f(d["fte"]), f(d["lordo"]), f(d["oneri"]),
                    f(d["tfr"]), f(d["costo"]), f(d["ore_pagate"], 1), f(d["ore_lavorate"], 1), f(d["ore_str"], 1),
                    f(d["costo_orario_pagato"]), f(d["costo_orario_effettivo"]),
                    f(d["assenteismo"] * 100 if d["assenteismo"] is not None else None, 1)])
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=costo_personale_{c['anno']}_{c['da']:02d}-{c['a']:02d}.csv"})
