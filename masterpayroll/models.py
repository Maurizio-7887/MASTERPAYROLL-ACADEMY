"""Modelli dati.

Ogni classe ricalca un modello del modulo Payroll di Odoo (OCA/payroll 19.0) e
dei moduli da cui dipende (hr, hr_contract/hr.version, resource, hr_holidays,
mail). Il nome del modello Odoo è indicato in ``_odoo`` e mostrato
nell'interfaccia, così gli allievi imparano anche la struttura di Odoo.

Ogni ``Workspace`` è una azienda (``res.company``): ogni allievo ne ha una sua,
isolata dalle altre.
"""
from datetime import date, datetime, timedelta, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def now():
    """Ora UTC senza fuso (colonne DateTime semplici)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ws_fk():
    return db.Column(db.Integer, db.ForeignKey("workspaces.id", ondelete="CASCADE"),
                     index=True, nullable=False)


# ===========================================================================
# Academy: utenti, ambienti, tracciamento, esercitazioni
# ===========================================================================
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="allievo")  # docente | allievo
    classe = db.Column(db.String(80), default="")
    active_flag = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=now)
    last_seen = db.Column(db.DateTime)

    workspace = db.relationship("Workspace", back_populates="owner", uselist=False,
                                cascade="all, delete-orphan")

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

    @property
    def is_docente(self):
        return self.role == "docente"

    @property
    def is_active(self):
        return bool(self.active_flag)


class Workspace(db.Model):
    """res.company + res.config.settings del modulo payroll."""
    __tablename__ = "workspaces"
    _odoo = "res.company"
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now)
    reset_at = db.Column(db.DateTime)

    name = db.Column(db.String(160), default="")
    vat = db.Column(db.String(30), default="")
    street = db.Column(db.String(200), default="")
    city = db.Column(db.String(120), default="")
    email = db.Column(db.String(120), default="")
    phone = db.Column(db.String(40), default="")
    ccnl = db.Column(db.String(160), default="")
    matricola_inps = db.Column(db.String(40), default="")
    pat_inail = db.Column(db.String(40), default="")
    currency = db.Column(db.String(3), default="EUR")

    # res.config.settings (payroll.*)
    leaves_positive = db.Column(db.Boolean, default=False)
    allow_cancel_payslips = db.Column(db.Boolean, default=False)
    prevent_compute_on_confirm = db.Column(db.Boolean, default=True)
    allow_edit_payslip_lines = db.Column(db.Boolean, default=False)
    require_code_and_category = db.Column(db.Boolean, default=False)

    # ir.sequence "salary.slip": prefisso SLIP/, padding 3
    slip_sequence_next = db.Column(db.Integer, default=1)

    owner = db.relationship("User", back_populates="workspace")

    def next_slip_number(self):
        n = self.slip_sequence_next or 1
        self.slip_sequence_next = n + 1
        return f"SLIP/{n:03d}"


class Attivita(db.Model):
    """Log delle azioni dell'allievo: base per il calcolo delle ore reali."""
    __tablename__ = "attivita"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ts = db.Column(db.DateTime, default=now, index=True)
    metodo = db.Column(db.String(10))
    path = db.Column(db.String(255))


class Esercitazione(db.Model):
    __tablename__ = "esercitazioni"
    id = db.Column(db.Integer, primary_key=True)
    ordine = db.Column(db.Integer, default=0)
    titolo = db.Column(db.String(200), nullable=False)
    testo = db.Column(db.Text, default="")
    livello = db.Column(db.String(20), default="base")
    attiva = db.Column(db.Boolean, default=True)


class EsercitazioneSvolta(db.Model):
    __tablename__ = "esercitazioni_svolte"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    esercitazione_id = db.Column(db.Integer, db.ForeignKey("esercitazioni.id", ondelete="CASCADE"))
    consegnata_at = db.Column(db.DateTime, default=now)
    nota = db.Column(db.Text, default="")
    __table_args__ = (db.UniqueConstraint("user_id", "esercitazione_id"),)


# ===========================================================================
# base / mail
# ===========================================================================
class Partner(db.Model):
    __tablename__ = "partners"
    _odoo = "res.partner"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(160), nullable=False)
    vat = db.Column(db.String(30), default="")
    street = db.Column(db.String(200), default="")
    city = db.Column(db.String(120), default="")
    email = db.Column(db.String(120), default="")


class Message(db.Model):
    """mail.message: il "chatter" con tracciamento dei campi."""
    __tablename__ = "messages"
    _odoo = "mail.message"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    model = db.Column(db.String(40), index=True)
    res_id = db.Column(db.Integer, index=True)
    author = db.Column(db.String(120), default="")
    date = db.Column(db.DateTime, default=now)
    body = db.Column(db.Text, default="")
    tracking = db.Column(db.Text, default="")  # righe "campo: vecchio → nuovo"
    message_type = db.Column(db.String(20), default="notification")  # notification | comment | email


class MailMail(db.Model):
    """mail.mail: posta in uscita (simulata se SMTP non è configurato)."""
    __tablename__ = "mail_mail"
    _odoo = "mail.mail"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    payslip_id = db.Column(db.Integer, db.ForeignKey("payslips.id", ondelete="SET NULL"))
    email_from = db.Column(db.String(160), default="")
    email_to = db.Column(db.String(160), default="")
    subject = db.Column(db.String(255), default="")
    body_html = db.Column(db.Text, default="")
    attachment_name = db.Column(db.String(160), default="")
    attachment = db.Column(db.LargeBinary)
    state = db.Column(db.String(20), default="outgoing")  # outgoing | sent | simulated | exception
    failure_reason = db.Column(db.Text, default="")
    date = db.Column(db.DateTime, default=now)


# ===========================================================================
# resource / hr_holidays
# ===========================================================================
class ResourceCalendar(db.Model):
    __tablename__ = "resource_calendars"
    _odoo = "resource.calendar"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(120), nullable=False)
    hours_per_day = db.Column(db.Float, default=8.0)
    attendance_ids = db.relationship("ResourceCalendarAttendance", cascade="all, delete-orphan",
                                     order_by="(ResourceCalendarAttendance.dayofweek, "
                                              "ResourceCalendarAttendance.hour_from)",
                                     back_populates="calendar")

    @property
    def hours_per_week(self):
        return sum(a.hour_to - a.hour_from for a in self.attendance_ids)


class ResourceCalendarAttendance(db.Model):
    __tablename__ = "resource_calendar_attendances"
    _odoo = "resource.calendar.attendance"
    id = db.Column(db.Integer, primary_key=True)
    calendar_id = db.Column(db.Integer, db.ForeignKey("resource_calendars.id", ondelete="CASCADE"))
    name = db.Column(db.String(80), default="")
    dayofweek = db.Column(db.Integer, nullable=False)  # 0 = lunedì
    hour_from = db.Column(db.Float, nullable=False)
    hour_to = db.Column(db.Float, nullable=False)
    calendar = db.relationship("ResourceCalendar", back_populates="attendance_ids")


class ResourceCalendarLeave(db.Model):
    """Assenze globali (festività) del calendario: in Odoo diventano 'Global Leaves'."""
    __tablename__ = "resource_calendar_leaves"
    _odoo = "resource.calendar.leaves"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, nullable=False)
    calendar_id = db.Column(db.Integer, db.ForeignKey("resource_calendars.id", ondelete="CASCADE"))
    calendar = db.relationship("ResourceCalendar")


class LeaveType(db.Model):
    __tablename__ = "leave_types"
    _odoo = "hr.leave.type"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(20), nullable=False)  # codice del work entry usato nei worked days
    sequence = db.Column(db.Integer, default=5)
    color = db.Column(db.String(20), default="#6c757d")
    unpaid = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)


class Leave(db.Model):
    __tablename__ = "leaves"
    _odoo = "hr.leave"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(200), default="")
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    holiday_status_id = db.Column(db.Integer, db.ForeignKey("leave_types.id"))
    date_from = db.Column(db.Date, nullable=False)
    date_to = db.Column(db.Date, nullable=False)
    request_unit_hours = db.Column(db.Boolean, default=False)
    hour_from = db.Column(db.Float)
    hour_to = db.Column(db.Float)
    state = db.Column(db.String(20), default="confirm")  # draft | confirm | validate | refuse
    employee = db.relationship("Employee", back_populates="leave_ids")
    holiday_status = db.relationship("LeaveType")


# ===========================================================================
# hr / hr.version (contratti)
# ===========================================================================
class Employee(db.Model):
    __tablename__ = "employees"
    _odoo = "hr.employee"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    active = db.Column(db.Boolean, default=True)
    registration_number = db.Column(db.String(20), default="")  # matricola
    last_name = db.Column(db.String(80), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    job_title = db.Column(db.String(120), default="")  # "Designation" nel report Odoo
    department = db.Column(db.String(80), default="")
    qualifica = db.Column(db.String(20), default="operaio")
    work_email = db.Column(db.String(120), default="")
    work_phone = db.Column(db.String(40), default="")
    private_street = db.Column(db.String(200), default="")
    private_city = db.Column(db.String(120), default="")
    private_email = db.Column(db.String(120), default="")
    identification_id = db.Column(db.String(20), default="")  # codice fiscale
    birthday = db.Column(db.Date)
    place_of_birth = db.Column(db.String(120), default="")
    bank_account = db.Column(db.String(40), default="")  # IBAN
    resource_calendar_id = db.Column(db.Integer, db.ForeignKey("resource_calendars.id"))

    resource_calendar = db.relationship("ResourceCalendar")
    contract_ids = db.relationship("Contract", back_populates="employee", cascade="all, delete-orphan",
                                   order_by="Contract.date_start")
    familiari = db.relationship("Familiare", back_populates="employee", cascade="all, delete-orphan",
                                order_by="Familiare.id")
    leave_ids = db.relationship("Leave", back_populates="employee", cascade="all, delete-orphan")
    slip_ids = db.relationship("Payslip", back_populates="employee", cascade="all, delete-orphan",
                               foreign_keys="Payslip.employee_id")

    @property
    def name(self):
        return f"{self.last_name} {self.first_name}"

    @property
    def payslip_count(self):
        return len(self.slip_ids)

    @property
    def contract_id(self):
        """Contratto corrente (in corso), come employee.contract_id in Odoo."""
        for c in reversed(self.contract_ids):
            if c.state == "open":
                return c
        return None


class Familiare(db.Model):
    """Familiari a carico (estensione italiana di hr.employee)."""
    __tablename__ = "familiari"
    _odoo = "hr.employee.familiare (l10n_it)"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    relazione = db.Column(db.String(20), default="figlio")  # coniuge | figlio | altro
    nome = db.Column(db.String(120), default="")
    codice_fiscale = db.Column(db.String(16), default="")
    data_nascita = db.Column(db.Date)
    percentuale = db.Column(db.Float, default=100.0)
    employee = db.relationship("Employee", back_populates="familiari")

    def eta_al(self, d):
        if not self.data_nascita:
            return None
        return d.year - self.data_nascita.year - ((d.month, d.day) < (self.data_nascita.month,
                                                                      self.data_nascita.day))


class Livello(db.Model):
    """Livelli e minimi del CCNL (estensione italiana)."""
    __tablename__ = "livelli"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    codice = db.Column(db.String(10), nullable=False)
    descrizione = db.Column(db.String(200), default="")
    minimo = db.Column(db.Float, default=0.0)
    scatto_importo = db.Column(db.Float, default=0.0)


CONTRACT_STATES = [("draft", "Nuovo"), ("open", "In corso"), ("close", "Scaduto"), ("cancel", "Annullato")]
SCHEDULE_PAY = [("monthly", "Mensile"), ("quarterly", "Trimestrale"), ("semi-annually", "Semestrale"),
                ("annually", "Annuale"), ("weekly", "Settimanale"), ("bi-weekly", "Bisettimanale"),
                ("bi-monthly", "Bimestrale")]


class Contract(db.Model):
    """hr.version (Odoo 19) / hr.contract con i campi aggiunti dal modulo payroll."""
    __tablename__ = "contracts"
    _odoo = "hr.version"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(160), default="")
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    state = db.Column(db.String(20), default="draft")
    contract_type = db.Column(db.String(30), default="indeterminato")
    job_title = db.Column(db.String(120), default="")
    department = db.Column(db.String(80), default="")
    date_start = db.Column(db.Date, nullable=False, default=date.today)
    date_end = db.Column(db.Date)
    trial_date_end = db.Column(db.Date)
    resource_calendar_id = db.Column(db.Integer, db.ForeignKey("resource_calendars.id"))
    wage = db.Column(db.Float, default=0.0)  # retribuzione base mensile (minimo tabellare)
    struct_id = db.Column(db.Integer, db.ForeignKey("payroll_structures.id"))
    schedule_pay = db.Column(db.String(20), default="monthly")
    notes = db.Column(db.Text, default="")
    # --- estensione italiana
    ccnl = db.Column(db.String(160), default="")
    livello_id = db.Column(db.Integer, db.ForeignKey("livelli.id"))
    superminimo = db.Column(db.Float, default=0.0)
    scatti_n = db.Column(db.Integer, default=0)
    scatto_importo = db.Column(db.Float, default=0.0)
    part_time = db.Column(db.Float, default=100.0)
    mensilita = db.Column(db.Float, default=13.0)
    divisore_orario = db.Column(db.Float, default=173.0)
    add_reg_rata = db.Column(db.Float, default=0.0)
    add_com_rata = db.Column(db.Float, default=0.0)

    employee = db.relationship("Employee", back_populates="contract_ids")
    struct = db.relationship("PayrollStructure")
    resource_calendar = db.relationship("ResourceCalendar")
    livello = db.relationship("Livello")

    @property
    def retribuzione_mensile(self):
        pt = (self.part_time or 0) / 100
        return round(((self.wage or 0) + (self.superminimo or 0)
                      + (self.scatti_n or 0) * (self.scatto_importo or 0)) * pt, 2)

    @property
    def ral(self):
        """Retribuzione Annua Lorda."""
        return round(self.retribuzione_mensile * (self.mensilita or 13), 2)

    def is_overlapping_period(self, date_from, date_to):
        return self.date_start <= date_to and (self.date_end is None or self.date_end >= date_from)


# ===========================================================================
# payroll
# ===========================================================================
class SalaryRuleCategory(db.Model):
    __tablename__ = "salary_rule_categories"
    _odoo = "hr.salary.rule.category"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(30))
    parent_id = db.Column(db.Integer, db.ForeignKey("salary_rule_categories.id", ondelete="SET NULL"))
    note = db.Column(db.Text, default="")
    parent = db.relationship("SalaryRuleCategory", remote_side=[id], backref="children_ids")


class ContributionRegister(db.Model):
    __tablename__ = "contribution_registers"
    _odoo = "hr.contribution.register"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(160), nullable=False)
    partner_id = db.Column(db.Integer, db.ForeignKey("partners.id", ondelete="SET NULL"))
    note = db.Column(db.Text, default="")
    # --- estensione italiana: dove finisce nel modello F24
    f24_sezione = db.Column(db.String(10), default="")  # "" | erario | inps | inail
    f24_codice = db.Column(db.String(20), default="")
    f24_tipo = db.Column(db.String(10), default="debito")  # debito | credito
    partner = db.relationship("Partner")


structure_rule_rel = db.Table(
    "hr_structure_salary_rule_rel",
    db.Column("struct_id", db.Integer, db.ForeignKey("payroll_structures.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("rule_id", db.Integer, db.ForeignKey("salary_rules.id", ondelete="CASCADE"), primary_key=True),
)


class PayrollStructure(db.Model):
    __tablename__ = "payroll_structures"
    _odoo = "hr.payroll.structure"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(160), nullable=False)
    code = db.Column(db.String(40))
    note = db.Column(db.Text, default="")
    parent_id = db.Column(db.Integer, db.ForeignKey("payroll_structures.id", ondelete="SET NULL"))
    parent = db.relationship("PayrollStructure", remote_side=[id], backref="children_ids")
    rule_ids = db.relationship("SalaryRule", secondary=structure_rule_rel, back_populates="struct_ids",
                               order_by="(SalaryRule.sequence, SalaryRule.id)")

    def get_structure_with_parents(self):
        """Odoo: parent_id.get_structure_with_parents() + self (padri prima)."""
        chain, seen, s = [], set(), self
        while s is not None and s.id not in seen:
            seen.add(s.id)
            chain.insert(0, s)
            s = s.parent
        return chain


class SalaryRule(db.Model):
    __tablename__ = "salary_rules"
    _odoo = "hr.salary.rule"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(160), nullable=False)
    code = db.Column(db.String(40))
    sequence = db.Column(db.Integer, nullable=False, default=5, index=True)
    quantity = db.Column(db.Text, default="1.0")
    category_id = db.Column(db.Integer, db.ForeignKey("salary_rule_categories.id", ondelete="SET NULL"))
    active = db.Column(db.Boolean, default=True)
    appears_on_payslip = db.Column(db.Boolean, default=True)
    parent_rule_id = db.Column(db.Integer, db.ForeignKey("salary_rules.id", ondelete="SET NULL"), index=True)
    condition_select = db.Column(db.String(10), nullable=False, default="none")  # none | range | python
    condition_range = db.Column(db.Text, default="contract.wage")
    condition_python = db.Column(db.Text, default="")
    condition_range_min = db.Column(db.Float, default=0.0)
    condition_range_max = db.Column(db.Float, default=0.0)
    amount_select = db.Column(db.String(12), nullable=False, default="fix")  # percentage | fix | code
    amount_fix = db.Column(db.Float, default=0.0)
    amount_percentage = db.Column(db.Float, default=0.0)
    amount_python_compute = db.Column(db.Text, default="")
    amount_percentage_base = db.Column(db.Text, default="")
    register_id = db.Column(db.Integer, db.ForeignKey("contribution_registers.id", ondelete="SET NULL"))
    note = db.Column(db.Text, default="")

    category = db.relationship("SalaryRuleCategory", backref="salary_rules_ids")
    parent_rule = db.relationship("SalaryRule", remote_side=[id], backref="child_ids")
    register = db.relationship("ContributionRegister")
    struct_ids = db.relationship("PayrollStructure", secondary=structure_rule_rel, back_populates="rule_ids")
    input_ids = db.relationship("RuleInput", cascade="all, delete-orphan", back_populates="rule",
                                order_by="RuleInput.id")


class RuleInput(db.Model):
    __tablename__ = "rule_inputs"
    _odoo = "hr.rule.input"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    code = db.Column(db.String(40), nullable=False)
    input_id = db.Column(db.Integer, db.ForeignKey("salary_rules.id", ondelete="CASCADE"), nullable=False)
    rule = db.relationship("SalaryRule", back_populates="input_ids")


PAYSLIP_STATES = [("draft", "Bozza"), ("verify", "In attesa"), ("done", "Completata"), ("cancel", "Rifiutata")]


class PayslipRun(db.Model):
    __tablename__ = "payslip_runs"
    _odoo = "hr.payslip.run"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    name = db.Column(db.String(160), nullable=False)
    state = db.Column(db.String(10), default="draft")  # draft | close
    date_start = db.Column(db.Date, nullable=False)
    date_end = db.Column(db.Date, nullable=False)
    credit_note = db.Column(db.Boolean, default=False)
    struct_id = db.Column(db.Integer, db.ForeignKey("payroll_structures.id", ondelete="SET NULL"))
    struct = db.relationship("PayrollStructure")
    slip_ids = db.relationship("Payslip", back_populates="payslip_run")


class Payslip(db.Model):
    __tablename__ = "payslips"
    _odoo = "hr.payslip"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    struct_id = db.Column(db.Integer, db.ForeignKey("payroll_structures.id", ondelete="SET NULL"))
    name = db.Column(db.String(200), default="")
    number = db.Column(db.String(40))
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False,
                            index=True)
    date_from = db.Column(db.Date, nullable=False)
    date_to = db.Column(db.Date, nullable=False)
    state = db.Column(db.String(10), default="draft", index=True)
    paid = db.Column(db.Boolean, default=False)
    note = db.Column(db.Text, default="")
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="SET NULL"))
    credit_note = db.Column(db.Boolean, default=False)
    payslip_run_id = db.Column(db.Integer, db.ForeignKey("payslip_runs.id", ondelete="SET NULL"))
    hide_child_lines = db.Column(db.Boolean, default=False)
    hide_invisible_lines = db.Column(db.Boolean, default=False)
    compute_date = db.Column(db.Date)
    refunded_id = db.Column(db.Integer, db.ForeignKey("payslips.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=now)

    struct = db.relationship("PayrollStructure")
    employee = db.relationship("Employee", back_populates="slip_ids", foreign_keys=[employee_id])
    contract = db.relationship("Contract")
    payslip_run = db.relationship("PayslipRun", back_populates="slip_ids")
    refunded = db.relationship("Payslip", remote_side=[id])
    line_ids = db.relationship("PayslipLine", cascade="all, delete-orphan", back_populates="slip",
                               order_by="(PayslipLine.contract_id, PayslipLine.sequence, PayslipLine.id)")
    worked_days_line_ids = db.relationship("PayslipWorkedDays", cascade="all, delete-orphan",
                                           back_populates="payslip",
                                           order_by="(PayslipWorkedDays.sequence, PayslipWorkedDays.id)")
    input_line_ids = db.relationship("PayslipInput", cascade="all, delete-orphan", back_populates="payslip",
                                     order_by="(PayslipInput.sequence, PayslipInput.id)")

    @property
    def payslip_count(self):
        return len(self.line_ids)

    @property
    def dynamic_filtered_payslip_lines(self):
        lines = list(self.line_ids)
        if self.hide_child_lines:
            lines = [ln for ln in lines if not ln.parent_rule_id]
        if self.hide_invisible_lines:
            lines = [ln for ln in lines if ln.appears_on_payslip]
        return lines

    def get_salary_line_total(self, code):
        for line in self.line_ids:
            if line.code == code:
                return line.total
        return 0.0


class PayslipWorkedDays(db.Model):
    __tablename__ = "payslip_worked_days"
    _odoo = "hr.payslip.worked_days"
    id = db.Column(db.Integer, primary_key=True)
    payslip_id = db.Column(db.Integer, db.ForeignKey("payslips.id", ondelete="CASCADE"), index=True)
    name = db.Column(db.String(160), nullable=False)
    sequence = db.Column(db.Integer, default=10)
    code = db.Column(db.String(40), nullable=False)
    number_of_days = db.Column(db.Float, default=0.0)
    number_of_hours = db.Column(db.Float, default=0.0)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="SET NULL"))
    payslip = db.relationship("Payslip", back_populates="worked_days_line_ids")
    contract = db.relationship("Contract")


class PayslipInput(db.Model):
    __tablename__ = "payslip_inputs"
    _odoo = "hr.payslip.input"
    id = db.Column(db.Integer, primary_key=True)
    payslip_id = db.Column(db.Integer, db.ForeignKey("payslips.id", ondelete="CASCADE"), index=True)
    name = db.Column(db.String(160), nullable=False)
    sequence = db.Column(db.Integer, default=10)
    code = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Float, default=0.0)
    amount_qty = db.Column(db.Float, default=0.0)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="SET NULL"))
    payslip = db.relationship("Payslip", back_populates="input_line_ids")
    contract = db.relationship("Contract")


class PayslipLine(db.Model):
    """hr.payslip.line: eredita (copia) i campi della regola + quantità/tasso/importo/totale."""
    __tablename__ = "payslip_lines"
    _odoo = "hr.payslip.line"
    id = db.Column(db.Integer, primary_key=True)
    slip_id = db.Column(db.Integer, db.ForeignKey("payslips.id", ondelete="CASCADE"), index=True)
    salary_rule_id = db.Column(db.Integer, db.ForeignKey("salary_rules.id", ondelete="SET NULL"))
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"))
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="SET NULL"), index=True)
    name = db.Column(db.String(200))
    code = db.Column(db.String(40), index=True)
    sequence = db.Column(db.Integer)
    category_id = db.Column(db.Integer, db.ForeignKey("salary_rule_categories.id", ondelete="SET NULL"))
    appears_on_payslip = db.Column(db.Boolean, default=True)
    parent_rule_id = db.Column(db.Integer, db.ForeignKey("salary_rules.id", ondelete="SET NULL"))
    condition_select = db.Column(db.String(10))
    condition_python = db.Column(db.Text)
    condition_range = db.Column(db.Text)
    condition_range_min = db.Column(db.Float)
    condition_range_max = db.Column(db.Float)
    amount_select = db.Column(db.String(12))
    amount_fix = db.Column(db.Float)
    amount_python_compute = db.Column(db.Text)
    amount_percentage = db.Column(db.Float)
    amount_percentage_base = db.Column(db.Text)
    register_id = db.Column(db.Integer, db.ForeignKey("contribution_registers.id", ondelete="SET NULL"))
    quantity = db.Column(db.Float, default=1.0)
    rate = db.Column(db.Float, default=100.0)
    amount = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, default=0.0)

    slip = db.relationship("Payslip", back_populates="line_ids")
    salary_rule = db.relationship("SalaryRule", foreign_keys=[salary_rule_id])
    parent_rule = db.relationship("SalaryRule", foreign_keys=[parent_rule_id])
    category = db.relationship("SalaryRuleCategory")
    register = db.relationship("ContributionRegister")
    employee = db.relationship("Employee")
    contract = db.relationship("Contract")

    def compute_total(self):
        self.total = round(float(self.quantity or 0) * (self.amount or 0) * (self.rate or 0) / 100, 2)

    @property
    def parent_line(self):
        if not self.parent_rule_id:
            return None
        found = [ln for ln in self.slip.line_ids if ln.salary_rule_id == self.parent_rule_id
                 and ln.contract_id == self.contract_id]
        return found[0] if len(found) == 1 else None

    @property
    def date_from(self):
        return self.slip.date_from if self.slip else None


# ===========================================================================
# Estensione italiana: parametri e scaglioni (esposti alle regole come payroll.CODICE)
# ===========================================================================
class Parametro(db.Model):
    __tablename__ = "parametri"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    codice = db.Column(db.String(40), nullable=False)
    descrizione = db.Column(db.String(200), default="")
    valore = db.Column(db.Float, default=0.0)
    unita = db.Column(db.String(20), default="")


class ScaglioneIrpef(db.Model):
    __tablename__ = "scaglioni_irpef"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    da = db.Column(db.Float, nullable=False)
    a = db.Column(db.Float)
    aliquota = db.Column(db.Float, nullable=False)


class ProgressivoAnnuo(db.Model):
    """Progressivi dell'anno portati dal gestionale paghe precedente (mesi non elaborati qui).

    Servono al conguaglio IRPEF di fine anno, alla CU e al TFR: come quando un'azienda cambia
    software paghe a metà anno e carica i progressivi dei mesi già pagati."""
    __tablename__ = "progressivi_annui"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    anno = db.Column(db.Integer, nullable=False)
    mesi = db.Column(db.Integer, default=0)
    imponibile_previdenziale = db.Column(db.Float, default=0.0)
    inps_dipendente = db.Column(db.Float, default=0.0)
    imponibile_fiscale = db.Column(db.Float, default=0.0)
    irpef_trattenuta = db.Column(db.Float, default=0.0)
    addizionali = db.Column(db.Float, default=0.0)
    cuneo_indennita = db.Column(db.Float, default=0.0)
    quota_tfr = db.Column(db.Float, default=0.0)
    employee = db.relationship("Employee")


class Cessazione(db.Model):
    """Cessazione del rapporto di lavoro: prospetto del TFR e busta di liquidazione (struttura IT_CESS)."""
    __tablename__ = "cessazioni"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="SET NULL"))
    data = db.Column(db.Date, nullable=False)
    motivo = db.Column(db.String(40), default="dimissioni")
    preavviso_ok = db.Column(db.Boolean, default=True)
    prospetto = db.Column(db.Text, default="")  # JSON del calcolo del TFR, anno per anno
    payslip_id = db.Column(db.Integer, db.ForeignKey("payslips.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=now)
    employee = db.relationship("Employee")
    contract = db.relationship("Contract")
    payslip = db.relationship("Payslip")


class Contabilizzazione(db.Model):
    """Registrazione in contabilità generale delle paghe di un mese (prima nota)."""
    __tablename__ = "contabilizzazioni"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    anno = db.Column(db.Integer, nullable=False)
    mese = db.Column(db.Integer, nullable=False)
    data = db.Column(db.Date, nullable=False)
    righe = db.Column(db.Text, default="")  # JSON: [conto, descrizione, dare, avere]
    created_at = db.Column(db.DateTime, default=now)


class EsercizioSpunta(db.Model):
    """Passi dell'esercizio guidato spuntati a mano (le letture); gli altri si verificano sui dati."""
    __tablename__ = "esercizio_spunte"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = ws_fk()
    esercizio = db.Column(db.String(40), nullable=False)
    passo = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, default=now)


def month_bounds(d):
    first = d.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


# Tutti i modelli legati a un ambiente, nell'ordine in cui cancellarli.
WORKSPACE_MODELS = [EsercizioSpunta, Contabilizzazione, Cessazione, ProgressivoAnnuo, MailMail, Message, PayslipLine, PayslipWorkedDays, PayslipInput, Payslip, PayslipRun,
                    Leave, Familiare, Contract, Employee, RuleInput, SalaryRule, PayrollStructure,
                    SalaryRuleCategory, ContributionRegister, Partner, ResourceCalendarLeave,
                    ResourceCalendarAttendance, ResourceCalendar, LeaveType, Livello, Parametro,
                    ScaglioneIrpef]
