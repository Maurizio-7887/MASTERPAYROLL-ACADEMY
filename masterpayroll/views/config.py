"""Configurazione: impostazioni, strutture, categorie, regole, registri, tabelle italiane."""
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for

from .. import payroll, reports
from ..fiscale import HELPER_DOCS
from ..models import (ContributionRegister, Contract, Livello, Parametro, Partner, PayrollStructure, Payslip,
                      PayslipLine, RuleInput, SalaryRule, SalaryRuleCategory, ScaglioneIrpef, db, month_bounds)
from .common import (author, bp, code_errors, f_bool, f_date, f_float, f_id, f_int, f_str, f_text,
                     handle_user_error, ws_get, ws_query)
from .payslips import _pdf_response


# ===========================================================================
# Impostazioni (res.config.settings)
# ===========================================================================
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


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for f, _, _ in SETTINGS:
            setattr(g.ws, f, f_bool(f))
        db.session.commit()
        flash("Impostazioni salvate.", "success")
        return redirect(url_for("main.settings"))
    return render_template("settings.html", settings=SETTINGS)


# ===========================================================================
# Strutture stipendio
# ===========================================================================
@bp.route("/structures")
def structures():
    rows = ws_query(PayrollStructure).order_by(PayrollStructure.code).all()
    return render_template("structure_list.html", rows=rows)


@bp.route("/structures/new", methods=["GET", "POST"])
@bp.route("/structures/<int:st_id>", methods=["GET", "POST"])
@handle_user_error
def structure(st_id=None):
    st = ws_get(PayrollStructure, st_id) if st_id else None
    if request.method == "POST":
        action = request.form.get("action", "save")
        if st and action == "copy":
            n = PayrollStructure(workspace_id=g.ws.id, name=st.name, code=f"{st.code} (copia)", note=st.note,
                                 parent_id=st.parent_id)
            n.rule_ids = list(st.rule_ids)
            db.session.add(n)
            db.session.commit()
            flash("Struttura duplicata.", "success")
            return redirect(url_for("main.structure", st_id=n.id))
        if st and action == "delete":
            if Contract.query.filter_by(struct_id=st.id).first() or Payslip.query.filter_by(struct_id=st.id).first():
                raise payroll.UserError("La struttura è usata da contratti o buste paga.")
            db.session.delete(st)
            db.session.commit()
            flash("Struttura eliminata.", "success")
            return redirect(url_for("main.structures"))
        if st and action == "remove_rule":
            rule = ws_get(SalaryRule, f_id("rule_id"))
            if rule in st.rule_ids:
                st.rule_ids.remove(rule)
            db.session.commit()
            return redirect(url_for("main.structure", st_id=st.id))
        if st and action == "add_rules":
            for rid in request.form.getlist("rule_ids", type=int):
                rule = ws_get(SalaryRule, rid)
                if rule not in st.rule_ids:
                    st.rule_ids.append(rule)
            db.session.commit()
            return redirect(url_for("main.structure", st_id=st.id))
        name, code = f_str("name"), f_str("code")
        if not name:
            raise payroll.UserError("Il nome è obbligatorio.")
        if g.ws.require_code_and_category and not code:
            raise payroll.UserError("Il codice della struttura è obbligatorio (vedi Impostazioni).")
        new = st is None
        if new:
            st = PayrollStructure(workspace_id=g.ws.id)
            db.session.add(st)
        st.name, st.code, st.note = name, code, f_text("note")
        pid = f_id("parent_id")
        st.parent = ws_get(PayrollStructure, pid) if pid else None
        db.session.flush()
        if payroll.has_cycle(st, "parent"):
            raise payroll.UserError("Non si può creare una struttura ricorsiva.")
        db.session.commit()
        flash("Struttura salvata.", "success")
        return redirect(url_for("main.structure", st_id=st.id))
    others = [s for s in ws_query(PayrollStructure).all() if not st or s.id != st.id]
    all_rules = payroll.get_all_rules(st.get_structure_with_parents()) if st else []
    available = ws_query(SalaryRule).filter(SalaryRule.parent_rule_id.is_(None)).order_by(SalaryRule.sequence).all()
    return render_template("structure_form.html", st=st, others=others, all_rules=all_rules, available=available)


# ===========================================================================
# Categorie regola stipendio
# ===========================================================================
@bp.route("/categories")
def categories():
    rows = ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code).all()
    return render_template("category_list.html", rows=rows)


@bp.route("/categories/new", methods=["GET", "POST"])
@bp.route("/categories/<int:cat_id>", methods=["GET", "POST"])
@handle_user_error
def category(cat_id=None):
    cat = ws_get(SalaryRuleCategory, cat_id) if cat_id else None
    if request.method == "POST":
        if cat and request.form.get("action") == "delete":
            if cat.salary_rules_ids or cat.children_ids:
                raise payroll.UserError("La categoria ha regole o categorie figlie.")
            db.session.delete(cat)
            db.session.commit()
            return redirect(url_for("main.categories"))
        name, code = f_str("name"), f_str("code").upper()
        if not name:
            raise payroll.UserError("Il nome è obbligatorio.")
        if g.ws.require_code_and_category and not code:
            raise payroll.UserError("Il codice della categoria è obbligatorio (vedi Impostazioni).")
        if cat is None:
            cat = SalaryRuleCategory(workspace_id=g.ws.id)
            db.session.add(cat)
        cat.name, cat.code, cat.note = name, code or None, f_text("note")
        pid = f_id("parent_id")
        cat.parent = ws_get(SalaryRuleCategory, pid) if pid else None
        db.session.flush()
        if payroll.has_cycle(cat, "parent"):
            raise payroll.UserError("Non si può creare una gerarchia ricorsiva di categorie.")
        db.session.commit()
        flash("Categoria salvata.", "success")
        return redirect(url_for("main.category", cat_id=cat.id))
    others = [c for c in ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code) if not cat or c.id != cat.id]
    return render_template("category_form.html", cat=cat, others=others)


# ===========================================================================
# Regole stipendio
# ===========================================================================
@bp.route("/rules")
def rules():
    q = ws_query(SalaryRule)
    if request.args.get("archiviate"):
        q = q.filter(SalaryRule.active.is_(False))
    else:
        q = q.filter(SalaryRule.active.is_(True))
    rows = q.order_by(SalaryRule.sequence, SalaryRule.id).all()
    s = (request.args.get("q") or "").strip().lower()
    if s:
        rows = [r for r in rows if s in (r.code or "").lower() or s in r.name.lower()]
    cat_id = request.args.get("category_id", type=int)
    if cat_id:
        rows = [r for r in rows if r.category_id == cat_id]
    st_id = request.args.get("struct_id", type=int)
    if st_id:
        rows = [r for r in rows if any(x.id == st_id for x in r.struct_ids)]
    tree = request.args.get("vista") == "albero"
    if tree:
        rows = [r for r in rows if not r.parent_rule_id]
    return render_template("rule_list.html", rows=rows, q=s, tree=tree, cat_id=cat_id, st_id=st_id,
                           categories=ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code).all(),
                           structures=ws_query(PayrollStructure).all(),
                           archiviate=request.args.get("archiviate"))


DEFAULT_PY_CONDITION = """# Variabili disponibili: vedi il tab Aiuto
# result = worked_days.WORK100 and worked_days.WORK100.number_of_days > 0
result = True"""
DEFAULT_PY_COMPUTE = """# Variabili disponibili: vedi il tab Aiuto
# result: importo; result_qty: quantità; result_rate: tasso %; result_name: nome della riga
result = contract.wage * 0.10"""


@bp.route("/rules/new", methods=["GET", "POST"])
@bp.route("/rules/<int:rule_id>", methods=["GET", "POST"])
@handle_user_error
def rule(rule_id=None):
    r = ws_get(SalaryRule, rule_id) if rule_id else None
    cats = ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code).all()
    regs = ws_query(ContributionRegister).order_by(ContributionRegister.name).all()
    structs = ws_query(PayrollStructure).order_by(PayrollStructure.code).all()
    if request.method == "POST":
        action = request.form.get("action", "save")
        if r and action == "delete":
            if PayslipLine.query.filter_by(salary_rule_id=r.id).first():
                raise payroll.UserError("La regola è già usata in buste paga: archiviala (togli 'Attivo').")
            for ch in list(r.child_ids):
                ch.parent_rule = None
            db.session.delete(r)
            db.session.commit()
            flash("Regola eliminata.", "success")
            return redirect(url_for("main.rules"))
        if r and action == "copy":
            cols = [c.name for c in SalaryRule.__table__.columns if c.name not in ("id",)]
            n = SalaryRule(**{c: getattr(r, c) for c in cols})
            n.name = f"{r.name} (copia)"
            n.struct_ids = list(r.struct_ids)
            for ri in r.input_ids:
                n.input_ids.append(RuleInput(name=ri.name, code=ri.code))
            db.session.add(n)
            db.session.commit()
            return redirect(url_for("main.rule", rule_id=n.id))
        vals = dict(
            name=f_str("name"), code=f_str("code") or None, sequence=f_int("sequence", 5),
            quantity=f_text("quantity") or "1.0", active=f_bool("active"),
            appears_on_payslip=f_bool("appears_on_payslip"),
            condition_select=request.form.get("condition_select", "none"),
            condition_range=f_text("condition_range"), condition_python=f_text("condition_python"),
            condition_range_min=f_float("condition_range_min"), condition_range_max=f_float("condition_range_max"),
            amount_select=request.form.get("amount_select", "fix"), amount_fix=f_float("amount_fix"),
            amount_percentage=f_float("amount_percentage"), amount_python_compute=f_text("amount_python_compute"),
            amount_percentage_base=f_text("amount_percentage_base"), note=f_text("note"),
        )
        if vals["condition_select"] not in ("none", "range", "python") or \
                vals["amount_select"] not in ("fix", "percentage", "code"):
            abort(400)
        errs = []
        if not vals["name"]:
            errs.append("Il nome è obbligatorio.")
        cat_id, reg_id, parent_id = f_id("category_id"), f_id("register_id"), f_id("parent_rule_id")
        if g.ws.require_code_and_category and (not vals["code"] or not cat_id):
            errs.append("Codice e categoria sono obbligatori (vedi Impostazioni).")
        errs += code_errors([
            ("Quantità", vals["quantity"], "eval"),
            ("Intervallo basato su", vals["condition_range"] if vals["condition_select"] == "range" else "", "eval"),
            ("Condizione Python", vals["condition_python"] if vals["condition_select"] == "python" else "", "exec"),
            ("Percentuale basata su",
             vals["amount_percentage_base"] if vals["amount_select"] == "percentage" else "", "eval"),
            ("Codice Python", vals["amount_python_compute"] if vals["amount_select"] == "code" else "", "exec"),
        ])
        if vals["condition_select"] == "python" and not vals["condition_python"].strip():
            errs.append("La condizione Python è obbligatoria.")
        if vals["amount_select"] == "percentage" and not vals["amount_percentage_base"].strip():
            errs.append("Indica su cosa si calcola la percentuale.")
        if vals["amount_select"] == "code" and not vals["amount_python_compute"].strip():
            errs.append("Scrivi il codice Python dell'importo.")
        if errs:
            for e in errs:
                flash(e, "danger")
            draft = SalaryRule(**vals)
            draft.id = r.id if r else None
            draft.category_id, draft.register_id, draft.parent_rule_id = cat_id, reg_id, parent_id
            return render_template("rule_form.html", r=draft, real=r, cats=cats, regs=regs, structs=structs,
                                   parents=_parents(r), helpers=HELPER_DOCS, tab=request.form.get("tab", "general"),
                                   sel_structs=request.form.getlist("struct_ids", type=int))
        new = r is None
        if new:
            r = SalaryRule(workspace_id=g.ws.id)
            db.session.add(r)
        for k, v in vals.items():
            setattr(r, k, v)
        r.category = ws_get(SalaryRuleCategory, cat_id) if cat_id else None
        r.register = ws_get(ContributionRegister, reg_id) if reg_id else None
        r.parent_rule = ws_get(SalaryRule, parent_id) if parent_id else None
        if "struct_ids_present" in request.form:
            r.struct_ids = [ws_get(PayrollStructure, i) for i in request.form.getlist("struct_ids", type=int)]
        # apporti (hr.rule.input)
        for ri in list(r.input_ids):
            if f_bool(f"ri_del_{ri.id}"):
                r.input_ids.remove(ri)
            elif f"ri_code_{ri.id}" in request.form:
                ri.code = f_str(f"ri_code_{ri.id}").upper() or ri.code
                ri.name = f_str(f"ri_name_{ri.id}") or ri.name
        if f_str("ri_new_code"):
            r.input_ids.append(RuleInput(code=f_str("ri_new_code").upper(),
                                         name=f_str("ri_new_name") or f_str("ri_new_code")))
        db.session.flush()
        if payroll.has_cycle(r, "parent_rule"):
            raise payroll.UserError("Non si può creare una gerarchia ricorsiva di regole.")
        db.session.commit()
        flash(f"Regola {r.code or r.name} salvata. Ricalcola le buste per vederne l'effetto.", "success")
        return redirect(url_for("main.rule", rule_id=r.id, tab=request.form.get("tab", "general")))
    if r is None:
        r = SalaryRule(sequence=5, quantity="1.0", active=True, appears_on_payslip=True, condition_select="none",
                       condition_range="contract.wage", condition_python=DEFAULT_PY_CONDITION, amount_select="fix",
                       amount_python_compute=DEFAULT_PY_COMPUTE)
        pid = request.args.get("parent", type=int)
        if pid:
            parent = ws_get(SalaryRule, pid)
            r.parent_rule_id = parent.id
            r.category_id = parent.category_id
            r.sequence = parent.sequence + 1
        real = None
        sel = [request.args.get("struct", type=int)] if request.args.get("struct") else []
    else:
        real = r
        sel = [s.id for s in r.struct_ids]
        if not r.condition_python:
            r.condition_python = DEFAULT_PY_CONDITION
        if not r.amount_python_compute:
            r.amount_python_compute = DEFAULT_PY_COMPUTE
    return render_template("rule_form.html", r=r, real=real, cats=cats, regs=regs, structs=structs,
                           parents=_parents(real), helpers=HELPER_DOCS, tab=request.args.get("tab", "general"),
                           sel_structs=sel)


def _parents(r):
    return [x for x in ws_query(SalaryRule).order_by(SalaryRule.sequence) if not r or x.id != r.id]


# ===========================================================================
# Registri contributi + report "Righe busta paga per registro contributi"
# ===========================================================================
@bp.route("/registers")
def registers():
    rows = ws_query(ContributionRegister).order_by(ContributionRegister.name).all()
    d1, d2 = month_bounds(date.today().replace(day=1))
    return render_template("register_list.html", rows=rows, d1=d1, d2=d2)


@bp.route("/registers/new", methods=["GET", "POST"])
@bp.route("/registers/<int:reg_id>", methods=["GET", "POST"])
@handle_user_error
def register(reg_id=None):
    reg = ws_get(ContributionRegister, reg_id) if reg_id else None
    if request.method == "POST":
        if reg and request.form.get("action") == "delete":
            db.session.delete(reg)
            db.session.commit()
            return redirect(url_for("main.registers"))
        if not f_str("name"):
            raise payroll.UserError("Il nome è obbligatorio.")
        if reg is None:
            reg = ContributionRegister(workspace_id=g.ws.id)
            db.session.add(reg)
        reg.name, reg.note = f_str("name"), f_text("note")
        pname = f_str("partner_name")
        if pname:
            p = ws_query(Partner).filter_by(name=pname).first()
            if not p:
                p = Partner(workspace_id=g.ws.id, name=pname)
                db.session.add(p)
            reg.partner = p
        else:
            reg.partner = None
        reg.f24_sezione = request.form.get("f24_sezione", "")
        reg.f24_codice = f_str("f24_codice")
        reg.f24_tipo = request.form.get("f24_tipo", "debito")
        db.session.commit()
        flash("Registro salvato.", "success")
        return redirect(url_for("main.register", reg_id=reg.id))
    lines = []
    if reg:
        lines = (db.session.query(PayslipLine).join(Payslip, PayslipLine.slip_id == Payslip.id)
                 .filter(PayslipLine.register_id == reg.id, Payslip.state == "done")
                 .order_by(Payslip.date_from.desc(), PayslipLine.slip_id, PayslipLine.sequence).limit(300).all())
    partners = ws_query(Partner).order_by(Partner.name).all()
    return render_template("register_form.html", reg=reg, lines=lines, partners=partners)


@bp.route("/registers/report", methods=["GET", "POST"])
def register_report():
    """Wizard payslip.lines.contribution.register + report PDF."""
    if request.method == "POST":
        ids = request.form.getlist("ids", type=int)
        regs = [ws_get(ContributionRegister, i) for i in ids]
        d1, d2 = f_date("date_from"), f_date("date_to")
        if not regs or not d1 or not d2:
            flash("Seleziona i registri e il periodo.", "warning")
            return redirect(url_for("main.registers"))
        return _pdf_response(reports.contribution_register_pdf(g.ws, regs, d1, d2), "registro_contributi.pdf")
    return redirect(url_for("main.registers"))


# ===========================================================================
# Tabelle della localizzazione italiana
# ===========================================================================
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
        return redirect(url_for("main.tabelle") + f"#{sez}")
    return render_template(
        "tabelle.html", parametri=ws_query(Parametro).order_by(Parametro.id).all(),
        scaglioni=ws_query(ScaglioneIrpef).order_by(ScaglioneIrpef.da).all(),
        livelli=ws_query(Livello).order_by(Livello.codice).all())


@bp.route("/guida")
def guida():
    cats = ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code).all()
    params = ws_query(Parametro).order_by(Parametro.id).all()
    return render_template("guida.html", helpers=HELPER_DOCS, cats=cats, params=params)


__all__ = ["author"]
