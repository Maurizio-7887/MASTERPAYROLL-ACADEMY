"""Oggetti disponibili nelle regole: porting di payroll/models/base_browsable.py.

In Odoo le regole ricevono record veri (``employee``, ``contract``, ``payslip``).
Qui ricevono dei *proxy in sola lettura* che espongono solo campi sicuri:
un allievo non può raggiungere il database o i dati di altri allievi.
"""
from datetime import date

from sqlalchemy import func

from .models import Payslip, PayslipInput, PayslipLine, PayslipWorkedDays, db


class BaseBrowsableObject:
    """Come Odoo: attributo mancante (o falso) → 0.0."""

    def __init__(self, vals_dict):
        self.__dict__["base_fields"] = ["base_fields", "dict"]
        self.dict = vals_dict

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        return attr in self.dict and self.dict.__getitem__(attr) or 0.0

    def __setattr__(self, attr, value):
        if attr in self.__dict__["base_fields"]:
            return super().__setattr__(attr, value)
        self.__dict__["dict"][attr] = value
        return None

    def __str__(self):
        return str(self.__dict__.get("dict"))


class BrowsableObject(BaseBrowsableObject):
    def __init__(self, employee_id, vals_dict, ws_id):
        super().__init__(vals_dict)
        self.base_fields += ["employee_id", "ws_id"]
        self.employee_id = employee_id
        self.ws_id = ws_id


def _done_slips(employee_id, ws_id, from_date, to_date):
    if to_date is None:
        to_date = date.today()
    return (Payslip.query.filter(Payslip.workspace_id == ws_id, Payslip.employee_id == employee_id,
                                 Payslip.state == "done", Payslip.date_from >= from_date,
                                 Payslip.date_to <= to_date))


class InputLine(BrowsableObject):
    def sum(self, code, from_date, to_date=None):
        ids = [s.id for s in _done_slips(self.employee_id, self.ws_id, from_date, to_date)]
        if not ids:
            return 0.0
        v = db.session.query(func.sum(PayslipInput.amount)).filter(
            PayslipInput.payslip_id.in_(ids), PayslipInput.code == code).scalar()
        return v or 0.0


class WorkedDays(BrowsableObject):
    def _sum(self, code, from_date, to_date=None):
        ids = [s.id for s in _done_slips(self.employee_id, self.ws_id, from_date, to_date)]
        if not ids:
            return (0.0, 0.0)
        return db.session.query(func.sum(PayslipWorkedDays.number_of_days),
                                func.sum(PayslipWorkedDays.number_of_hours)).filter(
            PayslipWorkedDays.payslip_id.in_(ids), PayslipWorkedDays.code == code).one()

    def sum(self, code, from_date, to_date=None):
        res = self._sum(code, from_date, to_date)
        return res and res[0] or 0.0

    def sum_hours(self, code, from_date, to_date=None):
        res = self._sum(code, from_date, to_date)
        return res and res[1] or 0.0


class Payslips(BrowsableObject):
    def sum(self, code, from_date, to_date=None):
        """Somma della regola nelle buste confermate (le note di credito si sottraggono)."""
        total = 0.0
        for slip in _done_slips(self.employee_id, self.ws_id, from_date, to_date):
            for line in PayslipLine.query.filter_by(slip_id=slip.id, code=code):
                total += -line.total if slip.credit_note else line.total
        return total


# ---------------------------------------------------------------------------
# Proxy dei record
# ---------------------------------------------------------------------------
class RecordProxy:
    """Espone in sola lettura solo i campi elencati."""
    _fields = ()
    _model = ""

    def __init__(self, record):
        object.__setattr__(self, "_record", record)

    def __getattr__(self, name):
        if name.startswith("_") or name not in self._fields:
            raise AttributeError(f"'{self._model}' non ha il campo '{name}' (o non è disponibile nelle regole)")
        value = getattr(self._record, name)
        return wrap(value)

    def __setattr__(self, name, value):
        raise AttributeError(f"I record ({self._model}) sono in sola lettura nelle regole")

    def __bool__(self):
        return self._record is not None

    def __eq__(self, other):
        return isinstance(other, RecordProxy) and other._record is self._record

    def __hash__(self):
        return id(self._record)

    def __repr__(self):
        return f"{self._model}({getattr(self._record, 'id', '')})"


class CalendarProxy(RecordProxy):
    _model = "resource.calendar"
    _fields = ("id", "name", "hours_per_day", "hours_per_week")


class LivelloProxy(RecordProxy):
    _model = "livello"
    _fields = ("id", "codice", "descrizione", "minimo", "scatto_importo")


class FamiliareProxy(RecordProxy):
    _model = "familiare"
    _fields = ("id", "relazione", "nome", "data_nascita", "percentuale")

    def eta_al(self, d):
        return self._record.eta_al(d)


class EmployeeProxy(RecordProxy):
    _model = "hr.employee"
    _fields = ("id", "name", "first_name", "last_name", "registration_number", "job_title", "department",
               "qualifica", "work_email", "identification_id", "birthday", "place_of_birth",
               "resource_calendar", "familiari", "active")


class ContractProxy(RecordProxy):
    _model = "hr.version"
    _fields = ("id", "name", "state", "contract_type", "job_title", "department", "date_start", "date_end",
               "trial_date_end", "resource_calendar", "wage", "schedule_pay", "ccnl", "livello", "superminimo",
               "scatti_n", "scatto_importo", "part_time", "mensilita", "divisore_orario", "add_reg_rata",
               "add_com_rata", "retribuzione_mensile", "ral", "employee")


class PayslipProxy(RecordProxy):
    _model = "hr.payslip"
    _fields = ("id", "name", "number", "date_from", "date_to", "state", "credit_note", "employee", "contract",
               "note", "compute_date")

    def get_salary_line_total(self, code):
        return self._record.get_salary_line_total(code)


class WorkedDaysLineProxy(RecordProxy):
    _model = "hr.payslip.worked_days"
    _fields = ("id", "name", "code", "sequence", "number_of_days", "number_of_hours", "contract")


class InputLineProxy(RecordProxy):
    _model = "hr.payslip.input"
    _fields = ("id", "name", "code", "sequence", "amount", "amount_qty", "contract")


class CategoryProxy(RecordProxy):
    _model = "hr.salary.rule.category"
    _fields = ("id", "name", "code", "parent")


class RegisterProxy(RecordProxy):
    _model = "hr.contribution.register"
    _fields = ("id", "name", "f24_codice", "f24_sezione")


class RuleProxy(RecordProxy):
    _model = "hr.salary.rule"
    _fields = ("id", "name", "code", "sequence", "quantity", "category", "appears_on_payslip", "parent_rule",
               "condition_select", "condition_range", "condition_range_min", "condition_range_max",
               "amount_select", "amount_fix", "amount_percentage", "amount_percentage_base", "register")


_PROXIES = {}


def wrap(value):
    from . import models as m
    if not _PROXIES:
        _PROXIES.update({
            m.Employee: EmployeeProxy, m.Contract: ContractProxy, m.Payslip: PayslipProxy,
            m.ResourceCalendar: CalendarProxy, m.Livello: LivelloProxy, m.Familiare: FamiliareProxy,
            m.PayslipWorkedDays: WorkedDaysLineProxy, m.PayslipInput: InputLineProxy,
            m.SalaryRuleCategory: CategoryProxy, m.ContributionRegister: RegisterProxy,
            m.SalaryRule: RuleProxy,
        })
    if value is None or isinstance(value, (int, float, str, bool, date, RecordProxy, BaseBrowsableObject)):
        return value
    if isinstance(value, (list, tuple)):
        return [wrap(v) for v in value]
    cls = _PROXIES.get(type(value))
    if cls:
        return cls(value)
    raise AttributeError("Valore non disponibile nelle regole")
