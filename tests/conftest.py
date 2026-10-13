import os
import sys
from datetime import date

import pytest
from flask import g
from flask.testing import FlaskClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from masterpayroll import create_app, ensure_workspace  # noqa: E402
from masterpayroll.models import (Contract, ContributionRegister, Employee, PayrollStructure,  # noqa: E402
                                  ResourceCalendar, ResourceCalendarAttendance, RuleInput, SalaryRule,
                                  SalaryRuleCategory, User, db)


class FreshClient(FlaskClient):
    """Il test tiene aperto un app context (per usare il DB tra le richieste): qui si svuota
    `g` prima di ogni richiesta, così ogni client ha il suo utente come in produzione."""

    def open(self, *args, **kwargs):
        g.__dict__.clear()
        return super().open(*args, **kwargs)


@pytest.fixture()
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite://", "ADMIN_PASSWORD": "prof123",
                      "TESTING": True, "TESTING_NO_CSRF": True})
    app.test_client_class = FreshClient
    with app.app_context():
        yield app


@pytest.fixture()
def ws(app):
    return ensure_workspace(User.query.filter_by(username="docente").one())


@pytest.fixture()
def docente(app):
    c = app.test_client()
    r = c.post("/login", data={"username": "docente", "password": "prof123"})
    assert r.status_code == 302
    return c


class OdooBase:
    """Porting di payroll/tests/common.py (TestPayslipBase) dentro un ambiente."""

    def __init__(self, ws):
        w = ws.id
        self.ws = ws
        self.categ_basic = SalaryRuleCategory(workspace_id=w, name="Basic", code="T_BASIC")
        self.categ_alw = SalaryRuleCategory(workspace_id=w, name="Allowance", code="T_ALW")
        self.categ_gross = SalaryRuleCategory(workspace_id=w, name="Gross", code="T_GROSS")
        self.categ_ded = SalaryRuleCategory(workspace_id=w, name="Deduction", code="T_DED")
        self.categ_net = SalaryRuleCategory(workspace_id=w, name="NET", code="T_NET")
        db.session.add_all([self.categ_basic, self.categ_alw, self.categ_gross, self.categ_ded, self.categ_net])

        def rule(**kw):
            r = SalaryRule(workspace_id=w, **kw)
            db.session.add(r)
            return r
        self.rule_basic = rule(name="Basic Salary", code="BASIC", sequence=1, category=self.categ_basic,
                               amount_select="code", amount_python_compute="result = contract.wage")
        self.rule_hra = rule(name="House Rent Allowance", code="HRA", sequence=5, category=self.categ_alw,
                             amount_select="percentage", amount_percentage=40.0, amount_percentage_base="contract.wage")
        self.rule_meal = rule(name="Meal Voucher", code="MA", sequence=16, category=self.categ_alw, amount_select="fix",
                              amount_fix=10.0, quantity="worked_days.WORK100 and worked_days.WORK100.number_of_days")
        self.rule_commission = rule(name="Get 1% of sales", code="SALE", sequence=17, category=self.categ_alw,
                                    amount_select="code",
                                    amount_python_compute="result = (inputs.SALEURO and inputs.SALEURO.amount) * 0.01")
        self.rule_commission.input_ids.append(RuleInput(name="Sales to Europe", code="SALEURO"))
        self.rule_gross = rule(name="Gross", code="GROSS", sequence=100, category=self.categ_gross, amount_select="code",
                               amount_python_compute="result = categories.T_BASIC + categories.T_ALW")
        self.rule_proftax = rule(name="Professional Tax", code="PT", sequence=150, category=self.categ_ded,
                                 amount_select="fix", amount_fix=-200.0)
        self.rule_net = rule(name="Net", code="NET", sequence=200, category=self.categ_net, amount_select="code",
                             amount_python_compute="result = categories.T_BASIC + categories.T_ALW + categories.T_DED")
        self.rule_child = rule(name="Net Child Rule", code="NET_CHILD", sequence=190, category=self.categ_net,
                               parent_rule=self.rule_net, amount_select="code",
                               amount_python_compute="result = categories.T_BASIC + categories.T_ALW + categories.T_DED")
        self.register_hra = ContributionRegister(workspace_id=w, name="House Rent Allowance")
        db.session.add(self.register_hra)
        self.calendar = ResourceCalendar(workspace_id=w, name="40h")
        for d in range(5):
            self.calendar.attendance_ids.append(ResourceCalendarAttendance(dayofweek=d, hour_from=8, hour_to=12))
            self.calendar.attendance_ids.append(ResourceCalendarAttendance(dayofweek=d, hour_from=13, hour_to=17))
        db.session.add(self.calendar)
        self.developer_pay_structure = PayrollStructure(workspace_id=w, name="Salary Structure for Software Developer",
                                                        code="SD")
        self.developer_pay_structure.rule_ids = [self.rule_hra, self.rule_proftax, self.rule_meal,
                                                 self.rule_commission, self.rule_basic, self.rule_gross,
                                                 self.rule_net]
        db.session.add(self.developer_pay_structure)
        self.richard_emp = Employee(workspace_id=w, last_name="Richard", first_name="Test",
                                    birthday=date(1984, 5, 1), department="R&D", resource_calendar=self.calendar)
        self.richard_contract = Contract(workspace_id=w, name="Contract for Richard", state="open",
                                         date_start=date(2026, 1, 1), wage=5000.0,
                                         struct=self.developer_pay_structure, resource_calendar=self.calendar)
        self.richard_emp.contract_ids.append(self.richard_contract)
        db.session.add(self.richard_emp)
        db.session.flush()


@pytest.fixture()
def odoo(ws):
    return OdooBase(ws)
