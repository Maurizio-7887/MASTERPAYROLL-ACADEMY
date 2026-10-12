import re

from masterpayroll.models import db, Cedolino, Elaborazione, Regola, Struttura, User


def test_pagine_docente(docente):
    for url in ["/", "/dipendenti", "/dipendenti?mostra=tutti", "/elaborazioni", "/strutture", "/tabelle",
                "/riepilogo", "/riepilogo?anno=2026&mese=9", "/guida", "/esercitazioni", "/docente/",
                "/docente/esercitazioni", "/docente/report.csv", "/dipendenti/nuovo"]:
        r = docente.get(url)
        assert r.status_code == 200, url
    assert "1001" in docente.get("/riepilogo?anno=2026&mese=9").get_data(as_text=True)


def test_flusso_allievo(app, docente):
    r = docente.post("/docente/", data={"azione": "crea", "classe": "UF4", "elenco": "Rossi Mario\nBianchi Giulia"})
    html = r.get_data(as_text=True)
    m = re.search(r"<code>(mario\.rossi)</code></td><td><code>([a-z0-9]{8})</code>", html)
    assert m, html[:2000]
    allievo = app.test_client()
    assert allievo.post("/login", data={"username": m.group(1), "password": m.group(2)}).status_code == 302
    assert allievo.get("/docente/").status_code == 403

    # nuova elaborazione di ottobre con straordinari
    r = allievo.post("/elaborazioni", data={"anno": 2026, "mese": 10, "tipo": "ordinaria"})
    el_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
    with app.app_context():
        el = db.session.get(Elaborazione, el_id)
        ceds = {c.dipendente.cognome: c.id for c in el.cedolini}
        ws_allievo = el.workspace_id
    assert len(ceds) == 8
    allievo.post(f"/elaborazioni/{el_id}", data={"azione": "calcola", f"in_{ceds['Bianchi']}_STR25": "10"})
    with app.app_context():
        b = db.session.get(Cedolino, ceds["Bianchi"])
        assert b.stato == "calcolato" and b.importo("STR25") > 0
    for url in [f"/elaborazioni/{el_id}", f"/cedolini/{ceds['Bianchi']}", f"/cedolini/{ceds['Bianchi']}/stampa",
                f"/elaborazioni/{el_id}/stampa", "/riepilogo?anno=2026&mese=10&calcolati=1"]:
        assert allievo.get(url).status_code == 200, url

    # nuova regola: indennità di turno per la saldatura
    with app.app_context():
        st = Struttura.query.filter_by(workspace_id=ws_allievo, codice="METAL_ORD").one()
        cat_comp = next(r.categoria_id for r in st.regole if r.codice == "STR25")
        st_id = st.id
    r = allievo.post(f"/strutture/{st_id}/regola/nuova", data={
        "sequenza": 75, "codice": "IND_TURNO", "nome": "Indennità di turno", "categoria_id": cat_comp,
        "condizione": "employee.reparto == 'Saldatura'", "formula": "50", "stampa": "on", "attiva": "on"})
    assert r.status_code == 302
    allievo.post(f"/strutture/{st_id}", data={"azione": "ricalcola"})
    with app.app_context():
        assert db.session.get(Cedolino, ceds["Esposito"]).importo("IND_TURNO") == 50
        assert db.session.get(Cedolino, ceds["Bianchi"]).riga("IND_TURNO") is None

    # formula sbagliata: non salva
    r = allievo.post(f"/strutture/{st_id}/regola/nuova", data={
        "sequenza": 76, "codice": "HACK", "nome": "x", "categoria_id": cat_comp, "formula": "__import__('os')"})
    assert r.status_code == 200 and "non ammess" in r.get_data(as_text=True)

    # isolamento: l'allievo non vede i dati del docente
    with app.app_context():
        doc_ced = Cedolino.query.filter(Cedolino.workspace_id != ws_allievo).first()
    assert allievo.get(f"/cedolini/{doc_ced.id}").status_code == 404

    # conferma, riepilogo, tredicesima
    allievo.post(f"/elaborazioni/{el_id}", data={"azione": "conferma"})
    r = allievo.post("/elaborazioni", data={"anno": 2026, "mese": 12, "tipo": "tredicesima"})
    el13 = int(r.headers["Location"].rstrip("/").split("/")[-1])
    allievo.post(f"/elaborazioni/{el13}", data={"azione": "calcola"})
    with app.app_context():
        e = db.session.get(Elaborazione, el13)
        assert all(c.stato == "calcolato" for c in e.cedolini), [c.errore for c in e.cedolini]
        rossi = next(c for c in e.cedolini if c.dipendente.cognome == "Rossi")
        assert rossi.importo("TREDICESIMA") == rossi.contratto.retribuzione_mensile

    # esercitazione consegnata e ore registrate
    allievo.post("/esercitazioni", data={"esercitazione_id": 1, "nota": "fatto"})
    assert "mario.rossi" in docente.get("/docente/report.csv").get_data(as_text=True)

    # il docente entra nell'ambiente dell'allievo
    with app.app_context():
        uid = User.query.filter_by(username="mario.rossi").one().id
    docente.post(f"/docente/apri/{uid}")
    assert "ambiente dell'allievo" in docente.get("/").get_data(as_text=True)
    docente.post("/docente/torna")

    # ripristino ambiente
    allievo.post("/ambiente/reset", data={"conferma": "RIPRISTINA"})
    with app.app_context():
        assert Elaborazione.query.filter_by(workspace_id=ws_allievo).count() == 1
        assert not Regola.query.filter_by(workspace_id=ws_allievo, codice="IND_TURNO").first()


def test_tabelle_e_dipendente(docente, app):
    r = docente.post("/dipendenti/nuovo", data={
        "matricola": "0009", "cognome": "Neri", "nome": "Elisa", "qualifica": "impiegato", "attivo": "on",
        "tipo": "indeterminato", "livello_id": "", "minimo": "2.000,00", "superminimo": "0", "scatti_n": "0",
        "scatto_importo": "0", "part_time": "100", "contratto_attivo": "on"})
    assert r.status_code == 302
    assert docente.get(r.headers["Location"]).status_code == 200
    r = docente.post("/tabelle", data={"sezione": "scaglioni", "nuovo_da": "", "nuovo_aliq": ""})
    assert r.status_code == 302
