"""Esercizio passo passo (ottobre-dicembre 2026): ogni azione fatta dalle pagine, come un allievo, spunta il suo passo.

Copre anche le funzioni nuove: malattia con indennità INPS, ferie e permessi, cessazione con TFR, tredicesima,
conguaglio IRPEF e cuneo, F24 con i crediti INPS, Libro unico, contabilizzazione, Certificazione Unica."""
from datetime import date

from masterpayroll.blueprints.esercizio import P, stato_passi
from masterpayroll.models import (Cessazione, Contabilizzazione, Employee, LeaveType, Payslip, PayrollStructure,
                                  PayslipRun, User)
from masterpayroll import ensure_workspace
from masterpayroll.models import db


def _ws():
    return ensure_workspace(User.query.filter_by(username="docente").one())


def _stati(ws):
    return dict(zip([p["id"] for p in P], stato_passi(ws)))


def _emp(ws, matr):
    return Employee.query.filter_by(workspace_id=ws.id, registration_number=matr).one()


def _run(ws, d1, d2, struct=None):
    for r in PayslipRun.query.filter_by(workspace_id=ws.id, date_start=d1, date_end=d2):
        if (r.struct.code if r.struct else None) == struct:
            return r


def _slip(run, matr):
    return next(s for s in run.slip_ids if s.employee.registration_number == matr)


def test_esercizio_ottobre_dicembre(docente, app):
    ws = _ws()
    # la finestra c'è su ogni pagina, con il primo passo da fare
    h = docente.get("/").get_data(as_text=True)
    assert 'id="guida"' in h and "Esercizio passo passo" in h and "Parti da un ambiente pulito" in h
    assert all(not s for s in _stati(ws).values())
    for pid in ("pulito", "leggi-settembre"):
        docente.post("/esercizio/spunta", data={"passo": pid, "azione": "fatto"})
    assert _stati(ws)["pulito"] == "mano"
    tipi = {t.code: t.id for t in LeaveType.query.filter_by(workspace_id=ws.id)}

    def assenza(matr, tipo, d1, d2, ore=None):
        data = {"employee_id": _emp(ws, matr).id, "holiday_status_id": tipi[tipo], "date_from": d1, "date_to": d2,
                "approva": "on", "name": tipo}
        if ore:
            data.update(request_unit_hours="on", hour_from=ore[0], hour_to=ore[1])
        assert docente.post("/leaves/new", data=data).status_code == 302
    assenza("0008", "MAL", "2026-10-12", "2026-10-30")
    assert _stati(ws)["malattia"] == "auto"
    assenza("0003", "ROL", "2026-10-16", "2026-10-16", ("13", "17"))
    assenza("0001", "FERIE", "2026-10-29", "2026-10-30")
    st = _stati(ws)
    assert st["rol"] == st["ferie"] == "auto"

    def gruppo(nome, d1, d2, struct=""):
        sid = PayrollStructure.query.filter_by(workspace_id=ws.id, code=struct).one().id if struct else ""
        r = docente.post("/runs/new", data={"name": nome, "date_start": d1, "date_end": d2, "struct_id": sid})
        assert r.status_code == 302
        return int(r.headers["Location"].rstrip("/").split("/")[-1])

    def genera(run_id):
        ids = [e.id for e in Employee.query.filter_by(workspace_id=ws.id, active=True)]
        docente.post(f"/runs/{run_id}", data={"action": "generate", "employee_ids": ids})

    def conferma_e_chiudi(run_id):
        run = db.session.get(PayslipRun, run_id)
        docente.post("/payslips/bulk", data={"ids": [s.id for s in run.slip_ids], "action": "done", "next": f"/runs/{run_id}"})
        docente.post(f"/runs/{run_id}", data={"action": "close_payslip_run"})

    def apporto(slip, codice, valore):
        i = next(x for x in slip.input_line_ids if x.code == codice)
        assert docente.post(f"/payslips/{slip.id}", data={"action": "compute_sheet", f"in_amount_{i.id}": valore}).status_code == 302

    ott = gruppo("Ottobre 2026", "2026-10-01", "2026-10-31")
    assert _stati(ws)["gruppo-ott"] == "auto" and not _stati(ws)["genera-ott"]
    genera(ott)
    run = db.session.get(PayslipRun, ott)
    assert len(run.slip_ids) == 8 and _stati(ws)["genera-ott"] == "auto"
    apporto(_slip(run, "0001"), "STR25", "10")
    apporto(_slip(run, "0004"), "TRASF", "3")
    apporto(_slip(run, "0006"), "PREMIO", "300")
    st = _stati(ws)
    assert st["str-ott"] == st["trasf-ott"] == st["premio-ott"] == "auto"
    mor = _slip(run, "0008")
    assert mor.get_salary_line_total("MAL_RID") == -520.0 and mor.get_salary_line_total("MAL_INPS") == 520.0
    assert mor.get_salary_line_total("IMP_PREV") == 1430.0          # niente contributi sull'indennità INPS
    assert round(mor.get_salary_line_total("IMP_FISC"), 2) == round(1430 + mor.get_salary_line_total("INPS_DIP") + 520, 2)
    conferma_e_chiudi(ott)
    st = _stati(ws)
    assert st["conferma-ott"] == st["chiudi-ott"] == "auto"
    # F24 di ottobre: INPS dipendente + azienda meno l'indennità anticipata
    f24 = docente.get("/f24?anno=2026&mese=10").get_data(as_text=True)
    assert "Indennità anticipate per conto dell" in f24 and "520,00" in f24
    run = db.session.get(PayslipRun, ott)
    inps = sum(abs(ln.total) for s in run.slip_ids for ln in s.line_ids if ln.code in ("INPS_DIP", "INPS_AGG", "INPS_DITTA"))
    assert f"{inps - 520:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") in f24
    # contabilità: la prima nota quadra e si registra
    pn = docente.get("/contabilita?anno=2026&mese=10").get_data(as_text=True)
    import re as _re; assert "· quadra" in pn, _re.sub(r"\s+", " ", pn[pn.find("<tbody>"):pn.find("</tfoot>")])[:3000]
    docente.post("/contabilita", data={"anno": 2026, "mese": 10})
    assert Contabilizzazione.query.filter_by(workspace_id=ws.id, anno=2026, mese=10).count() == 1
    assert _stati(ws)["contab-ott"] == "auto"
    lul = docente.get("/lul?anno=2026&mese=10").get_data(as_text=True)
    assert "MA" in lul and "FE" in lul and "L4+PR" in lul
    fp = docente.get("/ferie-permessi?al=2026-10-31").get_data(as_text=True)
    assert "Bianchi Marco" in fp and "Ferie e permessi" in fp
    from masterpayroll.hr_service import contatori_ferie
    c = contatori_ferie(_emp(ws, "0001"), 2026, date(2026, 10, 31))
    assert c["ferie_godute"] == 16 and c["rol_goduti"] == 4 and c["ferie_maturate"] == round(160 * 10 / 12, 2)
    # visita medica periodica di Bianchi
    assert docente.post("/visite-mediche", data={"employee_id": _emp(ws, "0001").id, "data": "2026-10-20", "tipo": "periodica",
                                                 "esito": "idoneo", "scadenza": "2027-10-20", "medico": "Dott.ssa Rinaldi"}).status_code == 302
    assert _stati(ws)["visita-bianchi"] == "auto"
    # trasformazione di Ferri a tempo pieno dal 16 novembre (prima di generare novembre)
    from masterpayroll.models import Contract, ResourceCalendar
    full = ResourceCalendar.query.filter(ResourceCalendar.workspace_id == ws.id, ResourceCalendar.name.like("Tempo pieno%")).one()
    fer = _emp(ws, "0005")
    assert docente.post("/variazioni", data={"employee_id": fer.id, "dal": "2026-11-16", "calendar_id": full.id,
                                             "part_time": "100", "motivo": "trasformazione a tempo pieno"}).status_code == 302
    assert _stati(ws)["trasf-ferri"] == "auto"
    vers = sorted(fer.contract_ids, key=lambda c: c.date_start)
    assert vers[-1].part_time == 100 and vers[-2].date_end == date(2026, 11, 15) and vers[-2].state == "close"
    # novembre e cessazione di Esposito
    nov = gruppo("Novembre 2026", "2026-11-01", "2026-11-30")
    genera(nov)
    assert _stati(ws)["gruppo-nov"] == "auto"
    sf = _slip(db.session.get(PayslipRun, nov), "0005")
    assert len([w for w in sf.worked_days_line_ids if w.code == "WORK100"]) == 2
    assert sf.get_salary_line_total("BASIC") == round(2110 * 0.75, 2)
    assert sf.contract_id == vers[-1].id
    cf = contatori_ferie(fer, 2026, date(2026, 11, 30))
    assert cf["ferie_maturate"] == round(80 * 10 / 12 + 120 / 12, 2)
    # corso carrelli elevatori di Moretti
    r = docente.post("/formazione", data={"titolo": "Abilitazione all'uso dei carrelli elevatori (12 ore)", "categoria": "abilitazione",
                                          "ente": "Ente bilaterale", "data_inizio": "2026-11-09", "data_fine": "2026-11-10",
                                          "ore": "12", "costo": "240", "validita_anni": "5", "stato": "svolto"})
    corso_url = r.headers["Location"]
    docente.post(corso_url, data={"action": "add", "employee_id": _emp(ws, "0008").id, "esito": "superato"})
    assert _stati(ws)["corso-moretti"] == "auto"
    esp = _emp(ws, "0004")
    r = docente.post("/cessazioni", data={"employee_id": esp.id, "data": "2026-11-30", "motivo": "dimissioni"})
    assert Cessazione.query.filter_by(workspace_id=ws.id).count() == 0   # prima va confermata la busta di novembre
    conferma_e_chiudi(nov)
    assert _stati(ws)["chiudi-nov"] == "auto"
    pv = docente.get(f"/cessazioni?employee_id={esp.id}&data=2026-11-30&motivo=dimissioni").get_data(as_text=True)
    assert "Tassazione separata" in pv and "TFR netto" in pv
    r = docente.post("/cessazioni", data={"employee_id": esp.id, "data": "2026-11-30", "motivo": "dimissioni"})
    assert r.status_code == 302
    ces = Cessazione.query.filter_by(workspace_id=ws.id).one()
    liq = ces.payslip
    codici = {ln.code for ln in liq.line_ids}
    assert {"FERIE_NG", "RATEI13", "IRPEF_CESS", "TFR_LIQ", "RIT_TFR", "SOST_TFR", "NET"} <= codici
    assert not esp.active and ces.contract.date_end == date(2026, 11, 30)
    assert liq.get_salary_line_total("NET") > liq.get_salary_line_total("TFR_LIQ") * 0.6
    assert _stati(ws)["cessazione"] == "auto" and not _stati(ws)["liquidazione"]
    docente.post(f"/payslips/{liq.id}", data={"action": "action_payslip_done"})
    assert _stati(ws)["liquidazione"] == "auto"
    f24n = docente.get("/f24?anno=2026&mese=11").get_data(as_text=True)
    assert "1012" in f24n and "1713" in f24n
    # dicembre: tredicesima, poi buste ordinarie con il conguaglio
    t13 = gruppo("Tredicesima 2026", "2026-12-01", "2026-12-31", "IT13")
    genera(t13)
    assert len(db.session.get(PayslipRun, t13).slip_ids) == 7                  # Esposito è in archivio
    assert _slip(db.session.get(PayslipRun, t13), "0008").line_ids and _stati(ws)["gruppo-13"] == "auto"
    conferma_e_chiudi(t13)
    assert _stati(ws)["conferma-13"] == "auto"
    dic = gruppo("Dicembre 2026", "2026-12-01", "2026-12-31")
    genera(dic)
    run = db.session.get(PayslipRun, dic)
    mor = _slip(run, "0008")
    assert mor.get_salary_line_total("CONG_IRPEF") < 0 and mor.get_salary_line_total("CONG_CUNEO") > 0
    assert all(abs(_slip(run, m).get_salary_line_total("CONG_IRPEF")) < 100 for m in ("0002", "0006", "0007"))
    conferma_e_chiudi(dic)
    docente.post("/contabilita", data={"anno": 2026, "mese": 12})
    assert "· quadra" in docente.get("/contabilita?anno=2026&mese=12").get_data(as_text=True)
    cu = docente.get(f"/cu?anno=2026&employee_id={esp.id}").get_data(as_text=True)
    assert "TFR erogato" in cu and "Ritenute sul TFR" in cu
    st = _stati(ws)
    for pid, s in st.items():
        p = next(x for x in P if x["id"] == pid)
        if p["check"] is not None:
            assert s == "auto", pid
    # pagine nuove raggiungibili, finestra con il conteggio, area docente con il progresso
    sc = docente.get("/scadenzario?al=2026-12-31").get_data(as_text=True)
    sc = sc[sc.find("<th>Stato</th>"):sc.find("</table>", sc.find("<th>Stato</th>"))]
    assert "Galli Sara" in sc and "Ferri Anna" in sc and "Esposito" not in sc
    for url in ("/esercizio", "/cessazioni", f"/cessazioni/{ces.id}", "/lul", "/cu", "/contabilita", "/ferie-permessi",
                "/variazioni", "/visite-mediche", "/formazione", "/formazione/dipendenti", "/documenti", "/scadenzario",
                f"/employees/{fer.id}", corso_url, "/"):
        assert docente.get(url).status_code == 200, url
    assert "Guida" in docente.get("/docente/").get_data(as_text=True)


def test_ambiente_vecchio_si_aggiorna(app):
    """Un ambiente creato prima delle funzioni nuove riceve regole, categorie, registri e struttura IT_CESS."""
    from masterpayroll.models import Parametro, SalaryRule, db
    from masterpayroll.seed import FORMULE_PRECEDENTI
    ws = _ws()
    for code in ("MAL_RID", "MAL_INPS", "CONG_IRPEF", "CONG_CUNEO", "IRPEF_CESS", "TFR_LIQ"):
        r = SalaryRule.query.filter_by(workspace_id=ws.id, code=code).one()
        r.struct_ids = []
        db.session.delete(r)
    net = SalaryRule.query.filter_by(workspace_id=ws.id, code="NET").one()
    net.amount_python_compute = FORMULE_PRECEDENTI["NET"][0]
    basic = SalaryRule.query.filter_by(workspace_id=ws.id, code="BASIC").one()
    basic.amount_python_compute = FORMULE_PRECEDENTI["BASIC"][0]
    from masterpayroll.models import EmployeeCalendar, VisitaMedica
    EmployeeCalendar.query.filter_by(workspace_id=ws.id).delete()
    VisitaMedica.query.filter_by(workspace_id=ws.id).delete()
    Parametro.query.filter(Parametro.workspace_id == ws.id,
                           Parametro.codice.in_(("TFR_SOSTITUTIVA", "SCADENZE_PREAVVISO_GG"))).delete()
    db.session.commit()
    ws = _ws()   # ensure_workspace vede l'ambiente vecchio e lo aggiorna
    assert SalaryRule.query.filter_by(workspace_id=ws.id, code="CONG_IRPEF").count() == 1
    assert SalaryRule.query.filter_by(workspace_id=ws.id, code="NET").one().amount_python_compute == FORMULE_PRECEDENTI["NET"][1]
    assert SalaryRule.query.filter_by(workspace_id=ws.id, code="BASIC").one().amount_python_compute == FORMULE_PRECEDENTI["BASIC"][1]
    assert EmployeeCalendar.query.filter_by(workspace_id=ws.id).count() == 8
    assert VisitaMedica.query.filter_by(workspace_id=ws.id).count() == 7
    assert Payslip.query.filter_by(workspace_id=ws.id).count() == 8
