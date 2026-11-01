"""AI Lab: storico con anomalie, metodi di controllo, presenze → apporti, assistente CCNL, seconda opinione, sportello."""
from datetime import date

import pytest

from masterpayroll.ai import anomalie as A
from masterpayroll.ai import ccnl as C
from masterpayroll.ai import presenze as P
from masterpayroll.ai import sportello as SP
from masterpayroll.ai import storico as S
from masterpayroll.models import AiStato, Employee, Payslip, PayslipRun, db


def test_storico_e_anomalie_trovate_dai_tre_metodi():
    assert len({r["mese"] for r in S.STORICO}) == 24
    vere = S.righe_anomale()
    assert len(vere) == 7 and all(vere.values())
    coperte = {v["r"]["riga"] for v in A.candidati(S.STORICO)}
    assert {x for rr in vere.values() for x in rr} <= coperte
    regole = {(r["riga"], t) for r, t, _ in A.regole(S.STORICO)}
    assert all(any(riga in rr for riga, _ in regole) for aid, rr in vere.items() if aid != 1)   # gli straordinari no
    z = {r["riga"] for r, *_ in A.zscore(S.STORICO)}
    assert vere[1][0] in z                                                                     # li trova la statistica
    v = A.variazione_reparto(S.STORICO, "Saldatura", "2026-07", "2026-09")
    assert v["var_costo_ora_perc"] > 10 and v["prime_tre"][0]["voce"] == "contributi c/azienda"
    assert round(v["effetto_ore"] + v["effetto_costo_orario"], 2) == v["delta"]


def test_valutazione_segnalazioni():
    vere = S.righe_anomale()
    tipo = {a["id"]: a["tipo"] for a in S.ANOMALIE}
    giuste = {rr[0]: tipo[aid] for aid, rr in vere.items()}
    assert A.valuta_segnalazioni(giuste, vere)["superata"]
    meta = dict(list(giuste.items())[:3])
    assert not A.valuta_segnalazioni(meta, vere)["superata"]


DIP = {"0001": "Bianchi Marco", "0002": "Rossi Laura", "0003": "Verdi Luca", "0004": "Esposito Giuseppe", "0005": "Ferri Anna",
       "0006": "Conti Davide", "0007": "Galli Sara", "0008": "Moretti Paolo"}


def test_presenze_si_fermano_sui_dubbi_e_poi_tornano():
    n = P.normalizza(DIP)
    chiavi = {e["chiave"] for e in n["aperti"]}
    assert {"cella:0003:18", "nome:ESPOSITO PINO", "uscita:0008:19", "scontrino:0007"} == chiavi
    corr = {e["chiave"]: e.get("proposta") for e in n["aperti"]} | {"scontrino:0007": "24,00"}
    n2 = P.normalizza(DIP, corr)
    assert not n2["aperti"] and not P.confronta_atteso(n2["apporti"])
    assert sorted((m, c) for m, c, *_ in n2["assenze"]) == [("0002", "FERIE"), ("0002", "ROL"), ("0003", "MAL")]


def test_laboratorio_presenze_scrive_le_buste_di_novembre(docente, ws):
    c = docente
    assert c.get("/ai/").status_code == 200
    r = c.get("/ai/presenze")
    assert r.status_code == 200 and "ESPOSITO PINO" in r.get_data(as_text=True)
    for nome in P.FILE:
        assert c.get(f"/ai/presenze/file/{nome}").status_code == 200
    form = {"azione": "correggi", "corr::cella:0003:18": "8", "corr::nome:ESPOSITO PINO": "0004",
            "corr::uscita:0008:19": "17:00", "corr::scontrino:0007": "24,00"}
    c.post("/ai/presenze", data=form)
    c.post("/ai/presenze", data={"azione": "applica"})
    run = PayslipRun.query.filter_by(workspace_id=ws.id, name="Novembre 2026").one()
    imp = {s.employee.registration_number: {i.code: i.amount for i in s.input_line_ids} for s in run.slip_ids}
    assert imp["0001"]["STR25"] == 12.5 and imp["0004"]["TRASF"] == 3 and imp["0007"]["RIMBORSI"] == 207.5
    assert all(s.line_ids for s in run.slip_ids)
    esiti = AiStato.query.filter_by(workspace_id=ws.id, chiave="esiti").one().valore
    assert '"presenze": {"superato": true' in esiti


def test_pagine_e_esercitazioni(docente, ws):
    c = docente
    for p in ("/ai/anomalie", "/ai/anomalie?dip=0001", "/ai/regole", "/ai/sportello"):
        assert c.get(p).status_code == 200, p
    csv_ = c.get("/ai/anomalie/storico.csv").get_data(as_text=True)
    assert csv_.count("\n") == len(S.STORICO) + 1
    vere = S.righe_anomale()
    tipo = {a["id"]: a["tipo"] for a in S.ANOMALIE}
    r = c.post("/ai/anomalie", data={f"tipo_{rr[0]}": tipo[aid] for aid, rr in vere.items()}, follow_redirects=True)
    assert "Esercitazione superata" in r.get_data(as_text=True)
    from masterpayroll.ai.lezioni import QUIZ_REGOLE
    r = c.post("/ai/regole", data={f"q{i}": str(q[2]) for i, q in enumerate(QUIZ_REGOLE)}, follow_redirects=True)
    assert "10/10" in r.get_data(as_text=True)


def test_sportello_risponde_solo_sui_propri_dati(docente, ws):
    e = Employee.query.filter_by(workspace_id=ws.id, registration_number="0003").one()
    r, fonte, _ = SP.rispondi("Quante ferie mi sono rimaste?", e, ws.id)
    assert fonte == "Ferie e permessi" and "ore" in r
    assert SP.rispondi("Quante ferie ha il mio collega Bianchi?", e, ws.id)[1] == "regola di riservatezza"
    assert SP.rispondi("Posso portare il cane in ufficio?", e, ws.id)[2] is True
    for q, atteso in SP.DOMANDE_TIPO:
        assert SP.rispondi(q, e, ws.id)[1] == atteso, q
    c = docente
    altro = Employee.query.filter_by(workspace_id=ws.id, registration_number="0001").one()
    domande = ["ferie rimaste?", "quanti ROL residui ho?", "rimborso km auto", "trasferta pranzo", "sono malato",
               "quante ferie ha il collega Verdi?", "posso venire in bici?", "orario di lavoro"]
    for i, q in enumerate(domande):
        c.post("/ai/sportello", data={"dipendente": (e if i % 2 else altro).id, "domanda": q})
    assert "superata" in c.get("/ai/sportello").get_data(as_text=True)


ccnl_ok = pytest.mark.skipif(not C.disponibile(), reason="ccnl-engine non installato")


@ccnl_ok
def test_assistente_ccnl_trova_la_scheda_con_la_fonte():
    for q, cid, tema in C.DOMANDE:
        top = C.cerca(q, cid)[0][1]
        assert top["titolo"].startswith(tema), q
    quiz = C.quiz_ccnl()
    assert len(quiz) == 10 and all(q["giusta"] in q["opzioni"] and len(q["opzioni"]) == 3 for q in quiz)
    assert not C.cerca("xyz qwerty", None)


@ccnl_ok
def test_pagine_ccnl_e_seconda_opinione(docente, ws):
    c = docente
    assert "Art." in c.get("/ai/ccnl?domanda=straordinario+metalmeccanico").get_data(as_text=True)
    assert c.get("/ai/ccnl/schede?ccnl=commercio-confcommercio").status_code == 200
    quiz = C.quiz_ccnl()
    r = c.post("/ai/ccnl", data={"azione": "quiz", **{f"q{q['n']}": q["giusta"] for q in quiz}}, follow_redirects=True)
    assert "10/10" in r.get_data(as_text=True)
    page = c.get("/ai/confronto").get_data(as_text=True)
    assert "2.064,88" in page                                     # minimo C2 da giugno 2026 nel motore
    righe = C.confronto([{"matricola": "0001", "nome": "Bianchi", "livello": "C2", "inizio": date(2018, 4, 3), "fine": None,
                          "tipo": "indeterminato", "part_time": 100.0, "minimo": 2060.0, "scatti_n": 2, "scatto": 25.5,
                          "superminimo": 0.0}])
    assert C.causa_principale(righe[0]) == "scatti di anzianità non aggiornati"
