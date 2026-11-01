"""Presenze e note spese di novembre 2026: quattro file «sporchi» come arrivano davvero all'ufficio paghe, la loro lettura
automatica, gli errori da risolvere e gli apporti puliti per le buste (STR25, STR50, TRASF, RIMBORSI) più le assenze.

File d'esempio (generati sempre uguali):
  presenze_novembre_2026.xlsx   foglio dei capi reparto: titoli, legenda, nomi scritti a mano, «8h», «8,5», «otto», sigle
  timbrature_badge_novembre.csv timbrature del badge (apprendista e imballaggio): uscite mancanti, timbrature doppie
  note_spese_novembre.pdf       riepilogo note spese con chilometri, parcheggi, hotel, pasti
  scontrino_taxi_galli.jpg      foto di uno scontrino: senza modello linguistico l'importo si inserisce a mano

Regole di lettura (legenda del foglio): numero = ore lavorate; oltre l'orario del giorno = straordinario feriale 25%;
sabato = straordinario feriale 25%; domenica e festività (anche il patrono, 13 novembre) = straordinario 50%;
F = ferie, M = malattia, P4 = 4 ore di permesso ROL, T = trasferta in Italia (giornata intera + 1 giorno di TRASF).
Badge: ore = uscita − entrata − 1 ora di pausa se la giornata supera le 6 ore. Rimborso chilometrico 0,40 €/km.
Le spese di vitto in trasferta non si rimborsano a chi ha già l'indennità forfettaria.
"""
import csv
import difflib
import io
import re
from datetime import date, datetime, timedelta

ANNO, MESE = 2026, 11
PATRONO = date(2026, 11, 13)
EURO_KM = 0.40
FESTIVI = {date(2026, 11, 1), PATRONO}

FOGLIO = {  # nome scritto nel foglio -> giorni particolari (gli altri giorni lavorativi: orario pieno)
    "BIANCHI M.": {4: "10", 5: "10", 10: "10", 11: "10", 20: "8,5", 21: "4"},
    "rossi laura": {16: "F", 17: "F", 25: "P4"},
    "Verdi Luca": {13: "6", 18: "otto", 23: "9", 26: "M", 27: "M"},
    "ESPOSITO PINO": {9: "T", 10: "T", 11: "T", 24: "10h"},
    "Ferri Anna (PT)": {},
}
ORARIO = {"Ferri Anna (PT)": 4}
BADGE = {"0006": {5: [("E", "08:00"), ("E", "08:00"), ("U", "17:00")], 12: [("E", "08:00"), ("U", "18:30")]},
         "0008": {19: [("E", "08:00")], 27: [("E", "08:00"), ("U", "19:00")]}}
NOTE_SPESE = [
    ("0002", "Rossi Laura", "03/11/2026", "Km auto propria Città di Castello - Perugia A/R (cliente Umbra Ferro)", "km", 120),
    ("0002", "Rossi Laura", "12/11/2026", "Km auto propria Città di Castello - Arezzo A/R (banca)", "km", 85),
    ("0002", "Rossi Laura", "12/11/2026", "Parcheggio Arezzo", "euro", 12.00),
    ("0002", "Rossi Laura", "19/11/2026", "Km auto propria Città di Castello - Firenze A/R (fiera)", "km", 210),
    ("0007", "Galli Sara", "05/11/2026", "Hotel Bologna (fornitore lamiere), 1 notte", "euro", 145.00),
    ("0007", "Galli Sara", "05/11/2026", "Cena di lavoro Bologna", "euro", 38.50),
    ("0004", "Esposito Giuseppe", "10/11/2026", "Pranzo durante la trasferta a Terni", "euro", 18.00),
]
SCONTRINO = {"matricola": "0007", "dipendente": "Galli Sara", "data": "06/11/2026", "descrizione": "Taxi stazione - fornitore",
             "importo": 24.00}

# Risultato atteso dopo aver risolto correttamente tutti gli errori (per la verifica dell'esercitazione)
ATTESO = {"0001": {"STR25": 12.5}, "0002": {"RIMBORSI": 178.0}, "0003": {"STR25": 1.0, "STR50": 6.0},
          "0004": {"STR25": 2.0, "TRASF": 3.0}, "0006": {"STR25": 1.5}, "0007": {"RIMBORSI": 207.5},
          "0008": {"STR25": 2.0}}
ASSENZE_ATTESE = [("0002", "FERIE", date(2026, 11, 16), date(2026, 11, 17), None),
                  ("0002", "ROL", date(2026, 11, 25), date(2026, 11, 25), (13.0, 17.0)),
                  ("0003", "MAL", date(2026, 11, 26), date(2026, 11, 27), None)]


def giorni_mese():
    d = date(ANNO, MESE, 1)
    while d.month == MESE:
        yield d
        d += timedelta(days=1)


def lavorativo(d):
    return d.weekday() < 5 and d not in FESTIVI


# ------------------------------------------------------------------------------------------- generazione dei file
def file_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Novembre"
    ws["A1"] = "FERRO & TRANSENNE SRL - FOGLIO PRESENZE REPARTI"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Mese: NOVEMBRE 2026        compilato dai capi reparto - consegnare entro il 2/12"
    ws["A3"] = "Legenda: ore lavorate | F ferie | M malattia | P4 permesso 4 ore | T trasferta (giornata intera)"
    ws.merge_cells("A1:L1")
    ws.cell(row=5, column=1, value="Dipendente")
    giorni = list(giorni_mese())
    for i, d in enumerate(giorni, start=2):
        c = ws.cell(row=5, column=i, value=d.day)
        c.alignment = Alignment(horizontal="center")
        ws.cell(row=4, column=i, value="LMMGVSD"[d.weekday()])
        if not lavorativo(d):
            c.fill = PatternFill("solid", fgColor="DDDDDD")
    ws.cell(row=5, column=len(giorni) + 2, value="Note")
    r = 6
    for nome, speciali in FOGLIO.items():
        ws.cell(row=r, column=1, value=nome)
        for i, d in enumerate(giorni, start=2):
            if d.day in speciali:
                v = speciali[d.day]
                ws.cell(row=r, column=i, value=float(v) if re.fullmatch(r"\d+", v) else v)
            elif lavorativo(d):
                ws.cell(row=r, column=i, value=ORARIO.get(nome, 8))
        r += 1
    ws.cell(row=r, column=1, value="TOTALE ORE REPARTI")
    ws.cell(row=r, column=2, value="vedi sopra")
    ws.cell(row=r + 2, column=1, value="Galli Sara (quadro): non compila le presenze")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def file_badge():
    out = io.StringIO()
    out.write("MATRICOLA;DATA;ORA;VERSO\n")
    for matr in ("0006", "0008"):
        for d in giorni_mese():
            if not lavorativo(d):
                continue
            stamps = BADGE[matr].get(d.day, [("E", "08:00"), ("U", "17:00")])
            for verso, ora in stamps:
                out.write(f"{matr};{d:%d/%m/%Y};{ora};{verso}\n")
    return out.getvalue().encode("utf-8")


def file_note_spese():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20 * mm, h - 20 * mm, "Ferro & Transenne Srl - Riepilogo note spese novembre 2026")
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 27 * mm, "Rimborso chilometrico aziendale 0,40 euro/km. Allegare i giustificativi.")
    y = h - 40 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "MATR | DIPENDENTE | DATA | DESCRIZIONE | TIPO | VALORE")
    c.setFont("Helvetica", 9)
    for matr, dip, dt, descr, tipo, val in NOTE_SPESE:
        y -= 7 * mm
        v = f"{val:g}" if tipo == "km" else f"{val:.2f}".replace(".", ",")
        c.drawString(20 * mm, y, f"{matr} | {dip} | {dt} | {descr} | {tipo} | {v}")
    y -= 12 * mm
    c.drawString(20 * mm, y, "Scontrino del taxi di Galli Sara (06/11/2026) consegnato a parte, in foto.")
    c.showPage()
    c.save()
    return buf.getvalue()


def file_scontrino():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (420, 560), (250, 248, 240))
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("DejaVuSansMono.ttf", 18)
        fb = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 22)
    except OSError:
        f = fb = ImageFont.load_default()
    righe = ["RADIO TAXI BOLOGNA", "Soc. Coop. - P.IVA 0000000000", "", "06/11/2026   ore 08:42",
             "Partenza: Stazione Centrale", "Arrivo: Via del Lavoro 8", "", "Corsa            21,50", "Supplemento       2,50",
             "-------------------------", "TOTALE EUR       24,00", "", "Pagato: carta", "Grazie e buona giornata"]
    y = 30
    for t in righe:
        d.text((30, y), t, fill=(30, 30, 30), font=fb if t.startswith(("RADIO", "TOTALE")) else f)
        y += 34
    img = img.rotate(3, expand=True, fillcolor=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


FILE = {"presenze_novembre_2026.xlsx": (file_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "timbrature_badge_novembre.csv": (file_badge, "text/csv"),
        "note_spese_novembre.pdf": (file_note_spese, "application/pdf"),
        "scontrino_taxi_galli.jpg": (lambda: open(_SCONTRINO_JPG, "rb").read(), "image/jpeg")}
# la foto è salvata nel pacchetto (file_scontrino l'ha generata): così non dipende dai font del server
import os as _os  # noqa: E402
_SCONTRINO_JPG = _os.path.join(_os.path.dirname(__file__), "dati", "scontrino_taxi_galli.jpg")


# ------------------------------------------------------------------------------------------- lettura
def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().replace("h", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def abbina_nome(testo, dipendenti):
    """Riconosce il dipendente da un nome scritto a mano: cognome e iniziale, maiuscole, sigle. Restituisce
    (matricola, punteggio) del migliore abbinamento; sotto 0,85 serve la conferma di una persona."""
    pulito = re.sub(r"\(.*?\)", "", testo or "").replace(".", " ").strip().lower()
    migliore, punti = None, 0.0
    for matr, nome in dipendenti.items():
        cogn, *resto = nome.lower().split()
        cand = [nome.lower(), f"{cogn} {resto[0][0] if resto else ''}".strip()]
        p = max(difflib.SequenceMatcher(None, pulito, c).ratio() for c in cand)
        if pulito.split() and pulito.split()[0] == cogn:
            p = max(p, 0.8)
        if p > punti:
            migliore, punti = matr, p
    return migliore, round(punti, 2)


def leggi_excel(dati, dipendenti, correzioni=None):
    """Righe giornaliere {matricola, giorno, valore} + errori. correzioni: {chiave errore: valore}."""
    from openpyxl import load_workbook
    correzioni = correzioni or {}
    wb = load_workbook(io.BytesIO(dati), data_only=True)
    ws = wb.active
    riga_giorni, col_giorni = None, {}
    for row in ws.iter_rows(min_row=1, max_row=15):
        nums = {c.column: int(c.value) for c in row if isinstance(c.value, (int, float)) and 1 <= c.value <= 31}
        if len(nums) >= 28:
            riga_giorni, col_giorni = row[0].row, nums
            break
    errori, giornate, nomi = [], [], {}
    if not riga_giorni:
        return [], [{"chiave": "excel-intestazione", "tipo": "bloccante", "testo": "Non trovo la riga con i giorni 1-30."}], {}
    for row in ws.iter_rows(min_row=riga_giorni + 1):
        testo = row[0].value
        if not testo or not isinstance(testo, str):
            continue
        if testo.strip().upper().startswith("TOTALE"):
            errori.append({"chiave": "excel-totale", "tipo": "info", "testo": f"Riga «{testo}» ignorata: è un totale, non un dipendente."})
            continue
        celle = {c.column: c.value for c in row}
        if not any(celle.get(col) not in (None, "") for col in col_giorni):
            errori.append({"chiave": f"excel-nota-{row[0].row}", "tipo": "info", "testo": f"Riga «{testo}» senza presenze: ignorata."})
            continue
        matr, punti = abbina_nome(testo, dipendenti)
        chiave = f"nome:{testo}"
        if chiave in correzioni:
            matr = correzioni[chiave] or None
        elif punti < 0.85:
            errori.append({"chiave": chiave, "tipo": "nome", "testo": f"Nome «{testo}» riconosciuto come {dipendenti.get(matr, '?')} "
                           f"(somiglianza {punti:.2f}): confermare il dipendente.", "proposta": matr})
            continue
        if not matr:
            continue
        nomi[matr] = testo
        for col, giorno in col_giorni.items():
            v = celle.get(col)
            if v in (None, ""):
                continue
            if isinstance(v, str) and v.strip().upper() in ("F", "M", "T") or (isinstance(v, str) and re.fullmatch(r"P\d+([.,]\d+)?", v.strip().upper())):
                giornate.append({"matricola": matr, "giorno": giorno, "valore": v.strip().upper()})
                continue
            n = _num(v)
            k = f"cella:{matr}:{giorno}"
            if k in correzioni:
                n = _num(correzioni[k])
            if n is None:
                errori.append({"chiave": k, "tipo": "valore", "testo": f"{dipendenti[matr]}, {giorno}/11: «{v}» non è un numero di ore.",
                               "proposta": "8" if str(v).strip().lower() == "otto" else ""})
                continue
            giornate.append({"matricola": matr, "giorno": giorno, "valore": n})
    return giornate, errori, nomi


def leggi_badge(dati, correzioni=None):
    correzioni = correzioni or {}
    righe = list(csv.DictReader(io.StringIO(dati.decode("utf-8-sig")), delimiter=";"))
    per = {}
    for r in righe:
        k = (r["MATRICOLA"].strip(), datetime.strptime(r["DATA"].strip(), "%d/%m/%Y").date())
        per.setdefault(k, []).append((r["VERSO"].strip().upper(), r["ORA"].strip()))
    giornate, errori = [], []
    for (matr, d), stamps in sorted(per.items()):
        visti, uniche = set(), []
        for s in stamps:
            if s in visti:
                errori.append({"chiave": f"doppia:{matr}:{d.day}", "tipo": "info",
                               "testo": f"Matricola {matr}, {d:%d/%m}: timbratura {s[0]} {s[1]} doppia, considerata una volta."})
                continue
            visti.add(s)
            uniche.append(s)
        ent = [o for v, o in uniche if v == "E"]
        usc = [o for v, o in uniche if v == "U"]
        k = f"uscita:{matr}:{d.day}"
        if ent and not usc:
            if k in correzioni and re.fullmatch(r"\d{1,2}[:.]\d{2}", correzioni[k] or ""):
                usc = [correzioni[k].replace(".", ":")]
            else:
                errori.append({"chiave": k, "tipo": "orario", "testo": f"Matricola {matr}, {d:%d/%m}: manca l'uscita. "
                               "Il capo reparto conferma l'orario normale.", "proposta": "17:00"})
                continue
        t1 = datetime.strptime(ent[0], "%H:%M")
        t2 = datetime.strptime(usc[-1], "%H:%M")
        ore = (t2 - t1).seconds / 3600
        if ore > 6:
            ore -= 1
        giornate.append({"matricola": matr, "giorno": d.day, "valore": round(ore, 2)})
    return giornate, errori


def leggi_note_spese(dati):
    import pdfplumber
    righe, errori = [], []
    with pdfplumber.open(io.BytesIO(dati)) as pdf:
        testo = "\n".join(p.extract_text() or "" for p in pdf.pages)
    for linea in testo.splitlines():
        parti = [p.strip() for p in linea.split("|")]
        if len(parti) != 6 or not re.fullmatch(r"\d{4}", parti[0]):
            continue
        matr, dip, dt, descr, tipo, val = parti
        v = float(val.replace(".", "").replace(",", ".")) if tipo == "euro" else float(val)
        importo = round(v * EURO_KM, 2) if tipo == "km" else v
        righe.append({"matricola": matr, "dipendente": dip, "data": dt, "descrizione": descr, "tipo": tipo, "valore": v,
                      "importo": importo})
    return righe, errori


# ------------------------------------------------------------------------------------------- normalizzazione
def normalizza(dipendenti, correzioni=None, file=None):
    """dipendenti: {matricola: «Cognome Nome»} dell'ambiente. file: {nome: bytes} caricati (altrimenti gli esempi).
    Restituisce apporti per matricola, assenze, righe di dettaglio ed errori aperti."""
    correzioni = correzioni or {}
    file = file or {}

    def dati(nome):
        return file.get(nome) or FILE[nome][0]()

    g_excel, err_x, _ = leggi_excel(dati("presenze_novembre_2026.xlsx"), dipendenti, correzioni)
    g_badge, err_b = leggi_badge(dati("timbrature_badge_novembre.csv"), correzioni)
    spese, err_s = leggi_note_spese(dati("note_spese_novembre.pdf"))
    errori = err_x + err_b + err_s
    apporti = {m: {"STR25": 0.0, "STR50": 0.0, "TRASF": 0.0, "RIMBORSI": 0.0} for m in dipendenti}
    assenze, dettaglio = [], []
    orario = {m: 8.0 for m in dipendenti}
    for m, nome in dipendenti.items():
        if "Ferri" in nome:
            orario[m] = 4.0
    giorni_assenza = {}
    for g in g_excel + g_badge:
        m, d, v = g["matricola"], date(ANNO, MESE, g["giorno"]), g["valore"]
        if m not in apporti:
            continue
        if isinstance(v, str):
            if v == "T":
                apporti[m]["TRASF"] += 1
                dettaglio.append((m, d, "trasferta", 1))
            elif v in ("F", "M"):
                giorni_assenza.setdefault((m, "FERIE" if v == "F" else "MAL"), []).append(d)
            elif v.startswith("P"):
                ore = float(v[1:].replace(",", "."))
                assenze.append((m, "ROL", d, d, (17.0 - ore, 17.0)))
            continue
        if d in FESTIVI or d.weekday() == 6:
            apporti[m]["STR50"] += v
            dettaglio.append((m, d, "straordinario 50%", v))
        elif d.weekday() == 5:
            apporti[m]["STR25"] += v
            dettaglio.append((m, d, "straordinario 25% (sabato)", v))
        elif v > orario[m]:
            apporti[m]["STR25"] += v - orario[m]
            dettaglio.append((m, d, "straordinario 25%", v - orario[m]))
    for (m, tipo), giorni in giorni_assenza.items():
        giorni.sort()
        inizio = prec = giorni[0]
        for d in giorni[1:] + [None]:
            if d is None or (d - prec).days > 1:
                assenze.append((m, tipo, inizio, prec, None))
                inizio = d
            prec = d or prec
    trasferte = {m for m, a in apporti.items() if a["TRASF"]}
    for s in spese:
        m = s["matricola"]
        if m not in apporti:
            continue
        if m in trasferte and re.search(r"pranzo|cena|pasto", s["descrizione"], re.I):
            errori.append({"chiave": f"vitto:{m}:{s['data']}", "tipo": "info",
                           "testo": f"{s['dipendente']}, {s['data']}: «{s['descrizione']}» non rimborsato, già coperto "
                                    "dall'indennità di trasferta forfettaria."})
            continue
        apporti[m]["RIMBORSI"] += s["importo"]
    k = "scontrino:0007"
    if k in correzioni and _num(correzioni[k]) is not None:
        if "0007" in apporti:
            apporti["0007"]["RIMBORSI"] += _num(correzioni[k])
    else:
        errori.append({"chiave": k, "tipo": "importo", "testo": "Scontrino del taxi di Galli Sara (foto): leggere l'importo "
                       "dalla foto e inserirlo. Con un modello linguistico attivo la lettura è automatica, ma va confermata.",
                       "proposta": ""})
    for a in apporti.values():
        for c in a:
            a[c] = round(a[c], 2)
    aperti = [e for e in errori if e["tipo"] not in ("info",)]
    return {"apporti": apporti, "assenze": sorted(assenze), "dettaglio": dettaglio, "errori": errori, "aperti": aperti,
            "spese": spese}


def confronta_atteso(apporti):
    diff = []
    for m in set(apporti) | set(ATTESO):
        for c in ("STR25", "STR50", "TRASF", "RIMBORSI"):
            v = round((apporti.get(m) or {}).get(c, 0.0), 2)
            att = (ATTESO.get(m) or {}).get(c, 0.0)
            if abs(v - att) > 0.01:
                diff.append((m, c, v, att))
    return diff
