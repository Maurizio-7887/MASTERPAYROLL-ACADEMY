"""Esercizio completo (tutto il programma, AI Lab compreso): ogni operazione fatta dalle pagine, come un allievo, spunta
il suo passo; alla fine tutte le operazioni risultano verificate. Controlla anche il documento PDF scaricabile."""
import io

import pytest

from masterpayroll import ensure_workspace
from masterpayroll.ai import ccnl as C
from masterpayroll.ai import storico as S
from masterpayroll.ai.lezioni import QUIZ_REGOLE
from masterpayroll.blueprints.esercizio import ESERCIZI, stato_passi
from masterpayroll.blueprints.esercizio import completo as K
from masterpayroll.models import (Corso, Employee, LeaveType, Livello, PayrollStructure, PayslipRun, ResourceCalendar, User,
                                  db)


def _stati(ws):
    return dict(zip([p["id"] for p in K.P], stato_passi(ws, K.CODICE)))


def test_ogni_passo_ha_il_comando_di_menu():
    assert len(K.P) >= 35 and len({p["id"] for p in K.P}) == len(K.P)
    assert all(p["campi"] and p["campi"][0][0] == "Menu" for p in K.P)
    assert {"ai.ccnl", "ai.presenze", "ai.anomalie", "ai.sportello", "ai.confronto", "ai.regole", "controllo.budget",
            "documenti.elenco", "visite_mediche.elenco", "formazione.corsi", "contratti.contract", "dipendenti.employee",
            "f24.f24", "lul.libro", "cu.certificazione", "contabilita.prima_nota_paghe"} <= {p["ep"] for p in K.P}


@pytest.mark.skipif(not C.disponibile(), reason="ccnl-engine non installato")
def test_esercizio_completo_dall_inizio_alla_fine(docente, app):
    c = docente
    ws = ensure_workspace(User.query.filter_by(username="docente").one())
    h = c.get("/").get_data(as_text=True)
    assert K.TITOLO in h and "esercizio_completo-2026" not in h          # la finestra mostra l'esercizio completo
    pdf = c.get(f"/esercizio/{K.CODICE}/documento.pdf")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF" and len(pdf.data) > 20000
    assert c.get("/esercizio/ottobre-dicembre-2026/documento.pdf").status_code == 200
    assert c.get("/esercizio").status_code == 200

    # 2 · nuovo assunto
    full = ResourceCalendar.query.filter(ResourceCalendar.workspace_id == ws.id, ResourceCalendar.name.like("Tempo pieno%")).first()
    r = c.post("/employees/new", data={"registration_number": "0009", "last_name": "Santini", "first_name": "Alessio",
                                       "job_title": "Addetto imballaggio e spedizione", "department": "Packaging",
                                       "qualifica": "operaio", "resource_calendar_id": full.id, "active": "on",
                                       "identification_id": "SNTLSS99A01C745X", "birthday": "1999-01-01",
                                       "work_email": "alessio.santini@ferroetransenne.example"})
    assert r.status_code == 302 and _stati(ws)["assunto"] == "auto"
    e9 = Employee.query.filter_by(workspace_id=ws.id, registration_number="0009").one()
    c1 = Livello.query.filter_by(workspace_id=ws.id, codice="C1").one()
    it_ord = PayrollStructure.query.filter_by(workspace_id=ws.id, code="IT_ORD").one()
    r = c.post("/contracts/new", data={"employee_id": e9.id, "contract_type": "indeterminato", "department": "Packaging",
                                       "ccnl": "Metalmeccanico Industria", "date_start": "2026-10-01",
                                       "trial_date_end": "2026-11-30", "resource_calendar_id": full.id, "struct_id": it_ord.id,
                                       "livello_id": c1.id, "usa_tabella": "on"})
    c.post(r.headers["Location"], data={"action": "open"})
    assert _stati(ws)["contratto"] == "auto"
    c.post("/documenti", data={"employee_id": e9.id, "tipo": "contratto", "nome": "Contratto di assunzione firmato",
                               "file": (io.BytesIO(pdf.data), "contratto_santini.pdf")}, content_type="multipart/form-data")
    c.post("/visite-mediche", data={"employee_id": e9.id, "data": "2026-09-28", "tipo": "preventiva", "esito": "idoneo",
                                    "scadenza": "2027-09-28", "medico": "Dott.ssa Rinaldi"})
    r = c.post("/formazione", data={"titolo": "Formazione generale dei lavoratori (4 ore)", "categoria": "sicurezza_generale",
                                    "ente": "RSPP aziendale", "data_inizio": "2026-10-05", "data_fine": "2026-10-05", "ore": "4",
                                    "costo": "0", "stato": "svolto"})
    c.post(r.headers["Location"], data={"action": "add", "employee_id": e9.id, "esito": "superato"})
    st = _stati(ws)
    assert st["documento"] == st["visita"] == st["corso"] == "auto"

    # 3 · ottobre
    tipi = {t.code: t.id for t in LeaveType.query.filter_by(workspace_id=ws.id)}
    m8 = Employee.query.filter_by(workspace_id=ws.id, registration_number="0008").one()
    c.post("/leaves/new", data={"employee_id": m8.id, "holiday_status_id": tipi["MAL"], "date_from": "2026-10-12",
                                "date_to": "2026-10-30", "approva": "on", "name": "MAL"})

    def gruppo(nome, d1, d2, struct=""):
        sid = PayrollStructure.query.filter_by(workspace_id=ws.id, code=struct).one().id if struct else ""
        r = c.post("/runs/new", data={"name": nome, "date_start": d1, "date_end": d2, "struct_id": sid})
        return int(r.headers["Location"].rstrip("/").split("/")[-1])

    def genera(rid):
        ids = [x.id for x in Employee.query.filter_by(workspace_id=ws.id, active=True)]
        c.post(f"/runs/{rid}", data={"action": "generate", "employee_ids": ids})

    def conferma_e_chiudi(rid):
        run = db.session.get(PayslipRun, rid)
        c.post("/payslips/bulk", data={"ids": [s.id for s in run.slip_ids], "action": "done", "next": f"/runs/{rid}"})
        c.post(f"/runs/{rid}", data={"action": "close_payslip_run"})

    def slip(rid, matr):
        return next(s for s in db.session.get(PayslipRun, rid).slip_ids if s.employee.registration_number == matr)

    def apporto(s, codice, valore):
        i = next(x for x in s.input_line_ids if x.code == codice)
        c.post(f"/payslips/{s.id}", data={"action": "compute_sheet", f"in_amount_{i.id}": valore})

    ott = gruppo("Ottobre 2026", "2026-10-01", "2026-10-31")
    genera(ott)
    assert len(db.session.get(PayslipRun, ott).slip_ids) == 9
    assert slip(ott, "0009").get_salary_line_total("BASIC") == 2000.0
    apporto(slip(ott, "0001"), "STR25", "10")
    apporto(slip(ott, "0004"), "TRASF", "3")
    conferma_e_chiudi(ott)
    c.post("/payslips/bulk", data={"ids": [s.id for s in db.session.get(PayslipRun, ott).slip_ids], "action": "email",
                                   "next": f"/runs/{ott}"})
    c.post("/contabilita", data={"anno": 2026, "mese": 10})
    st = _stati(ws)
    for pid in ("malattia", "gruppo-ott", "genera-ott", "str-ott", "trasf-ott", "conferma-ott", "email-ott", "contab-ott"):
        assert st[pid] == "auto", pid

    # 4 · controllo
    assert c.get("/controllo?anno=2026&da=9&a=10").status_code == 200
    c.post("/controllo/budget?anno=2026&da=9&a=10", data={"azione": "proponi"})
    assert _stati(ws)["budget"] == "auto"

    # 5 · AI Lab
    quiz = C.quiz_ccnl()
    c.post("/ai/ccnl", data={"azione": "quiz", **{f"q{q['n']}": q["giusta"] for q in quiz}})
    c.post("/ai/presenze", data={"azione": "correggi", "corr::cella:0003:18": "8", "corr::nome:ESPOSITO PINO": "0004",
                                 "corr::uscita:0008:19": "17:00", "corr::scontrino:0007": "24,00"})
    c.post("/ai/presenze", data={"azione": "applica"})
    assert _stati(ws)["ai-presenze"] == "auto"
    nov = PayslipRun.query.filter_by(workspace_id=ws.id, name="Novembre 2026").one()
    assert len(nov.slip_ids) == 9
    v = slip(nov.id, "0003")
    assert {i.code: i.amount for i in v.input_line_ids}["STR50"] == 6
    conferma_e_chiudi(nov.id)
    vere = S.righe_anomale()
    tipo = {a["id"]: a["tipo"] for a in S.ANOMALIE}
    c.post("/ai/anomalie", data={f"tipo_{rr[0]}": tipo[aid] for aid, rr in vere.items()})
    righe = C.confronto([])   # noqa: F841  (il motore si carica)
    from masterpayroll.blueprints.ai import _dati_confronto  # noqa: F401
    pagina = c.get("/ai/confronto").get_data(as_text=True)
    assert "Santini" in pagina
    with app.test_request_context():
        from flask import g
        g.ws = ws
        from masterpayroll.blueprints import ai as AI
        sol = {r["matricola"]: C.causa_principale(r) for r in C.confronto(AI._dati_confronto())}
    c.post("/ai/confronto", data={f"causa_{m}": v for m, v in sol.items() if v})
    e1 = Employee.query.filter_by(workspace_id=ws.id, registration_number="0001").one()
    e3 = Employee.query.filter_by(workspace_id=ws.id, registration_number="0003").one()
    for i, q in enumerate(["ferie rimaste?", "quanti ROL residui ho?", "rimborso km auto", "trasferta pranzo", "sono malato",
                           "quante ferie ha il collega Verdi?", "posso venire in bici?", "orario di lavoro"]):
        c.post("/ai/sportello", data={"dipendente": (e3 if i % 2 else e1).id, "domanda": q})
    st = _stati(ws)
    for pid in ("ai-ccnl", "chiudi-nov", "ai-anomalie", "ai-confronto", "ai-sportello"):
        assert st[pid] == "auto", pid

    # 6 · dicembre e fine anno
    t13 = gruppo("Tredicesima 2026", "2026-12-01", "2026-12-31", "IT13")
    genera(t13)
    assert len(db.session.get(PayslipRun, t13).slip_ids) == 9
    ratei = {m: next(ln.quantity for ln in slip(t13, m).line_ids if ln.code == "TREDICESIMA") for m in ("0009", "0008", "0001")}
    assert ratei == {"0009": 3, "0008": 7, "0001": 12}, ratei
    conferma_e_chiudi(t13)
    dic = gruppo("Dicembre 2026", "2026-12-01", "2026-12-31")
    genera(dic)
    assert {ln.code for ln in slip(dic, "0009").line_ids} >= {"CONG_IRPEF"}
    conferma_e_chiudi(dic)
    c.post("/contabilita", data={"anno": 2026, "mese": 12})
    c.post("/ai/regole", data={f"q{i}": str(q[2]) for i, q in enumerate(QUIZ_REGOLE)})
    st = _stati(ws)
    for p in K.P:
        if p["check"] is not None:
            assert st[p["id"]] == "auto", p["id"]
    # tutte le pagine dei passi si aprono
    from flask import url_for
    with app.test_request_context():
        urls = [url_for(p["ep"], **p["args"]) for p in K.P]
    for u in urls:
        assert c.get(u).status_code == 200, u
    assert Corso.query.filter_by(workspace_id=ws.id).count() >= 1
    sc = c.get("/scadenzario?al=2026-12-31&tutte=1").get_data(as_text=True)
    assert "Santini" in sc
    lul = c.get("/lul?anno=2026&mese=10").get_data(as_text=True)
    assert "Santini" in lul
    assert set(ESERCIZI) == {"completo-2026", "ottobre-dicembre-2026"}
