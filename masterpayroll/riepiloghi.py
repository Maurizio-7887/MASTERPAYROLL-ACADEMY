"""Riepiloghi sulle buste completate: totali per categoria, prima nota, libro unico, certificazione unica."""
from collections import defaultdict
from datetime import date

from .hr_service import attendance_intervals, calendari_periodo, daterange, list_leaves
from .models import Employee, Payslip, ProgressivoAnnuo, month_bounds


def totali_categorie(slip):
    """Totali per codice di categoria, compresi i padri (come categories.XXX nelle regole)."""
    tot = defaultdict(float)
    for ln in slip.line_ids:
        c = ln.category
        while c is not None:
            if c.code:
                tot[c.code] += ln.total
            c = c.parent
    return tot


def buste_del_mese(ws_id, anno, mese):
    d1, d2 = month_bounds(date(anno, mese, 1))
    return (Payslip.query.filter(Payslip.workspace_id == ws_id, Payslip.state == "done",
                                 Payslip.date_from >= d1, Payslip.date_to <= d2)
            .order_by(Payslip.employee_id, Payslip.id).all())


def periodi(ws_id):
    return sorted({(s.date_from.year, s.date_from.month) for s in
                   Payslip.query.filter_by(workspace_id=ws_id, state="done")}, reverse=True)


# conti di contabilità generale (piano dei conti didattico)
CONTI = {
    "retribuzioni": ("B9a", "Salari e stipendi"),
    "esenti": ("B9e", "Trasferte e rimborsi ai dipendenti"),
    "oneri": ("B9b", "Oneri sociali INPS"),
    "inail": ("B9b", "Premi INAIL"),
    "tfr": ("B9c", "Trattamento di fine rapporto (accantonamento)"),
    "fondo_util": ("D-TFR", "Fondo TFR (utilizzo per liquidazione)"),
    "inps_ind": ("C-INPS", "INPS c/indennità anticipate ai dipendenti"),
    "crediti_erario": ("C-ERA", "Erario c/crediti anticipati (trattamento integrativo, cuneo)"),
    "netti": ("D-DIP", "Debiti verso dipendenti (retribuzioni nette)"),
    "debito_inps": ("D-INPS", "Debiti verso INPS (contributi)"),
    "debito_erario": ("D-ERA", "Erario c/ritenute (IRPEF, addizionali, TFR)"),
    "debito_inail": ("D-INAIL", "Debiti verso INAIL"),
    "fondo_tfr": ("D-TFR", "Fondo TFR"),
    "anticipi": ("C-ANT", "Anticipi a dipendenti (recupero)"),
}


def prima_nota(slips):
    """Scrittura in partita doppia delle paghe del mese: Dare = costi e crediti, Avere = debiti."""
    t = defaultdict(float)
    for s in slips:
        sg = -1 if s.credit_note else 1
        c = totali_categorie(s)
        g = lambda k: sg * c.get(k, 0.0)  # noqa: E731
        t["retribuzioni"] += g("GROSS")
        t["esenti"] += g("ESENTE") - g("CRED") - g("TFRC")
        t["fondo_util"] += g("TFRC")
        t["inps_ind"] += g("INPS_IND")
        t["crediti_erario"] += g("CRED")
        t["netti"] += g("NET")
        t["debito_erario"] += -g("FISC")
        t["anticipi"] += -g("ALTRE")
        lc = defaultdict(float)
        for ln in s.line_ids:
            lc[ln.code] += sg * ln.total
        t["oneri"] += lc["INPS_DITTA"]
        t["inail"] += lc["INAIL"]
        t["tfr"] += lc["TFR"]
        t["debito_inps"] += -g("PREV") + lc["INPS_DITTA"]
        t["debito_inail"] += lc["INAIL"]
        t["fondo_tfr"] += lc["TFR"]
    dare = ["retribuzioni", "esenti", "oneri", "inail", "tfr", "fondo_util", "inps_ind", "crediti_erario"]
    avere = ["netti", "debito_inps", "debito_erario", "debito_inail", "fondo_tfr", "anticipi"]
    righe = []
    for k in dare:
        if abs(t[k]) >= 0.005:
            righe.append({"chiave": k, "conto": CONTI[k][0], "descrizione": CONTI[k][1], "dare": round(t[k], 2), "avere": 0.0})
    for k in avere:
        if abs(t[k]) >= 0.005:
            righe.append({"chiave": k, "conto": CONTI[k][0], "descrizione": CONTI[k][1], "dare": 0.0, "avere": round(t[k], 2)})
    # ogni riga di busta è arrotondata al centesimo: qualche centesimo di differenza va negli arrotondamenti
    diff = round(sum(r["dare"] for r in righe) - sum(r["avere"] for r in righe), 2)
    if 0.005 <= abs(diff) <= 0.10:
        righe.append({"chiave": "arrotondamenti", "conto": "C17", "descrizione": "Differenze di arrotondamento",
                      "dare": -diff if diff < 0 else 0.0, "avere": diff if diff > 0 else 0.0})
    return righe


# ---------------------------------------------------------------------------
# Libro unico del lavoro: calendario presenze del mese
# ---------------------------------------------------------------------------
SIGLE = {"FERIE": "FE", "ROL": "PR", "MAL": "MA", "INF": "IN", "PNR": "PN", "CONG": "CP"}


def presenze_mese(employee, anno, mese):
    d1, d2 = month_bounds(date(anno, mese, 1))
    cal = calendari_periodo(employee, d1, d2)  # l'orario del giorno: segue lo storico degli orari
    contratti = [c for c in employee.contract_ids if c.state in ("open", "close") and c.is_overlapping_period(d1, d2)]
    if not contratti:
        return []
    inizio = min(c.date_start for c in contratti)
    fine = max((c.date_end or d2) for c in contratti)
    assenze = defaultdict(list)
    for d, ore, tipo in list_leaves(employee, cal, d1, d2):
        assenze[d].append((ore, tipo))
    giorni = []
    for d in daterange(d1, d2):
        h_day = sum(t - f for f, t in attendance_intervals(cal(d), d))
        if d < inizio or d > fine:
            giorni.append((d, "", 0))
        elif h_day <= 0:
            giorni.append((d, "R", 0))
        elif d in assenze:
            ore_ass = sum(o for o, _ in assenze[d])
            tipo = assenze[d][0][1]
            sigla = "FS" if tipo is None else SIGLE.get(tipo.code, tipo.code[:2])
            giorni.append((d, sigla if ore_ass >= h_day else f"L{h_day - ore_ass:g}+{sigla}", h_day - ore_ass))
        else:
            giorni.append((d, f"{h_day:g}", h_day))
    return giorni


# ---------------------------------------------------------------------------
# Certificazione Unica: dati di sintesi dell'anno
# ---------------------------------------------------------------------------
def dati_cu(employee, anno, ws_id):
    d1, d2 = date(anno, 1, 1), date(anno, 12, 31)
    tot = defaultdict(float)
    for p in ProgressivoAnnuo.query.filter_by(workspace_id=ws_id, employee_id=employee.id, anno=anno):
        tot["IMP_FISC"] += p.imponibile_fiscale
        tot["IRPEF"] += p.irpef_trattenuta
        tot["IMP_PREV"] += p.imponibile_previdenziale
        tot["INPS"] += p.inps_dipendente
        tot["ADD"] += p.addizionali
        tot["CUNEO"] += p.cuneo_indennita
        tot["mesi_prec"] += p.mesi
    for s in Payslip.query.filter(Payslip.workspace_id == ws_id, Payslip.employee_id == employee.id,
                                  Payslip.state == "done", Payslip.date_from >= d1, Payslip.date_to <= d2):
        sg = -1 if s.credit_note else 1
        for ln in s.line_ids:
            v = sg * ln.total
            if ln.code == "IMP_FISC":
                tot["IMP_FISC"] += v
            elif ln.code in ("IRPEF", "IRPEF13", "IRPEF_CESS", "CONG_IRPEF"):
                tot["IRPEF"] -= v
            elif ln.code == "IMP_PREV":
                tot["IMP_PREV"] += v
            elif ln.code in ("INPS_DIP", "INPS_AGG"):
                tot["INPS"] -= v
            elif ln.code == "ADD_REG":
                tot["ADD_REG"] -= v
            elif ln.code == "ADD_COM":
                tot["ADD_COM"] -= v
            elif ln.code in ("IND_CUNEO", "CONG_CUNEO"):
                tot["CUNEO"] += v
            elif ln.code == "TRATT_INT":
                tot["TRATT_INT"] += v
            elif ln.code == "TFR_LIQ":
                tot["TFR"] += v
            elif ln.code == "RIT_TFR":
                tot["RIT_TFR"] -= v
            elif ln.code == "SOST_TFR":
                tot["SOST_TFR"] -= v
            elif ln.code == "MAL_INPS":
                tot["MAL_INPS"] += v
    return {k: round(v, 2) for k, v in tot.items()}


def dipendenti_anno(ws_id, anno):
    d1, d2 = date(anno, 1, 1), date(anno, 12, 31)
    out = []
    for e in Employee.query.filter_by(workspace_id=ws_id).order_by(Employee.last_name, Employee.first_name):
        if any(c.is_overlapping_period(d1, d2) for c in e.contract_ids if c.state in ("open", "close")):
            out.append(e)
    return out
