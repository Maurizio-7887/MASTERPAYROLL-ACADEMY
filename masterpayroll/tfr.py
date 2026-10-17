"""Cessazione del rapporto: prospetto del TFR (art. 2120 c.c.) e busta di liquidazione (struttura IT_CESS).

USO DIDATTICO. Semplificazioni dichiarate nel prospetto:
* per gli anni passati la retribuzione annua è quella del contratto attuale (non lo storico reale);
* rivalutazione annua al tasso della pagina Tabelle (TFR_RIVALUTAZIONE), imposta sostitutiva 17% trattenuta
  ogni anno dal fondo; quella dell'anno di cessazione si trattiene nella busta di liquidazione;
* contributo aggiuntivo IVS 0,50% della retribuzione utile, detratto dalla quota dell'anno;
* tassazione separata con l'aliquota media sul reddito di riferimento (TFR × 12 / mesi di servizio).
"""
import calendar as _cal
import json
from datetime import date

from . import fiscale, payroll
from .hr_service import contatori_ferie
from .models import (Cessazione, Parametro, PayrollStructure, Payslip, PayslipInput, ProgressivoAnnuo,
                     ScaglioneIrpef, db)

MOTIVI = [("dimissioni", "Dimissioni del lavoratore"), ("licenziamento", "Licenziamento"),
          ("fine_termine", "Scadenza del contratto a termine"), ("pensionamento", "Pensionamento"),
          ("consensuale", "Risoluzione consensuale")]


def _par(ws_id, codice, default):
    p = Parametro.query.filter_by(workspace_id=ws_id, codice=codice).first()
    return p.valore if p else default


def mesi_servizio(inizio, fine):
    """Mesi interi di servizio: si conta il mese se lavorato per almeno 15 giorni."""
    n = 0
    y, m = inizio.year, inizio.month
    while (y, m) <= (fine.year, fine.month):
        last = _cal.monthrange(y, m)[1]
        a = max(date(y, m, 1), inizio)
        b = min(date(y, m, last), fine)
        if b >= a and (b - a).days + 1 >= 15:
            n += 1
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return n


def inizio_rapporto(employee):
    return min((c.date_start for c in employee.contract_ids if c.state in ("open", "close")), default=None)


def prospetto(employee, contract, data_cess, ws_id):
    r2 = lambda x: round(x + 0.0, 2)  # noqa: E731
    tasso = _par(ws_id, "TFR_RIVALUTAZIONE", 2.5) / 100
    sost = _par(ws_id, "TFR_SOSTITUTIVA", 17.0) / 100
    divisore = _par(ws_id, "TFR_DIVISORE", 13.5)
    inizio = inizio_rapporto(employee) or contract.date_start
    ret_annua = contract.retribuzione_mensile * (contract.mensilita or 13)
    anni, fondo, riv_tot = [], 0.0, 0.0
    for y in range(inizio.year, data_cess.year):
        mesi = mesi_servizio(max(inizio, date(y, 1, 1)), date(y, 12, 31))
        utile = ret_annua * mesi / 12
        quota = utile / divisore
        contr = utile * 0.005
        riv = fondo * tasso
        imp_sost = riv * sost
        fondo = fondo + riv - imp_sost + quota - contr
        riv_tot += riv - imp_sost
        anni.append({"anno": y, "mesi": mesi, "retribuzione": r2(utile), "quota": r2(quota), "contributo": r2(contr),
                     "rivalutazione": r2(riv), "sostitutiva": r2(imp_sost), "fondo": r2(fondo)})
    # anno della cessazione: progressivi del gestionale precedente + buste completate di quest'anno
    y = data_cess.year
    quota_anno = utile_anno = 0.0
    for p in ProgressivoAnnuo.query.filter_by(workspace_id=ws_id, employee_id=employee.id, anno=y):
        quota_anno += p.quota_tfr or 0
        utile_anno += p.imponibile_previdenziale or 0
    for s in Payslip.query.filter(Payslip.workspace_id == ws_id, Payslip.employee_id == employee.id,
                                  Payslip.state == "done", Payslip.date_from >= date(y, 1, 1),
                                  Payslip.date_to <= data_cess):
        sg = -1 if s.credit_note else 1
        quota_anno += sg * s.get_salary_line_total("TFR")
        utile_anno += sg * s.get_salary_line_total("IMP_PREV")
    contr_anno = utile_anno * 0.005
    mesi_anno = mesi_servizio(max(inizio, date(y, 1, 1)), data_cess)
    riv_anno = fondo * tasso * mesi_anno / 12
    # competenze della busta di liquidazione: ferie e permessi residui, ratei di tredicesima
    cont = contatori_ferie(employee, y, data_cess, _par(ws_id, "FERIE_ORE_ANNO", 160.0), _par(ws_id, "ROL_ORE_ANNO", 104.0))
    ferie_ore = max(0.0, cont["residuo_totale"])
    ratei = payroll.ratei_tredicesima(contract, data_cess)
    oraria = contract.retribuzione_mensile / (contract.divisore_orario or 173)
    liq_utile = ferie_ore * oraria + ratei * contract.retribuzione_mensile / 12
    quota_liq = liq_utile / divisore - liq_utile * 0.005
    tfr_lordo = fondo + riv_anno + quota_anno - contr_anno + quota_liq
    rivalutazioni = riv_tot + riv_anno
    imponibile = tfr_lordo - rivalutazioni
    mesi_tot = mesi_servizio(inizio, data_cess)
    scaglioni = [(s.da, s.a, s.aliquota) for s in
                 ScaglioneIrpef.query.filter_by(workspace_id=ws_id).order_by(ScaglioneIrpef.da)] or None
    aliquota = fiscale.aliquota_media_tfr(imponibile, mesi_tot, scaglioni)
    riferimento = imponibile * 12 / mesi_tot if mesi_tot else 0
    return {
        "inizio": inizio.isoformat(), "inizio_it": inizio.strftime("%d/%m/%Y"), "data": data_cess.isoformat(), "retribuzione_annua": r2(ret_annua),
        "tasso": tasso * 100, "anni": anni, "fondo_31_12": r2(fondo),
        "anno": {"anno": y, "mesi": mesi_anno, "quote": r2(quota_anno), "utile": r2(utile_anno),
                 "contributo": r2(contr_anno), "rivalutazione": r2(riv_anno), "quota_liquidazione": r2(quota_liq)},
        "ferie": cont, "ferie_ore": r2(ferie_ore), "ratei_13": ratei,
        "tfr_lordo": r2(tfr_lordo), "rivalutazioni": r2(rivalutazioni), "imponibile": r2(imponibile),
        "mesi_servizio": mesi_tot, "riferimento": r2(riferimento), "aliquota": aliquota,
        "ritenuta": r2(imponibile * aliquota / 100), "sostitutiva_anno": r2(riv_anno * sost),
        "tfr_netto": r2(tfr_lordo - imponibile * aliquota / 100 - riv_anno * sost),
    }


def cessa(employee, contract, data_cess, motivo, ws, author=""):
    """Chiude il contratto, crea la busta di liquidazione IT_CESS con gli apporti del prospetto, archivia il dipendente."""
    if contract.date_start > data_cess:
        raise payroll.UserError("La cessazione non può precedere l'inizio del contratto.")
    if Cessazione.query.filter_by(workspace_id=ws.id, employee_id=employee.id).first():
        raise payroll.UserError(f"Per {employee.name} la cessazione è già stata registrata.")
    struct = PayrollStructure.query.filter_by(workspace_id=ws.id, code="IT_CESS").first()
    if not struct:
        raise payroll.UserError("Manca la struttura IT_CESS: ricarica la pagina per aggiornare l'ambiente.")
    d1 = data_cess.replace(day=1)
    if not Payslip.query.filter(Payslip.workspace_id == ws.id, Payslip.employee_id == employee.id,
                                Payslip.state == "done", Payslip.credit_note.is_(False),
                                Payslip.date_from >= d1, Payslip.date_to <= data_cess).first():
        raise payroll.UserError(f"Prima conferma la busta ordinaria di {payroll.MESI[data_cess.month]} di "
                                f"{employee.name}: la liquidazione viene dopo l'ultimo stipendio.")
    contract.date_end = data_cess
    pro = prospetto(employee, contract, data_cess, ws.id)
    slip = Payslip(workspace_id=ws.id, employee=employee, contract_id=contract.id, struct_id=struct.id,
                   date_from=d1, date_to=data_cess, name="")
    db.session.add(slip)
    db.session.flush()
    valori = {"FERIE_ORE": pro["ferie_ore"], "RATEI_13": pro["ratei_13"], "TFR_LORDO": pro["tfr_lordo"],
              "TFR_RIVAL": pro["rivalutazioni"], "TFR_RIV_ANNO": pro["anno"]["rivalutazione"], "TFR_ALIQ": pro["aliquota"]}
    for i in payroll.inputs_for(struct, [contract]):
        slip.input_line_ids.append(PayslipInput(amount=valori.get(i["code"], 0.0), **i))
    payroll.compute_name(slip)
    slip.name = f"Liquidazione di fine rapporto di {employee.name}"
    db.session.flush()
    payroll.compute_sheet(slip, author)
    contract.state = "close"
    employee.active = False
    c = Cessazione(workspace_id=ws.id, employee=employee, contract=contract, data=data_cess, motivo=motivo,
                   prospetto=json.dumps(pro), payslip_id=slip.id)
    db.session.add(c)
    payroll.log_message(ws.id, "hr.payslip", slip.id, body=f"Busta di liquidazione per cessazione del "
                        f"{data_cess.strftime('%d/%m/%Y')} ({dict(MOTIVI).get(motivo, motivo)})", author=author)
    db.session.commit()
    return c
