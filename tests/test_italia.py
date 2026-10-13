"""Localizzazione italiana: numeri del cedolino verificati a mano."""
from datetime import date

import pytest

from masterpayroll import payroll
from masterpayroll.fiscale import (cuneo_detrazione, cuneo_indennita, detrazione_coniuge, detrazione_figli,
                                   detrazione_lavoro, irpef_annua)
from masterpayroll.hr_service import italian_holidays
from masterpayroll.models import Employee, Payslip
from masterpayroll.safe_eval import SafeEvalError, safe_eval


def slip_of(ws, cognome, mese=9):
    return (Payslip.query.join(Employee, Payslip.employee_id == Employee.id)
            .filter(Payslip.workspace_id == ws.id, Employee.last_name == cognome,
                    Payslip.date_from == date(2026, mese, 1)).one())


def tot(slip, code):
    return slip.get_salary_line_total(code)


def test_irpef_e_detrazioni():
    assert irpef_annua(20000) == pytest.approx(4600)
    assert irpef_annua(40000) == pytest.approx(6440 + 12000 * 0.33)
    assert irpef_annua(60000) == pytest.approx(6440 + 22000 * 0.33 + 10000 * 0.43)
    assert detrazione_lavoro(12000) == 1955
    assert detrazione_lavoro(30000) == pytest.approx(1910 * 20000 / 22000 + 65)
    assert detrazione_coniuge(10000) == pytest.approx(800 - 110 * 10000 / 15000)
    assert detrazione_coniuge(30000) == 710
    assert detrazione_figli(30000, 1) == pytest.approx(950 * 65000 / 95000)
    assert cuneo_indennita(8000) == pytest.approx(568)
    assert cuneo_detrazione(36000) == pytest.approx(500)


def test_pasqua_e_festivita():
    feste = dict((d, n) for d, n in italian_holidays(2026))
    assert feste[date(2026, 4, 5)] == "Pasqua" and date(2026, 4, 6) in feste
    assert dict(italian_holidays(2027))[date(2027, 3, 28)] == "Pasqua"


def test_settembre_rossi(ws):
    s = slip_of(ws, "Rossi")
    assert s.state == "done" and s.payslip_run.name == "Settembre 2026"
    assert tot(s, "GROSS") == pytest.approx(2410 + 150 + 3 * 32.5)
    assert tot(s, "IMP_PREV") == 2658
    assert tot(s, "INPS_DIP") == pytest.approx(-round(2658 * 0.0919, 2))
    imp_fisc = tot(s, "GROSS") + tot(s, "INPS_DIP")
    assert tot(s, "IMP_FISC") == pytest.approx(imp_fisc)
    assert tot(s, "IRPEF_LORDA") == pytest.approx(round(irpef_annua(imp_fisc * 12) / 12, 2))
    detr = tot(s, "DETR_LAV") + tot(s, "DETR_FAM") + tot(s, "DETR_CUNEO")
    assert tot(s, "DETR_FAM") > 0  # figlio di 23 anni a carico
    assert tot(s, "IRPEF") == pytest.approx(-(tot(s, "IRPEF_LORDA") - detr), abs=0.01)
    netto = tot(s, "GROSS") + tot(s, "INPS_DIP") + tot(s, "IRPEF") - 45 - 18
    assert tot(s, "NET") == pytest.approx(netto, abs=0.01)


def test_settembre_casi_particolari(ws):
    verdi = slip_of(ws, "Verdi")
    wd = {w.code: w for w in verdi.worked_days_line_ids}
    assert wd["WORK100"].number_of_days == 22 and wd["PNR"].number_of_hours == -8 and wd["FERIE"].number_of_days == -2
    assert tot(verdi, "PNR") == pytest.approx(-8 * tot(verdi, "ORARIA"), abs=0.01)
    galli = slip_of(ws, "Galli")
    assert tot(galli, "INPS_AGG") < 0  # oltre la 1ª fascia: regola figlia di INPS_DIP
    ferri = slip_of(ws, "Ferri")
    assert tot(ferri, "TRATT_INT") == 100 and tot(ferri, "IND_CUNEO") > 0
    esposito = slip_of(ws, "Esposito")
    assert tot(esposito, "TRASF") == pytest.approx(2 * 46.48) and tot(esposito, "RIMBORSI") == 45
    assert tot(esposito, "DETR_FAM") == pytest.approx(round((690 + 950 * (95000 - tot(esposito, "REDD_ANNUO"))
                                                              / 95000 * 0.5) / 12, 2), abs=0.02)
    conti = slip_of(ws, "Conti")
    assert tot(conti, "ANTICIPO") == -200


def test_tredicesima_con_struttura_del_gruppo(ws):
    from masterpayroll.models import PayrollStructure, PayslipRun, db
    it13 = PayrollStructure.query.filter_by(workspace_id=ws.id, code="IT13").one()
    run = PayslipRun(workspace_id=ws.id, name="Tredicesima 2026", date_start=date(2026, 12, 1),
                     date_end=date(2026, 12, 31), struct_id=it13.id)
    db.session.add(run)
    db.session.flush()
    emps = Employee.query.filter_by(workspace_id=ws.id).all()
    slips, errors = payroll.generate_payslips(run, emps)
    assert not errors
    by = {s.employee.last_name: s for s in slips}
    rossi = by["Rossi"]
    assert tot(rossi, "TREDICESIMA") == pytest.approx(rossi.contract.retribuzione_mensile, abs=0.05)
    moretti = by["Moretti"]  # assunto il 1/6/2026: 7 ratei
    assert [ln.quantity for ln in moretti.line_ids if ln.code == "TREDICESIMA"] == [7]
    assert tot(rossi, "IRPEF13") < 0 and tot(rossi, "NET") > 0


def test_safe_eval_blocca_codice_pericoloso():
    for src in ["__import__('os')", "().__class__", "open('x')", "lambda: 1", "import os", "9 ** 999",
                "'{0.__class__}'.format(1)", "'a' * 10**8", "[0] * 10**9", "x = 0\nwhile True:\n    x += 1"]:
        mode = "exec" if "\n" in src or src.startswith("import") else "eval"
        with pytest.raises(SafeEvalError):
            safe_eval(src, {}, mode=mode)
    ld = {}
    safe_eval("result = sum([i * 2 for i in range(5)])\nresult_qty = 3", ld, mode="exec")
    assert ld["result"] == 20 and ld["result_qty"] == 3 and "__builtins__" not in ld


def test_record_proxy_read_only(ws):
    s = slip_of(ws, "Rossi")
    from masterpayroll.browsable import wrap
    emp = wrap(s.employee)
    assert emp.name == "Rossi Laura"
    with pytest.raises(SafeEvalError):
        safe_eval("employee.workspace_id", {"employee": emp})
    with pytest.raises(SafeEvalError):
        safe_eval("x = 1\nemployee.name = 'x'", {"employee": emp}, mode="exec")
