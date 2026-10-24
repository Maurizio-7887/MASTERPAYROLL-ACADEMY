"""Controllo del costo del personale: calcoli sulle buste di settembre e pagine."""
from masterpayroll.controllo import analisi, confronto_budget, budget_da_consuntivo, premio, PARAMETRI_DEFAULT


def test_analisi_settembre(ws):
    an = analisi(ws.id, 2026, 9, 9)
    assert not an["vuoto"] and len(an["dipendenti"]) == 8
    t = an["totale"]
    assert abs(t["costo"] - 26660.54) < 0.05            # somma della regola COSTO di settembre
    d = {x["e"].last_name: x for x in an["dipendenti"]}
    # Verdi: 176 h teoriche, 16 h di ferie, 8 h di permesso non retribuito
    assert d["Verdi"]["ore_teoriche"] == 176 and d["Verdi"]["ore_pagate"] == 168 and d["Verdi"]["ore_lavorate_tot"] == 152
    assert abs(d["Verdi"]["costo_orario_effettivo"] - 2693.38 / 152) < 0.01
    assert d["Verdi"]["assenteismo"] == 8 / 176           # le ferie non sono assenteismo
    # Bianchi: 8 ore di straordinario, 4 di ROL
    assert d["Bianchi"]["ore_str"] == 8 and d["Bianchi"]["ore_lavorate_tot"] == 176 - 4 + 8
    assert abs(d["Ferri"]["fte"] - 0.5) < 1e-9            # part-time al 50%
    assert abs(t["fte"] - 7.5) < 1e-9
    reparti = {r["reparto"]: r for r in an["reparti"]}
    assert reparti["Saldatura"]["dipendenti"] == 2


def test_budget_effetti_sommano(ws):
    an = analisi(ws.id, 2026, 9, 9)
    bud = budget_da_consuntivo(an)
    bud["Saldatura"] = {"fte": 2, "ore_mese": 360, "costo_mese": 5900}
    righe, tot = confronto_budget(an, bud)
    s = next(r for r in righe if r["reparto"] == "Saldatura")
    assert abs(s["eff_ore"] + s["eff_costo"] - s["scost"]) < 0.01
    assert s["scost"] > 0                                  # 6.174,65 effettivi contro 5.900 di budget


def test_premio(ws):
    an = analisi(ws.id, 2026, 9, 9)
    righe, tot = premio(an, dict(PARAMETRI_DEFAULT))
    d = {r["e"].last_name: r for r in righe}
    assert abs(d["Rossi"]["premio"] - 1200 * (0.4 + 0.2 + 0.4 * 0.8)) < 0.01
    assert d["Verdi"]["q_pres"] < 1                        # 4,5% di assenteismo, oltre la soglia del 4%
    assert abs(d["Ferri"]["premio"] - d["Rossi"]["premio"] / 2) < 0.01
    assert tot["costo_azienda"] > tot["premio"]


def test_pagine_controllo(docente, ws):
    for url in ("/controllo", "/controllo/reparti", "/controllo/assenze", "/controllo/budget", "/controllo/turnover",
                "/controllo/premio", "/controllo?anno=2026&da=1&a=3", "/controllo/export.csv?anno=2026&da=9&a=9"):
        r = docente.get(url)
        assert r.status_code == 200, url
    assert "Costo orario effettivo" in docente.get("/controllo?anno=2026&da=9&a=9").get_data(as_text=True)
    assert "Nessuna busta paga" in docente.get("/controllo?anno=2026&da=1&a=3").get_data(as_text=True)
    csv = docente.get("/controllo/export.csv?anno=2026&da=9&a=9").get_data(as_text=True)
    assert "Verdi" in csv and "costo_orario_effettivo" in csv
    righe = [r.split(";") for r in csv.lstrip("\ufeff").strip().splitlines()]
    intest = righe[0]
    for col in ("dipendente", "reparto", "fte", "lordo", "contributi", "tfr", "altri", "ore_teoriche", "ore_ferie_permessi",
                "ore_assenze", "ore_non_retribuite", "ore_straordinario"):
        assert col in intest, col
    verdi = dict(zip(intest, next(r for r in righe if "Verdi" in r[1])))
    assert verdi["ore_teoriche"] == "176,0" and verdi["ore_ferie_permessi"] == "16,0" and verdi["ore_non_retribuite"] == "8,0"
    r = docente.post("/controllo/budget?anno=2026&da=9&a=9", data={"azione": "proponi"})
    assert r.status_code == 302
    assert "Saldatura" in docente.get("/controllo/budget?anno=2026&da=9&a=9").get_data(as_text=True)
    r = docente.post("/controllo/parametri", data={"anno": 2026, "da": 9, "a": 9, "torna": "premio_risultato",
                                                   "premio_massimo": "2000"})
    assert r.status_code == 302
    assert 'name="premio_massimo" value="2000"' in docente.get("/controllo/premio?anno=2026&da=9&a=9").get_data(as_text=True)


def test_moduli_hanno_il_token_csrf(app, ws):
    c = app.test_client()
    c.post("/login", data={"username": "docente", "password": "prof123"})
    import re
    h = c.get("/controllo/budget?anno=2026&da=9&a=9").get_data(as_text=True)
    assert re.search(r'name="_csrf" value="[0-9a-f]{32}"', h)


def test_nessun_modulo_con_token_vuoto(app, ws):
    """Il macro csrf() importato senza contesto lasciava il token vuoto (POST rifiutati con 400)."""
    c = app.test_client()
    c.post("/login", data={"username": "docente", "password": "prof123"})
    for url in ("/", "/employees", "/payslips/new", "/runs/new", "/leaves/new", "/controllo/budget"):
        assert 'name="_csrf" value=""' not in c.get(url).get_data(as_text=True), url
