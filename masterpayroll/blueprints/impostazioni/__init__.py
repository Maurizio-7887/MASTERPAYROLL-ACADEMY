"""Blueprint «impostazioni» — Impostazioni e tabelle (parametri, scaglioni, livelli).

Una cartella per attività: le pagine HTML sono in templates/impostazioni/."""
from flask import flash, g, redirect, render_template, request, url_for
from ...models import (Contract, Livello, Parametro, ScaglioneIrpef, db)
from ..comune import (f_bool, f_float, f_str, ws_query)

from ..comune import area

bp = area("impostazioni")

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


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for f, _, _ in SETTINGS:
            setattr(g.ws, f, f_bool(f))
        db.session.commit()
        flash("Impostazioni salvate.", "success")
        return redirect(url_for("impostazioni.settings"))
    return render_template("impostazioni/settings.html", settings=SETTINGS)


@bp.route("/tabelle", methods=["GET", "POST"])
def tabelle():
    ws_id = g.ws.id
    if request.method == "POST":
        sez = request.form.get("sezione")
        if sez == "azienda":
            for campo in ("name", "vat", "street", "city", "email", "phone", "ccnl", "matricola_inps", "pat_inail"):
                setattr(g.ws, campo, f_str(campo))
        elif sez == "parametri":
            for p in ws_query(Parametro):
                if f_bool(f"del_{p.id}"):
                    db.session.delete(p)
                else:
                    p.valore = f_float(f"p_{p.id}", p.valore)
            cod = f_str("nuovo_codice").upper().replace(" ", "_")
            if cod:
                if not cod.replace("_", "").isalnum() or not cod[0].isalpha():
                    flash("Codice parametro non valido (lettere, numeri, _).", "danger")
                elif ws_query(Parametro).filter_by(codice=cod).first():
                    flash("Parametro già esistente.", "warning")
                else:
                    db.session.add(Parametro(workspace_id=ws_id, codice=cod, descrizione=f_str("nuovo_descr"),
                                             valore=f_float("nuovo_valore"), unita=f_str("nuovo_unita")))
        elif sez == "scaglioni":
            for s in ws_query(ScaglioneIrpef):
                if f_bool(f"del_{s.id}"):
                    db.session.delete(s)
                    continue
                s.da = f_float(f"da_{s.id}", s.da)
                s.a = f_float(f"a_{s.id}") if f_str(f"a_{s.id}") else None
                s.aliquota = f_float(f"al_{s.id}", s.aliquota)
            if f_str("nuovo_aliq"):
                db.session.add(ScaglioneIrpef(workspace_id=ws_id, da=f_float("nuovo_da"),
                                              a=f_float("nuovo_a") if f_str("nuovo_a") else None,
                                              aliquota=f_float("nuovo_aliq")))
        elif sez == "livelli":
            for lv in ws_query(Livello):
                lv.descrizione = f_str(f"ld_{lv.id}", lv.descrizione)
                lv.minimo = f_float(f"lm_{lv.id}", lv.minimo)
                lv.scatto_importo = f_float(f"ls_{lv.id}", lv.scatto_importo)
            if f_str("nuovo_livello"):
                db.session.add(Livello(workspace_id=ws_id, codice=f_str("nuovo_livello").upper(),
                                       descrizione=f_str("nuovo_livello_descr"),
                                       minimo=f_float("nuovo_livello_minimo"),
                                       scatto_importo=f_float("nuovo_livello_scatto")))
            if f_bool("aggiorna_contratti"):
                n = 0
                for c in ws_query(Contract).filter_by(state="open"):
                    if c.livello:
                        c.wage, c.scatto_importo = c.livello.minimo, c.livello.scatto_importo
                        n += 1
                flash(f"Rinnovo CCNL: aggiornati paga base e scatto su {n} contratti in corso.", "info")
        db.session.commit()
        flash("Tabelle aggiornate. Ricalcola le buste non confermate per applicarle.", "success")
        return redirect(url_for("impostazioni.tabelle") + f"#{sez}")
    return render_template("impostazioni/tabelle.html", parametri=ws_query(Parametro).order_by(Parametro.id).all(),
        scaglioni=ws_query(ScaglioneIrpef).order_by(ScaglioneIrpef.da).all(),
        livelli=ws_query(Livello).order_by(Livello.codice).all())
