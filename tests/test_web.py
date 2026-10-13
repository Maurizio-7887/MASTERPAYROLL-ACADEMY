"""Flussi completi via interfaccia web, isolamento tra allievi e area docente."""
import re

from masterpayroll.models import (Contract, Employee, Leave, LeaveType, MailMail, PayrollStructure, Payslip,
                                  PayslipRun, SalaryRule, SalaryRuleCategory, User, Workspace, db)

PAGES = ["/", "/payslips", "/payslips?group=employee", "/payslips?group=month&state=done", "/payslips/new", "/runs",
         "/runs/new", "/payslip-lines", "/payslip-lines?righe=employee&colonne=category", "/f24", "/outbox",
         "/settings", "/structures", "/structures/new", "/categories", "/categories/new", "/rules",
         "/rules?vista=albero", "/rules/new", "/registers", "/registers/new", "/tabelle", "/guida", "/employees",
         "/employees/new", "/contracts", "/contracts/new", "/calendars", "/calendars/new", "/leaves", "/leaves/new",
         "/leave-types", "/holidays", "/esercitazioni", "/docente/", "/docente/esercitazioni", "/docente/report.csv"]


def test_tutte_le_pagine(docente, ws):
    for url in PAGES:
        assert docente.get(url).status_code == 200, url
    for model, prefix in ((Payslip, "/payslips/"), (PayslipRun, "/runs/"), (PayrollStructure, "/structures/"),
                          (SalaryRule, "/rules/"), (SalaryRuleCategory, "/categories/"), (Employee, "/employees/"),
                          (Contract, "/contracts/")):
        for obj in model.query.filter_by(workspace_id=ws.id).limit(4):
            assert docente.get(f"{prefix}{obj.id}").status_code == 200, (prefix, obj.id)
    slip = Payslip.query.filter_by(workspace_id=ws.id).first()
    for url in (f"/payslips/{slip.id}/lines", f"/payslips/{slip.id}/pdf", f"/payslips/{slip.id}/pdf?report=details"):
        r = docente.get(url)
        assert r.status_code == 200
    assert docente.get(f"/payslips/{slip.id}/pdf").data.startswith(b"%PDF")


def _id(resp):
    return int(resp.headers["Location"].rstrip("/").split("/")[-1].split("?")[0])


def test_flusso_busta_da_interfaccia(docente, ws):
    emp = Employee.query.filter_by(workspace_id=ws.id, last_name="Bianchi").one()
    r = docente.post("/payslips/new", data={"employee_id": emp.id, "date_from": "2026-10-01", "date_to": "2026-10-31"})
    sid = _id(r)
    slip = db.session.get(Payslip, sid)
    wd = {w.code: w for w in slip.worked_days_line_ids}
    assert wd["WORK100"].number_of_days == 22 and "GLOBAL" not in wd  # il 4 ottobre 2026 è domenica
    inp = {i.code: i for i in slip.input_line_ids}
    data = {"action": "compute_sheet", "name": slip.name, "date_from": "2026-10-01", "date_to": "2026-10-31",
            "contract_id": slip.contract_id, "struct_id": slip.struct_id, f"in_amount_{inp['STR25'].id}": "10"}
    docente.post(f"/payslips/{sid}", data=data)
    db.session.expire_all()
    slip = db.session.get(Payslip, sid)
    assert slip.state == "verify" and slip.get_salary_line_total("STR25") > 0
    docente.post(f"/payslips/{sid}", data={"action": "action_payslip_done"})
    db.session.expire_all()
    assert db.session.get(Payslip, sid).state == "done"
    r = docente.post(f"/payslips/{sid}", data={"action": "refund_sheet"})
    refund = db.session.get(Payslip, _id(r))
    assert refund.credit_note and refund.state == "done"
    # cancellare una busta completata senza l'impostazione → messaggio di errore, stato invariato
    r = docente.post(f"/payslips/{sid}", data={"action": "action_payslip_cancel"}, follow_redirects=True)
    assert "Non si può annullare" in r.get_data(as_text=True)
    docente.post(f"/payslips/{sid}", data={"action": "email"})
    assert MailMail.query.filter_by(workspace_id=ws.id, payslip_id=sid, state="simulated").count() == 1
    assert "Email" in docente.get(f"/payslips/{sid}").get_data(as_text=True)


def test_gruppo_e_cambio_stato(docente, ws):
    r = docente.post("/runs/new", data={"name": "Ottobre 2026", "date_start": "2026-10-01", "date_end": "2026-10-31"})
    rid = _id(r)
    emps = [e.id for e in Employee.query.filter_by(workspace_id=ws.id)]
    docente.post(f"/runs/{rid}", data={"action": "generate", "employee_ids": emps})
    run = db.session.get(PayslipRun, rid)
    assert len(run.slip_ids) == 8 and all(s.state == "verify" for s in run.slip_ids)
    docente.post("/payslips/bulk", data={"action": "done", "ids": [s.id for s in run.slip_ids]})
    db.session.expire_all()
    assert all(s.state == "done" for s in db.session.get(PayslipRun, rid).slip_ids)
    r = docente.post("/payslips/bulk", data={"action": "pdf", "ids": [s.id for s in run.slip_ids]})
    assert r.data.startswith(b"%PDF")
    docente.post(f"/runs/{rid}", data={"action": "close_payslip_run"})
    assert db.session.get(PayslipRun, rid).state == "close"
    assert "1001" in docente.get("/f24?anno=2026&mese=10").get_data(as_text=True)


def test_regola_nuova_con_figlia(docente, ws):
    st = PayrollStructure.query.filter_by(workspace_id=ws.id, code="IT_ORD").one()
    alw = SalaryRuleCategory.query.filter_by(workspace_id=ws.id, code="ALW").one()
    r = docente.post("/rules/new", data={
        "name": "Indennità di turno", "code": "IND_TURNO", "sequence": "25", "category_id": alw.id, "active": "on",
        "appears_on_payslip": "on", "condition_select": "python",
        "condition_python": "result = employee.department == 'Saldatura'", "amount_select": "fix",
        "amount_fix": "50", "quantity": "1.0", "struct_ids_present": "1", "struct_ids": [st.id]})
    parent = SalaryRule.query.filter_by(workspace_id=ws.id, code="IND_TURNO").one()
    r = docente.post("/rules/new", data={
        "name": "Maggiorazione notturna", "code": "NOTTE", "sequence": "26", "category_id": alw.id, "active": "on",
        "appears_on_payslip": "on", "condition_select": "none", "amount_select": "fix", "amount_fix": "20",
        "quantity": "1.0", "parent_rule_id": parent.id, "struct_ids_present": "1"})
    assert r.status_code == 302
    r = docente.post("/rules/new", data={"name": "x", "code": "HACK", "condition_select": "none",
                                         "amount_select": "code", "amount_python_compute": "__import__('os')"})
    assert r.status_code == 200 and "non ammesso" in r.get_data(as_text=True)
    run = PayslipRun.query.filter_by(workspace_id=ws.id).first()
    for s in run.slip_ids:
        s.state = "verify"
    db.session.commit()
    docente.post("/payslips/bulk", data={"action": "verify", "ids": [s.id for s in run.slip_ids]})
    db.session.expire_all()
    by = {s.employee.last_name: s for s in db.session.get(PayslipRun, run.id).slip_ids}
    assert by["Esposito"].get_salary_line_total("IND_TURNO") == 50
    assert by["Esposito"].get_salary_line_total("NOTTE") == 20
    assert by["Bianchi"].get_salary_line_total("NOTTE") == 0  # figlia saltata: padre non applicabile


def test_assenza_e_riestrai(docente, ws):
    emp = Employee.query.filter_by(workspace_id=ws.id, last_name="Moretti").one()
    pnr = LeaveType.query.filter_by(workspace_id=ws.id, code="PNR").one()
    docente.post("/leaves/new", data={"employee_id": emp.id, "holiday_status_id": pnr.id, "date_from": "2026-10-12",
                                      "date_to": "2026-10-12", "approva": "on"})
    assert Leave.query.filter_by(employee_id=emp.id, state="validate").count() == 1
    r = docente.post("/payslips/new", data={"employee_id": emp.id, "date_from": "2026-10-01", "date_to": "2026-10-31"})
    sid = _id(r)
    slip = db.session.get(Payslip, sid)
    docente.post(f"/payslips/{sid}", data={"action": "compute_sheet"})
    db.session.expire_all()
    slip = db.session.get(Payslip, sid)
    assert slip.get_salary_line_total("PNR") < 0


def test_impostazioni_e_tabelle(docente, ws):
    docente.post("/settings", data={"allow_cancel_payslips": "on", "leaves_positive": "on"})
    db.session.expire_all()
    w = db.session.get(Workspace, ws.id)
    assert w.allow_cancel_payslips and w.leaves_positive and not w.prevent_compute_on_confirm
    assert docente.post("/tabelle", data={"sezione": "parametri", "nuovo_codice": "BONUS_X",
                                          "nuovo_valore": "1.234,50"}).status_code == 302
    from masterpayroll.models import Parametro
    assert Parametro.query.filter_by(workspace_id=ws.id, codice="BONUS_X").one().valore == 1234.5


def test_dipendente_familiare_contratto(docente, ws):
    r = docente.post("/employees/new", data={"registration_number": "0009", "last_name": "Neri", "first_name": "Elisa",
                                             "qualifica": "impiegato", "active": "on", "fam_new_nome": "Neri Paolo",
                                             "fam_new_rel": "coniuge", "fam_new_perc": "100"})
    emp = db.session.get(Employee, _id(r))
    assert emp.familiari[0].relazione == "coniuge"
    st = PayrollStructure.query.filter_by(workspace_id=ws.id, code="IT_ORD").one()
    r = docente.post("/contracts/new", data={"employee_id": emp.id, "date_start": "2026-10-01", "wage": "2.110,00",
                                             "struct_id": st.id, "contract_type": "indeterminato", "part_time": "100"})
    con = db.session.get(Contract, _id(r))
    assert con.state == "draft" and con.wage == 2110
    docente.post(f"/contracts/{con.id}", data={"action": "open"})
    db.session.expire_all()
    assert db.session.get(Contract, con.id).state == "open"
    r = docente.post("/payslips/new", data={"employee_id": emp.id, "date_from": "2026-10-01", "date_to": "2026-10-31"})
    sid = _id(r)
    docente.post(f"/payslips/{sid}", data={"action": "compute_sheet"})
    db.session.expire_all()
    assert db.session.get(Payslip, sid).get_salary_line_total("DETR_FAM") > 0


def test_allievi_isolati_e_docente(app, docente, ws):
    r = docente.post("/docente/", data={"azione": "crea", "classe": "UF4", "elenco": "Rossi Mario\nBianchi Giulia"})
    html = r.get_data(as_text=True)
    m = re.search(r"<code>(mario\.rossi)</code></td><td><code>([a-z0-9]{8})</code>", html)
    assert m
    allievo = app.test_client()
    assert allievo.post("/login", data={"username": m.group(1), "password": m.group(2)}).status_code == 302
    assert allievo.get("/docente/").status_code == 403
    assert allievo.get("/payslips").status_code == 200
    u = User.query.filter_by(username="mario.rossi").one()
    mine = Payslip.query.filter_by(workspace_id=u.workspace.id).count()
    assert mine == 8
    other = Payslip.query.filter_by(workspace_id=ws.id).first()
    assert allievo.get(f"/payslips/{other.id}").status_code == 404
    assert allievo.post("/payslips/bulk", data={"action": "done", "ids": [other.id]}).status_code == 404
    allievo.post("/esercitazioni", data={"esercitazione_id": 1, "nota": "fatto"})
    assert "mario.rossi" in docente.get("/docente/report.csv").get_data(as_text=True)
    docente.post(f"/docente/apri/{u.id}")
    assert "ambiente dell'allievo" in docente.get("/").get_data(as_text=True)
    docente.post("/docente/torna")
    allievo.post("/ambiente/reset", data={"conferma": "RIPRISTINA"})
    assert Payslip.query.filter_by(workspace_id=u.workspace.id).count() == 8
