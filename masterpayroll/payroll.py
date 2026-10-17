"""Motore paghe: porting di payroll/models/hr_payslip.py, hr_salary_rule.py,
hr_payroll_structure.py, hr_payslip_run.py e dei wizard.

I nomi delle funzioni sono quelli dei metodi Odoo, così chi legge il codice
ritrova la stessa logica:

    compute_sheet(slip)              -> hr.payslip.compute_sheet
    get_lines_dict(slip)             -> hr.payslip.get_lines_dict
    satisfy_condition(rule, ld)      -> hr.salary.rule._satisfy_condition
    compute_rule(rule, ld)           -> hr.salary.rule._compute_rule
    ...
"""
import calendar as _cal
import math
from datetime import date

from . import fiscale
from .browsable import (BaseBrowsableObject, BrowsableObject, InputLine, Payslips, WorkedDays, wrap)
from .hr_service import list_leaves, work_days_data
from .models import (Contract, Message, Parametro, Payslip, PayslipInput, PayslipLine, PayslipWorkedDays,
                     SalaryRule, ScaglioneIrpef, db, now)
from .safe_eval import SafeEvalError, safe_eval

MESI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre"]
STATE_LABEL = {"draft": "Bozza", "verify": "In attesa", "done": "Completata", "cancel": "Rifiutata"}


class UserError(Exception):
    """Come odoo.exceptions.UserError / ValidationError: messaggio per l'utente."""


# ===========================================================================
# Chatter (mail.thread)
# ===========================================================================
def log_message(ws_id, model, res_id, body="", tracking=None, author="", message_type="notification"):
    db.session.add(Message(workspace_id=ws_id, model=model, res_id=res_id, body=body, author=author,
                           tracking="\n".join(tracking or []), message_type=message_type))


def track_payslip(slip, old, author=""):
    """Campi con tracking=True in hr.payslip: date_from, date_to, state, note, contract_id, payslip_run_id."""
    changes = []
    labels = {"date_from": "Dalla data", "date_to": "Alla data", "state": "Stato", "note": "Nota interna",
              "contract_id": "Contratto", "payslip_run_id": "Gruppo buste paga"}
    for f, label in labels.items():
        before, after = old.get(f), getattr(slip, f)
        if before != after:
            if f == "state":
                before, after = STATE_LABEL.get(before, before), STATE_LABEL.get(after, after)
            elif f == "contract_id":
                before = _contract_name(before)
                after = slip.contract.name if slip.contract else ""
            elif f == "payslip_run_id":
                before = _run_name(before)
                after = slip.payslip_run.name if slip.payslip_run else ""
            elif isinstance(after, date) or isinstance(before, date):
                before = before.strftime("%d/%m/%Y") if before else ""
                after = after.strftime("%d/%m/%Y") if after else ""
            changes.append(f"{label}: {before or '—'} → {after or '—'}")
    if changes:
        log_message(slip.workspace_id, "hr.payslip", slip.id, tracking=changes, author=author)


def snapshot(slip):
    return {f: getattr(slip, f) for f in ("date_from", "date_to", "state", "note", "contract_id",
                                         "payslip_run_id")}


def _contract_name(cid):
    c = db.session.get(Contract, cid) if cid else None
    return c.name if c else ""


def _run_name(rid):
    from .models import PayslipRun
    r = db.session.get(PayslipRun, rid) if rid else None
    return r.name if r else ""


# ===========================================================================
# hr.payroll.structure / hr.salary.rule
# ===========================================================================
def recursive_search_of_rules(rules):
    """Regole + tutte le figlie (ricorsivo), senza duplicati."""
    out, seen = [], set()

    def visit(rule):
        for child in rule.child_ids:
            visit(child)
        if rule.id not in seen:
            seen.add(rule.id)
            out.append(rule)
    for r in rules:
        visit(r)
    return out


def get_all_rules(structures):
    rules, seen = [], set()
    for s in structures:
        for r in s.rule_ids:
            if r.id not in seen:
                seen.add(r.id)
                rules.append(r)
    allr = recursive_search_of_rules(rules)
    allr = [r for r in allr if r.active]
    return sorted(allr, key=lambda r: (r.sequence, r.id))


def has_cycle(obj, attr):
    seen, cur = set(), obj
    while cur is not None:
        if cur.id in seen:
            return True
        seen.add(cur.id)
        cur = getattr(cur, attr)
    return False


def _rule_error(kind, rule, localdict, err):
    emp = localdict.get("employee")
    ee = emp.name if emp else ""
    return UserError(f"{kind} per la regola {rule.name} ({rule.code}) del dipendente {ee}.\n"
                     f"Errore ricevuto: {err}")


def reset_localdict_values(localdict):
    localdict["result_name"] = None
    localdict["result_qty"] = 1.0
    localdict["result_rate"] = 100
    localdict["result"] = None
    return localdict


def satisfy_condition(rule, localdict):
    check = {"none": _cond_none, "range": _cond_range, "python": _cond_python}[rule.condition_select or "none"]
    if rule.parent_rule:
        return check(rule, localdict) and satisfy_condition(rule.parent_rule, localdict)
    return check(rule, localdict)


def _cond_none(rule, localdict):
    return True


def _cond_range(rule, localdict):
    try:
        result = safe_eval(rule.condition_range, localdict)
        return (rule.condition_range_min or 0) <= result <= (rule.condition_range_max or 0) or False
    except (SafeEvalError, TypeError) as ex:
        raise _rule_error("Condizione a intervallo errata", rule, localdict, ex) from None


def _cond_python(rule, localdict):
    try:
        safe_eval(rule.condition_python or "", localdict, mode="exec")
    except SafeEvalError as ex:
        raise _rule_error("Condizione Python errata", rule, localdict, ex) from None
    return "result" in localdict and localdict["result"] or False


def compute_rule(rule, localdict):
    return {"fix": _amount_fix, "percentage": _amount_percentage, "code": _amount_code}[rule.amount_select](
        rule, localdict)


def _amount_fix(rule, localdict):
    try:
        return {"name": rule.name, "quantity": float(safe_eval(rule.quantity or "1.0", localdict)),
                "rate": 100.0, "amount": rule.amount_fix or 0.0}
    except (SafeEvalError, TypeError, ValueError) as ex:
        raise _rule_error("Quantità errata", rule, localdict, ex) from None


def _amount_percentage(rule, localdict):
    try:
        return {"name": rule.name, "quantity": float(safe_eval(rule.quantity or "1.0", localdict)),
                "rate": rule.amount_percentage or 0.0,
                "amount": float(safe_eval(rule.amount_percentage_base or "0", localdict))}
    except (SafeEvalError, TypeError, ValueError) as ex:
        raise _rule_error("Base percentuale o quantità errata", rule, localdict, ex) from None


def _amount_code(rule, localdict):
    try:
        safe_eval(rule.amount_python_compute or "", localdict, mode="exec")
        name = localdict.get("result_name") or rule.name
        quantity = float(localdict["result_qty"]) if "result_qty" in localdict else 1.0
        rate = float(localdict["result_rate"]) if "result_rate" in localdict else 100.0
        if localdict.get("result") is None:
            raise SafeEvalError("il codice non assegna un valore a 'result'")
        return {"name": name, "quantity": quantity, "rate": rate, "amount": float(localdict["result"])}
    except (SafeEvalError, TypeError, ValueError) as ex:
        raise _rule_error("Codice Python errato", rule, localdict, ex) from None


# ===========================================================================
# hr.payslip
# ===========================================================================
def get_employee_contracts(slip):
    """Contratti validi nel periodo (quello indicato o tutti quelli del dipendente)."""
    if slip.contract_id:
        c = slip.contract
        return [c] if c and c.is_overlapping_period(slip.date_from, slip.date_to) else []
    return get_contracts(slip.employee, slip.date_from, slip.date_to)


def get_contracts(employee, date_from, date_to):
    return [c for c in employee.contract_ids
            if c.state in ("open", "close") and c.is_overlapping_period(date_from, date_to)]


def get_salary_rules(slip):
    return salary_rules_for(slip.struct, get_employee_contracts(slip))


def salary_rules_for(struct, contracts):
    """Odoo _get_salary_rules: struttura della busta (o dei contratti) + padri, regole ordinate."""
    if not contracts:
        return []
    if struct:
        structures = struct.get_structure_with_parents()
    else:
        structures, seen = [], set()
        for c in contracts:
            if c.struct:
                for s in c.struct.get_structure_with_parents():
                    if s.id not in seen:
                        seen.add(s.id)
                        structures.append(s)
    return get_all_rules(structures)


def get_worked_day_lines(slip, contracts, date_from, date_to):
    return worked_day_lines_for(slip_workspace(slip), contracts, date_from, date_to)


def worked_day_lines_for(ws, contracts, date_from, date_to):
    from .hr_service import day_work_hours
    res = []
    for contract in contracts:
        calendar = contract.resource_calendar or contract.employee.resource_calendar
        if not calendar:
            continue
        day_from = max(date_from, contract.date_start)
        day_to = min(date_to, contract.date_end) if contract.date_end else date_to
        if day_from > day_to:
            continue
        # == assenze == #
        leaves = {}
        sign = 1 if ws.leaves_positive else -1
        for day, hours, ltype in list_leaves(contract.employee, calendar, day_from, day_to):
            key = ltype.id if ltype else "GLOBAL"
            cur = leaves.setdefault(key, {
                "name": ltype.name if ltype else "Festività (Global Leaves)",
                "sequence": ltype.sequence if ltype else 5,
                "code": ltype.code if ltype else "GLOBAL",
                "number_of_days": 0.0, "number_of_hours": 0.0, "contract_id": contract.id})
            cur["number_of_hours"] += sign * hours
            wh = day_work_hours(calendar, day)
            if wh:
                cur["number_of_days"] += sign * hours / wh
        res.extend(leaves.values())
        # == giorni lavorati == #
        data = work_days_data(calendar, day_from, day_to)
        res.append({"name": "Giorni lavorativi regolari pagati al 100%", "sequence": 1, "code": "WORK100",
                    "number_of_days": data["days"], "number_of_hours": data["hours"],
                    "contract_id": contract.id})
    for r in res:
        r["number_of_days"] = round(r["number_of_days"], 2)
        r["number_of_hours"] = round(r["number_of_hours"], 2)
    return res


def get_inputs(slip, contracts):
    return inputs_for(slip.struct, contracts)


def inputs_for(struct, contracts):
    res = []
    rule_inputs = []
    for rule in salary_rules_for(struct, contracts):
        rule_inputs.extend(rule.input_ids)
    for contract in contracts:
        for ri in rule_inputs:
            res.append({"name": ri.name, "code": ri.code, "contract_id": contract.id})
    return res


def slip_workspace(slip):
    from .models import Workspace
    return db.session.get(Workspace, slip.workspace_id)


def get_payroll_dict(slip, contracts):
    """Valori disponibili nelle regole come ``payroll.xxx`` (punto di estensione di Odoo).

    La localizzazione italiana aggiunge i parametri della pagina Tabelle e alcuni
    valori pronti (ratei di tredicesima, reddito annuo dei 12 mesi).
    """
    res = {"contracts": BaseBrowsableObject({"count": len(contracts)})}
    for p in Parametro.query.filter_by(workspace_id=slip.workspace_id):
        res[p.codice] = p.valore
    contract = contracts[0] if contracts else None
    if contract:
        res["ratei_13"] = ratei_tredicesima(contract, slip.date_to)
        inps = SalaryRule.query.filter_by(workspace_id=slip.workspace_id, code="INPS_DIP").first()
        aliq = abs(inps.amount_percentage) if inps and inps.amount_select == "percentage" else 9.19
        res["reddito_ordinario_annuo"] = round(contract.retribuzione_mensile * 12 * (1 - aliq / 100), 2)
        # malattia: giorni dell'evento per fascia e indennità a carico INPS anticipata in busta
        from .hr_service import malattia_periodo
        mal = malattia_periodo(slip.employee, contract, slip.date_from, slip.date_to,
                               res.get("MAL_INPS_PERC1", 50.0), res.get("MAL_INPS_PERC2", 66.67))
        res.update({"mal_carenza": mal["carenza"], "mal_gg50": mal["gg50"], "mal_gg67": mal["gg67"],
                    "mal_rmg": mal["rmg"], "mal_inps": mal["importo"]})
        # conguaglio di fine anno (dicembre) e di fine rapporto (busta di liquidazione IT_CESS)
        res["cessazione"] = bool(slip.struct and slip.struct.code == "IT_CESS")
        res.update(dati_conguaglio(slip, contract))
    return res


def dati_conguaglio(slip, contract):
    """Progressivi dell'anno per il conguaglio: imponibile fiscale e IRPEF già trattenuta nelle buste
    completate (esclusa questa) più i progressivi caricati dal gestionale precedente; giorni di lavoro."""
    from .models import ProgressivoAnnuo
    anno = slip.date_to.year
    d1, d2 = date(anno, 1, 1), date(anno, 12, 31)
    imp = irpef = cuneo = 0.0
    q = Payslip.query.filter(Payslip.workspace_id == slip.workspace_id, Payslip.employee_id == slip.employee_id,
                             Payslip.state == "done", Payslip.date_from >= d1, Payslip.date_to <= d2,
                             Payslip.id != (slip.id or 0))
    for s in q:
        sg = -1 if s.credit_note else 1
        for ln in s.line_ids:
            if ln.code == "IMP_FISC":
                imp += sg * ln.total
            elif ln.code in ("IRPEF", "IRPEF13", "IRPEF_CESS", "CONG_IRPEF"):
                irpef -= sg * ln.total
            elif ln.code in ("IND_CUNEO", "CONG_CUNEO"):
                cuneo += sg * ln.total
    for p in ProgressivoAnnuo.query.filter_by(workspace_id=slip.workspace_id, employee_id=slip.employee_id, anno=anno):
        imp += p.imponibile_fiscale or 0
        irpef += p.irpef_trattenuta or 0
        cuneo += p.cuneo_indennita or 0
    inizio = min((c.date_start for c in slip.employee.contract_ids if c.state in ("open", "close")
                  and (c.date_end is None or c.date_end >= d1)), default=contract.date_start)
    fine = contract.date_end if contract.date_end and contract.date_end < d2 else d2
    giorni = max(0, (fine - max(inizio, d1)).days + 1)
    return {"cong_imponibile": round(imp, 2), "cong_irpef": round(irpef, 2), "cong_cuneo": round(cuneo, 2),
            "cong_giorni": min(365, giorni)}


def ratei_tredicesima(contract, ref_date):
    """Mesi maturati nell'anno: conta il mese se lavorato per almeno 15 giorni."""
    year = ref_date.year
    n = 0
    for m in range(1, ref_date.month + 1):
        last = _cal.monthrange(year, m)[1]
        start = max(date(year, m, 1), contract.date_start)
        end = min(date(year, m, last), contract.date_end or date(year, m, last))
        if end >= start and (end - start).days + 1 >= 15:
            n += 1
    return n


def get_current_contract_dict(slip, contract, contracts):
    return {}


def get_tools_dict(slip):
    """Strumenti per le regole (``tools.xxx``): math + funzioni fiscali italiane."""
    scaglioni = [(s.da, s.a, s.aliquota) for s in
                 ScaglioneIrpef.query.filter_by(workspace_id=slip.workspace_id).order_by(ScaglioneIrpef.da)]
    tools = {"math": BaseBrowsableObject({k: getattr(math, k) for k in (
        "floor", "ceil", "sqrt", "fabs", "trunc", "isclose", "pi", "e", "log", "log10", "exp")})}
    tools.update(fiscale.make_helpers(scaglioni or None, slip.date_to))
    return tools


def get_baselocaldict(slip, contracts):
    ws = slip.workspace_id
    worked_days = {ln.code: wrap(ln) for ln in slip.worked_days_line_ids if ln.code}
    inputs = {ln.code: wrap(ln) for ln in slip.input_line_ids if ln.code}
    return {
        "payslips": Payslips(slip.employee_id, {}, ws),
        "worked_days": WorkedDays(slip.employee_id, worked_days, ws),
        "inputs": InputLine(slip.employee_id, inputs, ws),
        "payroll": BrowsableObject(slip.employee_id, get_payroll_dict(slip, contracts), ws),
        "current_contract": BrowsableObject(slip.employee_id, {}, ws),
        "categories": BrowsableObject(slip.employee_id, {}, ws),
        "rules": BrowsableObject(slip.employee_id, {}, ws),
        "result_rules": BrowsableObject(slip.employee_id, {}, ws),
        "tools": BrowsableObject(slip.employee_id, get_tools_dict(slip), ws),
    }


def sum_salary_rule_category(localdict, category, amount):
    if category is None:
        return localdict
    if category.parent:
        localdict = sum_salary_rule_category(localdict, category.parent, amount)
    if category.code:
        d = localdict["categories"].dict
        d[category.code] = d.get(category.code, 0) + amount
    return localdict


def compute_payslip_line(slip, rule, localdict, lines_dict, contract):
    previous_amount = rule.code in localdict and localdict[rule.code] or 0.0
    values = compute_rule(rule, localdict)
    key = (rule.code or f"id{rule.id}") + "-" + str(contract.id)
    total = values["quantity"] * values["rate"] * values["amount"] / 100.0
    values["total"] = total
    if rule.code:
        localdict[rule.code] = total
        localdict["rules"].dict[rule.code] = wrap(rule)
        localdict["result_rules"].dict[rule.code] = BaseBrowsableObject(values)
    localdict = sum_salary_rule_category(localdict, rule.category, total - previous_amount)
    line = {
        "salary_rule_id": rule.id, "employee_id": slip.employee_id, "contract_id": contract.id,
        "code": rule.code, "category_id": rule.category_id, "sequence": rule.sequence,
        "appears_on_payslip": rule.appears_on_payslip, "parent_rule_id": rule.parent_rule_id,
        "condition_select": rule.condition_select, "condition_python": rule.condition_python,
        "condition_range": rule.condition_range, "condition_range_min": rule.condition_range_min,
        "condition_range_max": rule.condition_range_max, "amount_select": rule.amount_select,
        "amount_fix": rule.amount_fix, "amount_python_compute": rule.amount_python_compute,
        "amount_percentage": rule.amount_percentage, "amount_percentage_base": rule.amount_percentage_base,
        "register_id": rule.register_id,
    }
    line.update(values)
    lines_dict[key] = line
    return localdict, lines_dict


def get_lines_dict(slip):
    lines_dict = {}
    blacklist = set()
    contracts = get_employee_contracts(slip)
    baselocaldict = get_baselocaldict(slip, contracts)
    rules = get_salary_rules(slip)
    for contract in contracts:
        baselocaldict["current_contract"] = BrowsableObject(
            slip.employee_id, get_current_contract_dict(slip, contract, contracts), slip.workspace_id)
        localdict = dict(baselocaldict, employee=wrap(contract.employee), contract=wrap(contract),
                         payslip=wrap(slip))
        for rule in rules:
            localdict = reset_localdict_values(localdict)
            if rule.id not in blacklist and satisfy_condition(rule, localdict):
                localdict, lines_dict = compute_payslip_line(slip, rule, localdict, lines_dict, contract)
            else:
                blacklist.update(r.id for r in recursive_search_of_rules([rule]))
        baselocaldict["current_contract"] = {}
    return lines_dict


def compute_sheet(slip, author=""):
    """Cancella le righe, ricalcola, assegna il numero, stato 'In attesa'."""
    old = snapshot(slip)
    lines = get_lines_dict(slip)  # se una regola fallisce solleva UserError e non tocca nulla
    slip.line_ids.clear()  # delete-orphan: le righe vecchie vengono cancellate
    db.session.flush()
    ws = slip_workspace(slip)
    if not slip.number:
        slip.number = ws.next_slip_number()
    for vals in lines.values():
        pl = PayslipLine(**{k: v for k, v in vals.items() if k != "total"})
        pl.name = vals["name"]
        pl.quantity = round(vals["quantity"], 2)
        pl.rate = round(vals["rate"], 4)
        pl.amount = round(vals["amount"], 2)
        pl.compute_total()
        slip.line_ids.append(pl)
    slip.state = "verify"
    slip.compute_date = date.today()
    db.session.flush()
    track_payslip(slip, old, author)
    return True


def action_payslip_draft(slip, author=""):
    old = snapshot(slip)
    slip.state = "draft"
    track_payslip(slip, old, author)


def action_payslip_done(slip, author="", without_compute_sheet=False):
    ws = slip_workspace(slip)
    if not without_compute_sheet and not ws.prevent_compute_on_confirm:
        compute_sheet(slip, author)
    old = snapshot(slip)
    slip.state = "done"
    track_payslip(slip, old, author)


def action_payslip_cancel(slip, author=""):
    ws = slip_workspace(slip)
    if ws.allow_cancel_payslips:
        if slip.refunded and slip.refunded.state != "cancel":
            raise UserError("Per annullare la busta paga originale bisogna prima annullare la busta di storno.")
    elif slip.state == "done":
        raise UserError("Non si può annullare una busta paga completata "
                        "(attiva 'Consente annullamento buste paga confermate' nelle Impostazioni).")
    old = snapshot(slip)
    slip.state = "cancel"
    track_payslip(slip, old, author)


def copy_payslip(slip, **default):
    new = Payslip(workspace_id=slip.workspace_id, struct_id=slip.struct_id, name=slip.name,
                  employee_id=slip.employee_id, date_from=slip.date_from, date_to=slip.date_to,
                  note=slip.note, contract_id=slip.contract_id, credit_note=slip.credit_note,
                  hide_child_lines=slip.hide_child_lines, hide_invisible_lines=slip.hide_invisible_lines,
                  compute_date=slip.compute_date)
    for k, v in default.items():
        setattr(new, k, v)
    for wd in slip.worked_days_line_ids:
        new.worked_days_line_ids.append(PayslipWorkedDays(name=wd.name, sequence=wd.sequence, code=wd.code,
                                                          number_of_days=wd.number_of_days,
                                                          number_of_hours=wd.number_of_hours,
                                                          contract_id=wd.contract_id))
    for i in slip.input_line_ids:
        new.input_line_ids.append(PayslipInput(name=i.name, sequence=i.sequence, code=i.code, amount=i.amount,
                                               amount_qty=i.amount_qty, contract_id=i.contract_id))
    cols = [c.name for c in PayslipLine.__table__.columns if c.name not in ("id", "slip_id")]
    for ln in slip.line_ids:
        new.line_ids.append(PayslipLine(**{c: getattr(ln, c) for c in cols}))
    db.session.add(new)
    db.session.flush()
    return new


def refund_sheet(slip, author=""):
    """Storno: copia la busta come nota di credito confermata e la collega all'originale."""
    refund = copy_payslip(slip, credit_note=True, name=f"Storno: {slip.name}")
    refund.number = slip_workspace(slip).next_slip_number()
    log_message(slip.workspace_id, "hr.payslip", refund.id, body=f"Creata come storno di {slip.number}",
                author=author)
    action_payslip_done(refund, author, without_compute_sheet=True)
    slip.refunded_id = refund.id
    log_message(slip.workspace_id, "hr.payslip", slip.id, body=f"Stornata con {refund.number}", author=author)
    return refund


def check_unlink(slip):
    if slip.state not in ("draft", "cancel"):
        raise UserError("Non si può eliminare una busta paga che non è in bozza o rifiutata.")


def compute_name(slip):
    slip.name = f"Foglio retribuzione di {slip.employee.name} per {MESI[slip.date_from.month]}-{slip.date_from.year}"


def onchange_employee(slip, keep_contract=False, keep_struct=False):
    """'Riestrai dati busta paga': contratto, struttura, nome, giorni lavorati e apporti."""
    if not slip.employee or not slip.date_from or not slip.date_to:
        return
    if not keep_contract or not slip.contract_id:
        slip.contract_id = None
        contracts = get_employee_contracts(slip)
        if not contracts:
            return
        slip.contract = contracts[0]
    if not slip.struct_id and not keep_struct:
        if not slip.contract.struct:
            return
        slip.struct = slip.contract.struct
    elif not slip.struct_id and slip.contract and slip.contract.struct:
        slip.struct = slip.contract.struct
    compute_name(slip)
    onchange_dates(slip)
    onchange_struct_id(slip)


def onchange_dates(slip):
    for wd in list(slip.worked_days_line_ids):
        slip.worked_days_line_ids.remove(wd)
    db.session.flush()
    for vals in get_worked_day_lines(slip, get_employee_contracts(slip), slip.date_from, slip.date_to):
        slip.worked_days_line_ids.append(PayslipWorkedDays(**vals))


def onchange_struct_id(slip):
    """Ricrea gli apporti dalle regole della struttura (conserva gli importi già inseriti)."""
    old = {(i.code, i.contract_id): (i.amount, i.amount_qty) for i in slip.input_line_ids}
    for i in list(slip.input_line_ids):
        slip.input_line_ids.remove(i)
    db.session.flush()
    if not slip.struct_id:
        return
    for vals in get_inputs(slip, get_employee_contracts(slip)):
        amount, qty = old.get((vals["code"], vals["contract_id"]), (0.0, 0.0))
        slip.input_line_ids.append(PayslipInput(amount=amount, amount_qty=qty, **vals))


def get_payslip_vals(ws_id, date_from, date_to, employee, contract_id=None, struct_id=None):
    """Valori iniziali di una busta (usato dal wizard 'Genera buste paga')."""
    res = {"name": "", "contract_id": None, "struct_id": None, "worked_days_line_ids": [], "input_line_ids": []}
    if not employee or not date_from or not date_to:
        return res
    contracts = ([db.session.get(Contract, contract_id)] if contract_id
                 else get_contracts(employee, date_from, date_to))
    contracts = [c for c in contracts if c]
    if not contracts:
        return res
    contract = contracts[0]
    res["contract_id"] = contract.id
    if struct_id:
        res["struct_id"] = struct_id
    elif contract.struct_id:
        res["struct_id"] = contract.struct_id
    else:
        return res
    from .models import PayrollStructure, Workspace
    struct = db.session.get(PayrollStructure, res["struct_id"])
    ws = db.session.get(Workspace, ws_id)
    res["worked_days_line_ids"] = worked_day_lines_for(ws, contracts, date_from, date_to)
    res["input_line_ids"] = inputs_for(struct, contracts)
    return res


def generate_payslips(run, employees, author=""):
    """Wizard hr.payslip.employees.compute_sheet."""
    if not employees:
        raise UserError("Devi selezionare almeno un dipendente per generare le buste paga.")
    slips = []
    for emp in employees:
        vals = get_payslip_vals(run.workspace_id, run.date_start, run.date_end, emp, struct_id=run.struct_id)
        slip = Payslip(workspace_id=run.workspace_id, employee=emp, payslip_run=run,
                       date_from=run.date_start, date_to=run.date_end, credit_note=run.credit_note,
                       contract_id=vals["contract_id"], struct_id=vals["struct_id"])
        for wd in vals["worked_days_line_ids"]:
            slip.worked_days_line_ids.append(PayslipWorkedDays(**wd))
        for i in vals["input_line_ids"]:
            slip.input_line_ids.append(PayslipInput(**i))
        db.session.add(slip)
        db.session.flush()
        compute_name(slip)
        log_message(slip.workspace_id, "hr.payslip", slip.id, body=f"Creata dal gruppo {run.name}", author=author)
        slips.append(slip)
    errors = []
    for slip in slips:
        try:
            compute_sheet(slip, author)  # se una regola fallisce la busta resta in bozza
        except UserError as e:
            errors.append(str(e))
    return slips, errors


def change_state(slips, new_state, author=""):
    """Wizard hr.payslip.change.state."""
    for rec in slips:
        if new_state == "draft":
            if rec.state == "cancel":
                action_payslip_draft(rec, author)
            else:
                raise UserError(f"Solo le buste rifiutate possono tornare in bozza: "
                                f"{rec.name} è nello stato {STATE_LABEL[rec.state]}.")
        elif new_state == "verify":
            if rec.state in ("draft", "verify"):
                compute_sheet(rec, author)
            else:
                raise UserError(f"Solo le buste in bozza possono essere calcolate: "
                                f"{rec.name} è nello stato {STATE_LABEL[rec.state]}.")
        elif new_state == "done":
            if rec.state in ("verify", "draft"):
                action_payslip_done(rec, author)
            else:
                raise UserError(f"Solo le buste in attesa o in bozza possono essere confermate: "
                                f"{rec.name} è nello stato {STATE_LABEL[rec.state]}.")
        elif new_state == "cancel":
            if rec.state != "cancel":
                action_payslip_cancel(rec, author)
            else:
                raise UserError(f"La busta {rec.name} è già annullata: deselezionala.")


def now_str():
    return now().strftime("%d/%m/%Y %H:%M")
