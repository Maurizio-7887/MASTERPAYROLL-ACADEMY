"""Blueprint «ai» — AI Lab: l'intelligenza artificiale attorno al cedolino, in sei laboratori.

Pagine: panoramica, anomalie, presenze e note spese, assistente CCNL, seconda opinione (ccnl-engine), sportello HR, regole e
rischi. La logica è in masterpayroll/ai/; qui ci sono le rotte, lo stato dell'allievo (modello AiStato) e le verifiche delle
esercitazioni. Tutto funziona senza modello linguistico; con LLM_API_KEY e LLM_MODEL si attiva la riformulazione.
"""
import csv
import io
import json
from datetime import date

from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from ...ai import anomalie as A
from ...ai import ccnl as C
from ...ai import llm
from ...ai import presenze as P
from ...ai import sportello as SP
from ...ai import storico as S
from ...ai.lezioni import LABORATORI, LEZIONI, QUIZ_REGOLE
from ...models import AiStato, Contract, Employee, Leave, LeaveType, Livello, Payslip, PayslipRun, db, now
from ..comune import area, author, parse_float, ws_query

bp = area("ai", url_prefix="/ai")


# ---------------------------------------------------------------------------------------------------- stato
def stato(chiave, default=None):
    r = AiStato.query.filter_by(workspace_id=g.ws.id, chiave=chiave).first()
    return json.loads(r.valore) if r and r.valore else (default if default is not None else {})


def salva(chiave, valore):
    if g.ws_altrui:
        abort(403)
    r = AiStato.query.filter_by(workspace_id=g.ws.id, chiave=chiave).first()
    if r is None:
        r = AiStato(workspace_id=g.ws.id, chiave=chiave)
        db.session.add(r)
    r.valore = json.dumps(valore, default=str)
    r.updated_at = now()


def esito(lab, superato, dettaglio):
    es = stato("esiti")
    prima = es.get(lab, {}).get("superato")
    es[lab] = {"superato": bool(superato or prima), "ultimo": bool(superato), "dettaglio": dettaglio,
               "quando": date.today().isoformat()}
    salva("esiti", es)


def _lab(lab_id):
    return next(x for x in LABORATORI if x["id"] == lab_id)


def _render(tpl, lab_id, **kw):
    return render_template(f"ai/{tpl}", lab=_lab(lab_id), lezione=LEZIONI[lab_id], esiti=stato("esiti"),
                           llm_attivo=llm.attivo(), **kw)


def _dipendenti():
    """{matricola: «Cognome Nome»} dei dipendenti attivi dell'ambiente."""
    return {e.registration_number: f"{e.last_name} {e.first_name}"
            for e in ws_query(Employee).filter_by(active=True).order_by(Employee.registration_number) if e.registration_number}


# ---------------------------------------------------------------------------------------------------- panoramica
@bp.route("/")
def index():
    return render_template("ai/index.html", labs=sorted(LABORATORI, key=lambda x: x["n"]), esiti=stato("esiti"),
                           llm_attivo=llm.attivo(), engine=C.disponibile())


# ---------------------------------------------------------------------------------------------------- L3 anomalie
@bp.route("/anomalie", methods=["GET", "POST"])
def anomalie():
    righe = S.STORICO
    contaminazione = min(0.2, max(0.01, parse_float(request.values.get("contaminazione"), 0.05)))
    cand = A.candidati(righe, contaminazione)
    seg = stato("anomalie").get("segnalate", {})
    valutazione = None
    if request.method == "POST":
        seg = {str(v["r"]["riga"]): request.form.get(f"tipo_{v['r']['riga']}", "") for v in cand}
        seg = {k: t for k, t in seg.items() if t}
        valutazione = A.valuta_segnalazioni({int(k): t for k, t in seg.items()}, S.righe_anomale())
        salva("anomalie", {"segnalate": seg, "valutazione": valutazione})
        esito("anomalie", valutazione["superata"], f"{len(valutazione['trovate'])}/{valutazione['totale']} anomalie, "
                                                   f"{len(valutazione['falsi'])} falsi allarmi")
        db.session.commit()
        flash("Esercitazione superata: anomalie trovate e classificate." if valutazione["superata"] else
              "Non ancora: controlla le righe e i tipi.", "success" if valutazione["superata"] else "warning")
    else:
        valutazione = stato("anomalie").get("valutazione")
    mesi = [f"{a}-{m:02d}" for a, m in S.mesi()]
    rep = request.args.get("reparto", "Saldatura")
    base = request.args.get("base", "2026-07")
    conf = request.args.get("conf", "2026-09")
    var = A.variazione_reparto(righe, rep, base, conf) if base in mesi and conf in mesi else None
    filtro = request.args.get("dip", "")
    tabella = [r for r in righe if not filtro or r["matricola"] == filtro]
    return _render("anomalie.html", "anomalie", cand=cand, seg=seg, valutazione=valutazione, tipi=S.TIPI, mesi=mesi,
                   reparti=A.reparti(righe), rep=rep, base=base, conf=conf, var=var, tabella=tabella[-60:] if not filtro else tabella,
                   anagrafica=S.anagrafica_per_matricola(), filtro=filtro, contaminazione=contaminazione,
                   n_righe=len(righe), anomalie_docente=S.ANOMALIE if current_user.is_docente else None)


@bp.route("/anomalie/storico.csv")
def storico_csv():
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(S.COLONNE_CSV)
    for r in S.STORICO:
        w.writerow([str(r[c]).replace(".", ",") if isinstance(r[c], float) else r[c] for c in S.COLONNE_CSV])
    return Response(out.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=storico_costo_personale_ferro_transenne.csv"})


# ---------------------------------------------------------------------------------------------------- L2 presenze
def _file_caricati():
    caricati = stato("presenze_file")
    import base64
    return {k: base64.b64decode(v) for k, v in caricati.items()}


@bp.route("/presenze/file/<nome>")
def presenze_file(nome):
    if nome not in P.FILE:
        abort(404)
    fn, mime = P.FILE[nome]
    return Response(fn(), mimetype=mime, headers={"Content-Disposition": f"attachment; filename={nome}"})


@bp.route("/presenze", methods=["GET", "POST"])
def presenze():
    dip = _dipendenti()
    st = stato("presenze")
    corr = st.get("correzioni", {})
    if request.method == "POST":
        azione = request.form.get("azione")
        if azione == "carica":
            import base64
            caricati = stato("presenze_file")
            for nome in P.FILE:
                f = request.files.get(nome.replace(".", "_"))
                if f and f.filename:
                    caricati[nome] = base64.b64encode(f.read()).decode()
            salva("presenze_file", caricati)
            flash("File caricati: la lettura usa i tuoi file al posto degli esempi.", "success")
        elif azione == "esempi":
            salva("presenze_file", {})
            flash("Si torna ai file d'esempio.", "info")
        elif azione == "correggi":
            for k, v in request.form.items():
                if k.startswith("corr::"):
                    corr[k[6:]] = v.strip()
            st["correzioni"] = corr
            salva("presenze", st)
            flash("Correzioni salvate.", "success")
        elif azione == "azzera":
            salva("presenze", {})
            corr = {}
            flash("Correzioni azzerate.", "info")
        elif azione == "applica":
            ris = P.normalizza(dip, corr, _file_caricati())
            if ris["aperti"]:
                flash("Prima risolvi gli errori aperti.", "warning")
            else:
                n, errori = applica_novembre(ris)
                ok, diff = verifica_presenze()
                esito("presenze", ok, "apporti e assenze di novembre corretti" if ok else f"{len(diff)} differenze")
                for e in errori:
                    flash(e, "danger")
                flash(f"Apporti scritti in {n} buste di novembre e ricalcolate. " +
                      ("Esercitazione superata." if ok else "Ci sono ancora differenze con il risultato atteso."),
                      "success" if ok else "warning")
        db.session.commit()
        return redirect(url_for("ai.presenze"))
    ris = P.normalizza(dip, corr, _file_caricati())
    ok, diff = verifica_presenze()
    return _render("presenze.html", "presenze", ris=ris, dip=dip, corr=corr, file=P.FILE, caricati=stato("presenze_file"),
                   diff=diff, verificato=ok)


NOME_RUN = "Novembre 2026"
TAG_ASSENZA = "AI Lab · presenze di novembre"


def applica_novembre(ris):
    """Scrive assenze e apporti nelle buste di novembre 2026 (le crea con un gruppo se mancano) e le ricalcola."""
    from ... import payroll
    errori = []
    d1, d2 = date(2026, 11, 1), date(2026, 11, 30)
    emps = {e.registration_number: e for e in ws_query(Employee).filter_by(active=True) if e.registration_number}
    tipi = {t.code: t for t in ws_query(LeaveType)}
    for lv in ws_query(Leave).filter(Leave.name == TAG_ASSENZA):
        db.session.delete(lv)
    db.session.flush()
    for matr, codice, da, a, ore in ris["assenze"]:
        if matr in emps and codice in tipi:
            db.session.add(Leave(workspace_id=g.ws.id, name=TAG_ASSENZA, employee=emps[matr], holiday_status=tipi[codice],
                                 date_from=da, date_to=a, request_unit_hours=bool(ore), hour_from=ore[0] if ore else None,
                                 hour_to=ore[1] if ore else None, state="validate"))
    db.session.flush()
    run = ws_query(PayslipRun).filter_by(name=NOME_RUN, credit_note=False).first()
    if run is None:
        run = PayslipRun(workspace_id=g.ws.id, name=NOME_RUN, date_start=d1, date_end=d2)
        db.session.add(run)
        db.session.flush()
    gia = {s.employee_id for s in run.slip_ids}
    nuovi = [e for e in emps.values() if e.id not in gia and payroll.get_contracts(e, d1, d2)]
    if nuovi:
        _, err = payroll.generate_payslips(run, nuovi, author())
        errori += err
    n = 0
    for s in run.slip_ids:
        if s.state not in ("draft", "verify"):
            continue
        payroll.onchange_dates(s)
        vals = ris["apporti"].get(s.employee.registration_number, {})
        for i in s.input_line_ids:
            if i.code in vals:
                i.amount = vals[i.code]
        try:
            payroll.compute_sheet(s, author())
        except payroll.UserError as e:
            errori.append(str(e))
        n += 1
    return n, errori


def verifica_presenze():
    """Confronta gli apporti delle buste di novembre con il risultato atteso e controlla le assenze."""
    run = ws_query(PayslipRun).filter_by(name=NOME_RUN, credit_note=False).first()
    if run is None:
        return False, [("—", "buste di novembre non ancora create", 0, 0)]
    trovati = {}
    for s in run.slip_ids:
        trovati[s.employee.registration_number] = {i.code: i.amount for i in s.input_line_ids}
    diff = P.confronta_atteso({m: {c: v or 0.0 for c, v in x.items()} for m, x in trovati.items()})
    tipi = {t.id: t.code for t in ws_query(LeaveType)}
    emps = {e.id: e.registration_number for e in ws_query(Employee)}
    ass = {(emps.get(l.employee_id), tipi.get(l.holiday_status_id), l.date_from, l.date_to)
           for l in ws_query(Leave).filter(Leave.state == "validate", Leave.date_from >= date(2026, 11, 1),
                                           Leave.date_to <= date(2026, 11, 30))}
    for m, cod, da, a, _ in P.ASSENZE_ATTESE:
        if (m, cod, da, a) not in ass:
            diff.append((m, f"assenza {cod} {da:%d/%m}-{a:%d/%m}", 0, 1))
    return not diff, diff


# ---------------------------------------------------------------------------------------------------- L1 assistente CCNL
@bp.route("/ccnl", methods=["GET", "POST"])
def ccnl():
    if not C.disponibile():
        return _render("ccnl.html", "ccnl", manca=True)
    domanda = (request.values.get("domanda") or "").strip()
    cid = request.values.get("ccnl") or ""
    risultati, riformulata, motivo = [], None, None
    quiz = C.quiz_ccnl()
    risposte = stato("ccnl").get("risposte", {})
    if request.method == "POST" and request.form.get("azione") == "quiz":
        risposte = {str(q["n"]): request.form.get(f"q{q['n']}", "") for q in quiz}
        giuste = sum(1 for q in quiz if risposte.get(str(q["n"])) == q["giusta"])
        salva("ccnl", {"risposte": risposte, "giuste": giuste})
        esito("ccnl", giuste >= 8, f"{giuste}/10 risposte giuste")
        db.session.commit()
        flash(f"{giuste}/10 risposte giuste." + (" Esercitazione superata." if giuste >= 8 else " Servono almeno 8."),
              "success" if giuste >= 8 else "warning")
        return redirect(url_for("ai.ccnl", _anchor="esercitazione"))
    if domanda:
        risultati = C.cerca(domanda, cid or None)
        if risultati and request.values.get("llm") and llm.attivo():
            reg = stato("llm_registro", [])
            riformulata, motivo = llm.riformula(domanda, [s for _, s in risultati], reg)
            salva("llm_registro", reg[-200:])
            db.session.commit()
    return _render("ccnl.html", "ccnl", manca=False, domanda=domanda, cid=cid, contratti=C.CONTRATTI, risultati=risultati,
                   riformulata=riformulata, motivo=motivo, quiz=quiz, risposte=risposte, esempi=[q for q, *_ in C.DOMANDE])


@bp.route("/ccnl/schede")
def ccnl_schede():
    cid = request.args.get("ccnl") or "metalmeccanico-federmeccanica"
    if cid not in C.CONTRATTI or not C.disponibile():
        abort(404)
    return _render("ccnl_schede.html", "ccnl", cid=cid, contratti=C.CONTRATTI, schede=C.schede(cid))


# ---------------------------------------------------------------------------------------------------- L5 seconda opinione
def _dati_confronto():
    out = []
    for e in ws_query(Employee).filter_by(active=True).order_by(Employee.registration_number):
        c = e.contract_id
        if not c or not c.livello:
            continue
        out.append({"matricola": e.registration_number, "nome": e.name, "livello": c.livello.codice, "inizio": c.date_start,
                    "fine": c.date_end, "tipo": c.contract_type, "part_time": c.part_time or 100.0, "minimo": c.wage or 0.0,
                    "scatti_n": c.scatti_n or 0, "scatto": c.scatto_importo or 0.0, "superminimo": c.superminimo or 0.0})
    return out


@bp.route("/confronto", methods=["GET", "POST"])
def confronto():
    if not C.disponibile():
        return _render("confronto.html", "confronto", manca=True)
    righe = C.confronto(_dati_confronto())
    risposte = stato("confronto").get("risposte", {})
    if request.method == "POST":
        risposte = {r["matricola"]: request.form.get(f"causa_{r['matricola']}", "") for r in righe}
        valutabili = [r for r in righe if C.causa_principale(r)]
        giuste = sum(1 for r in valutabili if risposte.get(r["matricola"]) == C.causa_principale(r))
        ok = giuste >= len(valutabili) - 1
        salva("confronto", {"risposte": risposte, "giuste": giuste, "totale": len(valutabili)})
        esito("confronto", ok, f"{giuste}/{len(valutabili)} cause spiegate")
        db.session.commit()
        flash(f"{giuste}/{len(valutabili)} cause giuste." + (" Esercitazione superata." if ok else ""),
              "success" if ok else "warning")
        return redirect(url_for("ai.confronto"))
    return _render("confronto.html", "confronto", manca=False, righe=righe, cause=C.CAUSE, risposte=risposte,
                   soluzioni={r["matricola"]: C.causa_principale(r) for r in righe} if stato("confronto") else {})


# ---------------------------------------------------------------------------------------------------- L4 sportello
@bp.route("/sportello", methods=["GET", "POST"])
def sportello():
    emps = ws_query(Employee).filter_by(active=True).order_by(Employee.last_name).all()
    eid = request.values.get("dipendente", type=int) or (emps[0].id if emps else None)
    emp = next((e for e in emps if e.id == eid), None)
    registro = stato("sportello", [])
    risposta = None
    if request.method == "POST" and emp:
        domanda = (request.form.get("domanda") or "").strip()[:300]
        if request.form.get("azione") == "collaudo":
            for q, _atteso in SP.DOMANDE_TIPO:
                r, fonte, inoltro = SP.rispondi(q, emp, g.ws.id)
                registro.append({"dipendente": emp.name, "domanda": q, "risposta": r, "fonte": fonte, "inoltro": inoltro,
                                 "quando": now().isoformat(timespec="minutes")})
        elif domanda:
            r, fonte, inoltro = SP.rispondi(domanda, emp, g.ws.id)
            risposta = {"domanda": domanda, "risposta": r, "fonte": fonte, "inoltro": inoltro}
            registro.append({"dipendente": emp.name, **risposta, "quando": now().isoformat(timespec="minutes")})
        salva("sportello", registro[-300:])
        ok, dett = verifica_sportello(registro)
        esito("sportello", ok, dett)
        db.session.commit()
    ok, dett = verifica_sportello(registro)
    collaudo = [(q, atteso, SP.rispondi(q, emp, g.ws.id)) for q, atteso in SP.DOMANDE_TIPO] if emp else []
    return _render("sportello.html", "sportello", emps=emps, emp=emp, registro=list(reversed(registro[-30:])),
                   risposta=risposta, collaudo=collaudo, verifica=(ok, dett), policy=SP.POLICY)


def verifica_sportello(registro):
    """Superata con almeno 8 domande scritte a mano, per almeno 2 dipendenti diversi, tra cui un tentativo di sapere i dati
    di un collega (rifiutato) e una domanda inoltrata all'ufficio paghe."""
    tipo = {q for q, _ in SP.DOMANDE_TIPO}
    proprie = [r for r in registro if r["domanda"] not in tipo]
    dip = {r["dipendente"] for r in proprie}
    rifiuto = any(r["fonte"] == "regola di riservatezza" for r in proprie)
    inoltro = any(r["inoltro"] for r in proprie)
    ok = len(proprie) >= 8 and len(dip) >= 2 and rifiuto and inoltro
    return ok, (f"{len(proprie)} domande tue, {len(dip)} dipendenti, riservatezza {'provata' if rifiuto else 'da provare'}, "
                f"inoltro {'provato' if inoltro else 'da provare'}")


# ---------------------------------------------------------------------------------------------------- L6 regole e rischi
@bp.route("/regole", methods=["GET", "POST"])
def regole():
    risposte = stato("regole").get("risposte", {})
    if request.method == "POST":
        risposte = {str(i): request.form.get(f"q{i}", "") for i in range(len(QUIZ_REGOLE))}
        giuste = sum(1 for i, q in enumerate(QUIZ_REGOLE) if risposte.get(str(i)) == str(q[2]))
        salva("regole", {"risposte": risposte, "giuste": giuste})
        esito("regole", giuste >= 8, f"{giuste}/10 risposte giuste")
        db.session.commit()
        flash(f"{giuste}/10 risposte giuste." + (" Esercitazione superata." if giuste >= 8 else " Servono almeno 8."),
              "success" if giuste >= 8 else "warning")
        return redirect(url_for("ai.regole"))
    return _render("regole.html", "regole", quiz=QUIZ_REGOLE, risposte=risposte, corretto=bool(stato("regole")))
