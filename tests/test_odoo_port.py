"""Porting dei test del modulo OCA/payroll 19.0 (cartella payroll/tests)."""
from datetime import date

import pytest

from masterpayroll import payroll
from masterpayroll.browsable import BaseBrowsableObject, BrowsableObject
from masterpayroll.models import (Leave, LeaveType, Payslip, PayslipRun, ResourceCalendarLeave, SalaryRule,
                                  SalaryRuleCategory, PayrollStructure, db)
from masterpayroll.reports import contribution_register_pdf, payslip_details_pdf, payslip_pdf

D1, D2 = date(2026, 9, 1), date(2026, 9, 30)  # settembre 2026: 22 giorni lavorativi, nessuna festività


def new_slip(odoo, **kw):
    slip = Payslip(workspace_id=odoo.ws.id, employee=odoo.richard_emp, date_from=kw.pop("date_from", D1),
                   date_to=kw.pop("date_to", D2), **kw)
    db.session.add(slip)
    db.session.flush()
    payroll.onchange_employee(slip, keep_contract=bool(slip.contract_id), keep_struct=bool(slip.struct_id))
    return slip


def line(slip, code):
    found = [ln for ln in slip.line_ids if ln.code == code]
    return found[0] if len(found) == 1 else (found or None)


# --------------------------------------------------------------------------- test_payslip_flow
def test_00_payslip_flow(odoo, ws):
    slip = new_slip(odoo)
    assert slip.state == "draft"
    assert slip.contract == odoo.richard_contract and slip.struct == odoo.developer_pay_structure
    assert slip.name == "Foglio retribuzione di Richard Test per settembre-2026"
    inp = [i for i in slip.input_line_ids if i.code == "SALEURO"][0]
    inp.amount = 5.0
    payroll.compute_sheet(slip)
    assert slip.state == "verify" and slip.number.startswith("SLIP/")

    # le righe figlie si vedono di default, con la riga padre corretta
    child = [ln for ln in slip.dynamic_filtered_payslip_lines if ln.code == "NET_CHILD"]
    assert len(child) == 1
    assert child[0].parent_line.code == "NET"
    assert line(slip, "NET").parent_line is None
    slip.hide_child_lines = True
    assert not [ln for ln in slip.dynamic_filtered_payslip_lines if ln.code == "NET_CHILD"]

    work100 = [w for w in slip.worked_days_line_ids if w.code == "WORK100"][0]
    assert work100.number_of_days == 22
    assert line(slip, "NET").amount == pytest.approx(5000.0 + 0.4 * 5000 + work100.number_of_days * 10 + 0.05 - 200)

    payroll.action_payslip_done(slip)
    assert slip.state == "done"
    refund = payroll.refund_sheet(slip)
    assert refund.credit_note and refund.name == "Storno: " + slip.name and refund.state == "done"
    assert slip.refunded_id == refund.id
    assert len(refund.line_ids) == len(slip.line_ids)

    run = PayslipRun(workspace_id=ws.id, name="Payslip for Employee", date_start=D1, date_end=D2)
    db.session.add(run)
    db.session.flush()
    slips, errors = payroll.generate_payslips(run, [odoo.richard_emp])
    assert not errors and slips[0].state == "verify" and slips[0].payslip_run == run

    assert payslip_pdf(ws, [slip]).startswith(b"%PDF")
    assert payslip_details_pdf(ws, [slip]).startswith(b"%PDF")
    assert contribution_register_pdf(ws, [odoo.register_hra], D1, D2).startswith(b"%PDF")


# --------------------------------------------------------------------------- test_hr_payroll_cancel
def _computed(odoo):
    slip = new_slip(odoo)
    for i in slip.input_line_ids:
        i.amount = 5.0
    payroll.compute_sheet(slip)
    return slip


def test_refund_sheet_cancel(odoo, ws):
    ws.allow_cancel_payslips = True
    slip = _computed(odoo)
    payroll.action_payslip_done(slip)
    payroll.refund_sheet(slip)
    with pytest.raises(payroll.UserError):
        payroll.action_payslip_cancel(slip)
    assert slip.refunded.state == "done"
    payroll.action_payslip_cancel(slip.refunded)
    assert slip.refunded.state == "cancel" and slip.state == "done"
    payroll.action_payslip_cancel(slip)
    assert slip.state == "cancel"


def test_cannot_cancel_done_without_setting(odoo, ws):
    slip = _computed(odoo)
    payroll.action_payslip_done(slip)
    with pytest.raises(payroll.UserError):
        payroll.action_payslip_cancel(slip)


def test_unlink_only_draft_or_cancel(odoo):
    slip = _computed(odoo)
    with pytest.raises(payroll.UserError):
        payroll.check_unlink(slip)
    payroll.action_payslip_cancel(slip)
    payroll.check_unlink(slip)


def test_confirm_recomputes_when_setting_off(odoo, ws):
    slip = _computed(odoo)
    ln = line(slip, "BASIC")
    ln.amount = 1
    ln.compute_total()
    ws.prevent_compute_on_confirm = False
    payroll.action_payslip_done(slip)
    assert line(slip, "BASIC").total == 5000


# --------------------------------------------------------------------------- test_hr_payslip_change_state
def test_change_state(odoo):
    slip = _computed(odoo)
    payroll.change_state([slip], "verify")
    with pytest.raises(payroll.UserError):
        payroll.change_state([slip], "draft")
    assert slip.state == "verify" and slip.number
    payroll.change_state([slip], "done")
    assert slip.state == "done"
    for st in ("draft", "verify", "done"):
        with pytest.raises(payroll.UserError):
            payroll.change_state([slip], st)
    odoo.ws.allow_cancel_payslips = True
    payroll.change_state([slip], "cancel")
    assert slip.state == "cancel"
    for st in ("done", "verify", "cancel"):
        with pytest.raises(payroll.UserError):
            payroll.change_state([slip], st)
    payroll.change_state([slip], "draft")
    assert slip.state == "draft"


# --------------------------------------------------------------------------- test_hr_payslip_worked_days
def _with_leave(odoo, positive):
    odoo.ws.leaves_positive = positive
    db.session.add(ResourceCalendarLeave(workspace_id=odoo.ws.id, name="Festa", date=date(2026, 9, 15)))
    lt = LeaveType(workspace_id=odoo.ws.id, name="TestLeaveType", code="TLT")
    db.session.add(Leave(workspace_id=odoo.ws.id, employee=odoo.richard_emp, holiday_status=lt,
                         date_from=date(2026, 9, 16), date_to=date(2026, 9, 16), state="validate"))
    db.session.add(Leave(workspace_id=odoo.ws.id, employee=odoo.richard_emp, holiday_status=lt,
                         date_from=date(2026, 9, 17), date_to=date(2026, 9, 17), state="refuse"))
    db.session.flush()
    return new_slip(odoo)


@pytest.mark.parametrize("positive,sign", [(False, -1), (True, 1)])
def test_worked_days_sign(odoo, positive, sign):
    slip = _with_leave(odoo, positive)
    wd = {w.code: w for w in slip.worked_days_line_ids}
    assert set(wd) == {"WORK100", "GLOBAL", "TLT"}
    assert (wd["GLOBAL"].number_of_days, wd["GLOBAL"].number_of_hours) == (sign * 1.0, sign * 8.0)
    assert (wd["TLT"].number_of_days, wd["TLT"].number_of_hours) == (sign * 1.0, sign * 8.0)
    assert wd["WORK100"].number_of_days == 22  # come Odoo: giorni pieni da calendario


def test_worked_days_respect_contract_start(odoo):
    odoo.richard_contract.date_start = date(2026, 9, 16)
    slip = new_slip(odoo)
    work = [w for w in slip.worked_days_line_ids if w.code == "WORK100"][0]
    assert work.number_of_days == 11


# --------------------------------------------------------------------------- test_hr_salary_rule
@pytest.fixture()
def rules(odoo):
    w = odoo.ws.id
    test_rule = SalaryRule(workspace_id=w, name="Test Rule", code="TEST", category=odoo.categ_alw, sequence=6,
                           amount_select="code", amount_python_compute="result = 0")
    parent_test = SalaryRule(workspace_id=w, name="Parent Test Rule", code="PARENT_TEST", category=odoo.categ_alw,
                             sequence=6, parent_rule=test_rule, amount_select="code",
                             amount_python_compute="result = 100")
    child_test = SalaryRule(workspace_id=w, name="Child Test Rule", code="CHILD_TEST", category=odoo.categ_alw,
                            sequence=7, parent_rule=test_rule, amount_select="code",
                            amount_python_compute="result = 100")
    db.session.add_all([test_rule, parent_test, child_test])
    odoo.developer_pay_structure.rule_ids += [test_rule, parent_test]
    db.session.flush()
    return test_rule, parent_test, child_test


def test_python_code_return_values(odoo, rules):
    rules[0].amount_python_compute = "result_rate = 0\nresult_qty = 0\nresult = 0\n"
    slip = new_slip(odoo)
    payroll.compute_sheet(slip)
    ln = line(slip, "TEST")
    assert (ln.amount, ln.rate, ln.quantity, ln.code) == (0.0, 0.0, 0.0, "TEST")


def test_python_code_result_not_set(odoo, rules):
    rules[0].amount_python_compute = "result = 2"
    slip = new_slip(odoo)
    payroll.compute_sheet(slip)
    ln = line(slip, "TEST")
    assert (ln.amount, ln.rate, ln.quantity) == (2.0, 100.0, 1.0)


def test_parent_child_order(odoo, rules):
    test_rule, _, child = rules
    slip = new_slip(odoo)
    payroll.compute_sheet(slip)
    assert line(slip, "CHILD_TEST")
    child.sequence = 5
    slip2 = new_slip(odoo)
    payroll.compute_sheet(slip2)
    assert line(slip2, "CHILD_TEST")
    test_rule.condition_select = "python"
    test_rule.condition_python = "result = False"
    slip3 = new_slip(odoo)
    payroll.compute_sheet(slip3)
    assert line(slip3, "PARENT_TEST") is None and line(slip3, "CHILD_TEST") is None


def test_rule_and_category_with_and_without_code(odoo):
    w = odoo.ws.id
    rule_test_code = SalaryRule(workspace_id=w, name="rule test code", code="rule_test_code", sequence=100,
                                amount_select="code", amount_python_compute="result = categories.T_BASIC + HRA")
    categ_no_code = SalaryRuleCategory(workspace_id=w, name="categ no code")
    no_code = SalaryRule(workspace_id=w, name="rule without code", category=categ_no_code, sequence=10,
                         amount_select="code", amount_python_compute="result = 100")
    no_cat = SalaryRule(workspace_id=w, name="rule without category", sequence=10, amount_select="code",
                        amount_python_compute="result = 100")
    st = PayrollStructure(workspace_id=w, name="test code and id")
    st.rule_ids = [odoo.rule_basic, odoo.rule_hra, rule_test_code, no_code, no_cat]
    db.session.add_all([rule_test_code, categ_no_code, no_code, no_cat, st])
    db.session.flush()
    slip = new_slip(odoo, contract_id=odoo.richard_contract.id, struct_id=st.id)
    payroll.compute_sheet(slip)
    assert line(slip, "rule_test_code").total == 7000
    assert len([ln for ln in slip.line_ids if ln.name == "rule without code"]) == 1
    assert len([ln for ln in slip.line_ids if ln.name == "rule without category"]) == 1


def test_range_condition_and_structure_parent(odoo):
    w = odoo.ws.id
    bonus = SalaryRule(workspace_id=w, name="Bonus alti redditi", code="BONUS", sequence=50, category=odoo.categ_alw,
                       condition_select="range", condition_range="contract.wage", condition_range_min=4000,
                       condition_range_max=6000, amount_select="fix", amount_fix=50)
    child_st = PayrollStructure(workspace_id=w, name="Figlia", code="SDX", parent=odoo.developer_pay_structure)
    child_st.rule_ids = [bonus]
    db.session.add_all([bonus, child_st])
    db.session.flush()
    slip = new_slip(odoo, struct_id=child_st.id)
    payroll.compute_sheet(slip)
    assert line(slip, "BONUS").total == 50 and line(slip, "BASIC").total == 5000  # BASIC ereditata dal padre
    odoo.richard_contract.wage = 3000
    payroll.compute_sheet(slip)
    assert line(slip, "BONUS") is None


def test_wrong_code_raises_user_error(odoo):
    odoo.rule_hra.amount_select = "code"
    odoo.rule_hra.amount_python_compute = "result = contract.salario_inesistente"
    slip = new_slip(odoo)
    with pytest.raises(payroll.UserError) as e:
        payroll.compute_sheet(slip)
    assert "HRA" in str(e.value)
    assert slip.state == "draft" and not slip.line_ids


def test_recursive_structures_detected(odoo):
    st = odoo.developer_pay_structure
    child = PayrollStructure(workspace_id=odoo.ws.id, name="c", code="C", parent=st)
    db.session.add(child)
    db.session.flush()
    st.parent = child
    assert payroll.has_cycle(st, "parent")


# --------------------------------------------------------------------------- test_browsable_object
def test_browsable_init_and_update():
    obj = BrowsableObject(7, {"test": 1}, 1)
    assert obj.test == 1 and obj.employee_id == 7
    obj = BrowsableObject(7, {"level1": BaseBrowsableObject({"level2": 10, "env": 900.0})}, 1)
    assert obj.level1.level2 == 10 and obj.level1.employee_id == 0.0 and obj.level1.env == 900.0
    obj = BrowsableObject(7, {"foo": BaseBrowsableObject({"bar": 200.0})}, 1)
    obj.foo.bar = 350.0
    assert obj.foo.bar == 350.0
    assert obj.missing == 0.0


def test_payslips_sum_subtracts_credit_notes(odoo):
    slip = _computed(odoo)
    payroll.action_payslip_done(slip)
    from masterpayroll.browsable import Payslips
    ps = Payslips(odoo.richard_emp.id, {}, odoo.ws.id)
    assert ps.sum("BASIC", date(2026, 1, 1), date(2026, 12, 31)) == 5000
    payroll.refund_sheet(slip)
    assert ps.sum("BASIC", date(2026, 1, 1), date(2026, 12, 31)) == 0
