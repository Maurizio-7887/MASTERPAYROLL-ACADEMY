"""Moduli HR aggiunti (OCA hr-19.0): documenti, storico orari, visite mediche, corsi."""
import io
from datetime import date

from masterpayroll.models import (Contract, DocumentoDipendente, Employee, EmployeeCalendar, ResourceCalendar, User,
                                  VisitaMedica)
from masterpayroll import ensure_workspace


def _ws():
    return ensure_workspace(User.query.filter_by(username="docente").one())


def _emp(ws, matr):
    return Employee.query.filter_by(workspace_id=ws.id, registration_number=matr).one()


def test_documenti_carica_scarica_elimina(docente, app):
    ws = _ws()
    e = _emp(ws, "0003")
    r = docente.post("/documenti", data={"employee_id": e.id, "tipo": "identita", "nome": "Carta d'identità",
                                         "scadenza": "2026-12-01", "file": (io.BytesIO(b"%PDF-1.4 prova"), "ci.pdf")},
                     content_type="multipart/form-data")
    assert r.status_code == 302
    d = DocumentoDipendente.query.filter_by(workspace_id=ws.id).one()
    assert d.dimensione == 14 and d.mimetype == "application/pdf"
    f = docente.get(f"/documenti/{d.id}/file")
    assert f.data == b"%PDF-1.4 prova" and f.headers["Content-Type"].startswith("application/pdf")
    sc = docente.get("/scadenzario?al=2026-11-15").get_data(as_text=True)
    assert "Carta d&#39;identità" in sc or "Carta d'identità" in sc
    # formato non ammesso
    docente.post("/documenti", data={"employee_id": e.id, "file": (io.BytesIO(b"<script>"), "x.html")},
                 content_type="multipart/form-data")
    assert DocumentoDipendente.query.filter_by(workspace_id=ws.id).count() == 1
    docente.post(f"/documenti/{d.id}/elimina")
    assert DocumentoDipendente.query.filter_by(workspace_id=ws.id).count() == 0


def test_variazione_solo_orario_e_blocchi(docente, app):
    ws = _ws()
    e = _emp(ws, "0003")
    part = ResourceCalendar.query.filter(ResourceCalendar.workspace_id == ws.id, ResourceCalendar.name.like("Part%")).one()
    n_contratti = Contract.query.filter_by(employee_id=e.id).count()
    # stessa percentuale: cambia solo l'orario, nessuna nuova versione del contratto
    docente.post("/variazioni", data={"employee_id": e.id, "dal": "2026-10-05", "calendar_id": part.id, "part_time": "100"})
    assert Contract.query.filter_by(employee_id=e.id).count() == n_contratti
    righe = EmployeeCalendar.query.filter_by(employee_id=e.id).order_by(EmployeeCalendar.date_start).all()
    assert len(righe) == 2 and righe[0].date_end == date(2026, 10, 4) and righe[1].calendar_id == part.id
    from masterpayroll.hr_service import calendario_al, work_days_data, calendari_periodo
    assert calendario_al(e, date(2026, 10, 2)).name.startswith("Tempo pieno")
    assert calendario_al(e, date(2026, 10, 6)).id == part.id
    giorni = work_days_data(calendari_periodo(e, date(2026, 10, 1), date(2026, 10, 31)), date(2026, 10, 1), date(2026, 10, 31))
    assert giorni["hours"] == 2 * 8 + 20 * 4   # 1-2 ottobre a 8 ore, poi 4 ore al giorno
    # settembre è confermato: una variazione che lo tocca viene rifiutata
    r = docente.post("/variazioni", data={"employee_id": e.id, "dal": "2026-09-15", "calendar_id": part.id, "part_time": "50"})
    assert r.status_code == 302 and Contract.query.filter_by(employee_id=e.id).count() == n_contratti


def test_visite_e_corsi_pagine(docente, app):
    ws = _ws()
    e = _emp(ws, "0005")
    r = docente.post("/visite-mediche", data={"employee_id": e.id, "data": "2026-11-20", "tipo": "preventiva",
                                              "esito": "idoneo_prescrizioni", "prescrizioni": ""})
    assert VisitaMedica.query.filter_by(employee_id=e.id).count() == 0   # con prescrizioni vanno scritte
    docente.post("/visite-mediche", data={"employee_id": e.id, "data": "2026-11-20", "tipo": "preventiva",
                                          "esito": "idoneo", "scadenza": "2031-11-20"})
    v = VisitaMedica.query.filter_by(employee_id=e.id).one()
    assert docente.get(f"/visite-mediche/{v.id}").status_code == 200
    sc = docente.get("/scadenzario?al=2026-12-31").get_data(as_text=True)
    sc = sc[sc.find("<th>Stato</th>"):sc.find("</table>", sc.find("<th>Stato</th>"))]
    assert "Ferri Anna" not in sc
    h = docente.get("/").get_data(as_text=True)
    assert "Scadenze del personale" in h
