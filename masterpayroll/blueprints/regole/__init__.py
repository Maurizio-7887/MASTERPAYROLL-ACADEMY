"""Blueprint «regole» — Strutture, categorie e regole stipendio.

Una cartella per attività: le pagine HTML sono in templates/regole/."""
from flask import abort, flash, g, redirect, render_template, request, url_for
from ... import payroll
from ...fiscale import HELPER_DOCS
from ...models import (ContributionRegister, Contract, PayrollStructure, Payslip, PayslipLine, RuleInput, SalaryRule,
                      SalaryRuleCategory, db)
from ..comune import (code_errors, f_bool, f_float, f_id, f_int, f_str, f_text, handle_user_error, ws_get,
                     ws_query)

from ..comune import area

bp = area("regole")

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


@bp.route("/structures")
def structures():
    rows = ws_query(PayrollStructure).order_by(PayrollStructure.code).all()
    return render_template("regole/structure_list.html", rows=rows)


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
            return redirect(url_for("regole.structure", st_id=n.id))
        if st and action == "delete":
            if Contract.query.filter_by(struct_id=st.id).first() or Payslip.query.filter_by(struct_id=st.id).first():
                raise payroll.UserError("La struttura è usata da contratti o buste paga.")
            db.session.delete(st)
            db.session.commit()
            flash("Struttura eliminata.", "success")
            return redirect(url_for("regole.structures"))
        if st and action == "remove_rule":
            rule = ws_get(SalaryRule, f_id("rule_id"))
            if rule in st.rule_ids:
                st.rule_ids.remove(rule)
            db.session.commit()
            return redirect(url_for("regole.structure", st_id=st.id))
        if st and action == "add_rules":
            for rid in request.form.getlist("rule_ids", type=int):
                rule = ws_get(SalaryRule, rid)
                if rule not in st.rule_ids:
                    st.rule_ids.append(rule)
            db.session.commit()
            return redirect(url_for("regole.structure", st_id=st.id))
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
        return redirect(url_for("regole.structure", st_id=st.id))
    others = [s for s in ws_query(PayrollStructure).all() if not st or s.id != st.id]
    all_rules = payroll.get_all_rules(st.get_structure_with_parents()) if st else []
    available = ws_query(SalaryRule).filter(SalaryRule.parent_rule_id.is_(None)).order_by(SalaryRule.sequence).all()
    return render_template("regole/structure_form.html", st=st, others=others, all_rules=all_rules, available=available)


@bp.route("/categories")
def categories():
    rows = ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code).all()
    return render_template("regole/category_list.html", rows=rows)


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
            return redirect(url_for("regole.categories"))
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
        return redirect(url_for("regole.category", cat_id=cat.id))
    others = [c for c in ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code) if not cat or c.id != cat.id]
    return render_template("regole/category_form.html", cat=cat, others=others)


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
    return render_template("regole/rule_list.html", rows=rows, q=s, tree=tree, cat_id=cat_id, st_id=st_id,
                           categories=ws_query(SalaryRuleCategory).order_by(SalaryRuleCategory.code).all(),
                           structures=ws_query(PayrollStructure).all(),
                           archiviate=request.args.get("archiviate"))


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
            return redirect(url_for("regole.rules"))
        if r and action == "copy":
            cols = [c.name for c in SalaryRule.__table__.columns if c.name not in ("id",)]
            n = SalaryRule(**{c: getattr(r, c) for c in cols})
            n.name = f"{r.name} (copia)"
            n.struct_ids = list(r.struct_ids)
            for ri in r.input_ids:
                n.input_ids.append(RuleInput(name=ri.name, code=ri.code))
            db.session.add(n)
            db.session.commit()
            return redirect(url_for("regole.rule", rule_id=n.id))
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
            return render_template("regole/rule_form.html", r=draft, real=r, cats=cats, regs=regs, structs=structs,
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
        return redirect(url_for("regole.rule", rule_id=r.id, tab=request.form.get("tab", "general")))
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
    return render_template("regole/rule_form.html", r=r, real=real, cats=cats, regs=regs, structs=structs,
                           parents=_parents(real), helpers=HELPER_DOCS, tab=request.args.get("tab", "general"),
                           sel_structs=sel)


def _parents(r):
    return [x for x in ws_query(SalaryRule).order_by(SalaryRule.sequence) if not r or x.id != r.id]
