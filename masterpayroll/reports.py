"""Report PDF con ReportLab (in Odoo sono report QWeb stampati con wkhtmltopdf).

* payslip_pdf                -> payroll.report_payslip         ("Busta paga")
* payslip_details_pdf        -> payroll.report_payslipdetails  ("Dettaglio busta paga")
* contribution_register_pdf  -> payroll.report_contributionregister
Ogni pagina porta la filigrana dell'ambiente formativo.
"""
import io
from collections import OrderedDict

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .models import Payslip, PayslipLine, db

BLU = colors.HexColor("#16324f")
GRIGIO = colors.HexColor("#f0f2f5")
_ss = getSampleStyleSheet()
ST = {
    "h1": ParagraphStyle("h1", parent=_ss["Heading1"], fontSize=14, textColor=BLU, spaceAfter=2, spaceBefore=0),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontSize=10.5, textColor=BLU, spaceBefore=8, spaceAfter=3),
    "n": ParagraphStyle("n", parent=_ss["Normal"], fontSize=8, leading=10),
    "s": ParagraphStyle("s", parent=_ss["Normal"], fontSize=6.8, leading=8.5, textColor=colors.HexColor("#555555")),
    "lbl": ParagraphStyle("lbl", parent=_ss["Normal"], fontSize=6, leading=7, textColor=colors.HexColor("#666666")),
    "r": ParagraphStyle("r", parent=_ss["Normal"], fontSize=8, leading=10, alignment=TA_RIGHT),
    "big": ParagraphStyle("big", parent=_ss["Normal"], fontSize=13, leading=16, alignment=TA_RIGHT,
                          fontName="Helvetica-Bold", textColor=BLU),
}


def eur(v, dec=2):
    s = f"{float(v or 0):,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def qty(v):
    if v is None:
        return ""
    v = float(v)
    if v == int(v):
        return str(int(v))
    return f"{v:.4f}".rstrip("0").replace(".", ",")


def d(dt):
    return dt.strftime("%d/%m/%Y") if dt else ""


def _esc(s):
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _watermark(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 30)
    canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.10))
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(35)
    canvas.drawCentredString(0, 0, "AMBIENTE FORMATIVO — DATI SIMULATI")
    canvas.restoreState()
    canvas.saveState()
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(15 * mm, 9 * mm, "MasterPayroll Academy — documento didattico senza valore legale")
    canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Pagina {doc.page}")
    canvas.restoreState()


def _doc(buf, title):
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=13 * mm,
                             bottomMargin=15 * mm, title=title, author="MasterPayroll Academy")


def _grid(data, widths, header=True, zebra=False, extra=None):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7.8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b5bcc5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), GRIGIO), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7)]
    if zebra:
        for i in range(1 + header, len(data), 2):
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafbfc")))
    t.setStyle(TableStyle(style + (extra or [])))
    return t


def _cell(label, value, bold=False):
    v = f"<b>{_esc(value)}</b>" if bold else _esc(value)
    return Paragraph(f'<font size="6" color="#666666">{_esc(label).upper()}</font><br/>{v}', ST["n"])


def _header(ws, slip, title):
    emp, c = slip.employee, slip.contract
    story = [Paragraph(_esc(title), ST["h1"]), Paragraph(_esc(slip.name), ST["n"]), Spacer(0, 4)]
    data = [
        [_cell("Azienda", ws.name, True), _cell("Indirizzo", f"{ws.street} {ws.city}"), _cell("Partita IVA", ws.vat),
         _cell("Matricola INPS / PAT INAIL", f"{ws.matricola_inps} / {ws.pat_inail}")],
        [_cell("Dipendente", f"{emp.registration_number} - {emp.name}", True), _cell("Mansione", emp.job_title),
         _cell("Codice fiscale", emp.identification_id), _cell("IBAN", emp.bank_account)],
        [_cell("Riferimento", slip.number or "(bozza)", True), _cell("Periodo", f"{d(slip.date_from)} - {d(slip.date_to)}"),
         _cell("Contratto / livello", f"{c.contract_type} {c.livello.codice if c.livello else ''}" if c else ""),
         _cell("Part-time / CCNL", f"{qty(c.part_time)}% - {c.ccnl or ws.ccnl}" if c else ws.ccnl)],
    ]
    story.append(_grid(data, [45 * mm, 45 * mm, 45 * mm, 45 * mm], header=False))
    return story


def _lines_table(slip):
    rows = [["Cod.", "Voce", "Quantità", "Base / tasso", "Competenze", "Trattenute"]]
    comp = tratt = 0.0
    for ln in slip.line_ids:
        if not ln.appears_on_payslip or (ln.category and ln.category.code == "NET"):
            continue
        base = ""
        if ln.amount_select == "percentage":
            base = f"{eur(ln.amount)} × {qty(ln.rate)}%"
        elif (ln.quantity or 1) != 1 or (ln.rate or 100) != 100:
            base = eur(ln.amount, 2) + ("" if (ln.rate or 100) == 100 else f" × {qty(ln.rate)}%")
        q = qty(ln.quantity) if (ln.quantity or 1) != 1 else ""
        c_val = t_val = ""
        if ln.total >= 0:
            c_val, comp = eur(ln.total), comp + ln.total
        else:
            t_val, tratt = eur(-ln.total), tratt - ln.total
        rows.append([ln.code or "", Paragraph(_esc(ln.name), ST["n"]), q, base, c_val, t_val])
    rows.append(["", Paragraph("<b>Totali</b>", ST["n"]), "", "", eur(comp), eur(tratt)])
    return _grid(rows, [20 * mm, 66 * mm, 16 * mm, 30 * mm, 24 * mm, 24 * mm], zebra=True, extra=[
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 7.8), ("BACKGROUND", (0, -1), (-1, -1), GRIGIO)])


def _code_total(slip, code):
    return sum(ln.total for ln in slip.line_ids if ln.code == code)


def _cat_total(slip, code):
    return sum(ln.total for ln in slip.line_ids if ln.category and ln.category.code == code)


def payslip_pdf(ws, slips):
    buf = io.BytesIO()
    doc = _doc(buf, "Busta paga")
    story = []
    for i, slip in enumerate(slips):
        if i:
            story.append(PageBreak())
        title = "Busta paga" + (" — STORNO (nota di credito)" if slip.credit_note else "")
        if slip.state in ("draft", "verify"):
            title += f" — {'BOZZA' if slip.state == 'draft' else 'DA CONFERMARE'}"
        story += _header(ws, slip, title)
        story.append(Spacer(0, 6))
        if not slip.line_ids:
            story.append(Paragraph("Busta non ancora calcolata.", ST["n"]))
            continue
        story.append(_lines_table(slip))
        story.append(Spacer(0, 6))
        wd = [["Giorni lavorati e assenze", "Codice", "Giorni", "Ore"]] + [
            [Paragraph(_esc(w.name), ST["n"]), w.code, qty(w.number_of_days), qty(w.number_of_hours)]
            for w in slip.worked_days_line_ids]
        riep = [["Imponibile previdenziale", eur(_code_total(slip, "IMP_PREV"))],
                ["Imponibile fiscale", eur(_code_total(slip, "IMP_FISC"))],
                ["IRPEF lorda", eur(_code_total(slip, "IRPEF_LORDA"))],
                ["Detrazioni", eur(_cat_total(slip, "DETR"))],
                ["Quota TFR del mese", eur(_code_total(slip, "TFR"))]]
        net = _cat_total(slip, "NET")
        left = _grid(wd, [48 * mm, 19 * mm, 12 * mm, 12 * mm], extra=[("ALIGN", (2, 0), (-1, -1), "RIGHT")])
        right = Table([[_grid(riep, [50 * mm, 25 * mm], header=False, extra=[("ALIGN", (1, 0), (1, -1), "RIGHT")])],
                       [Spacer(0, 4)],
                       [Paragraph(f'<font size="7" color="#666666">NETTO DEL MESE</font><br/>€ {eur(net)}', ST["big"])]],
                      colWidths=[78 * mm])
        story.append(Table([[left, right]], colWidths=[100 * mm, 80 * mm],
                           style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(Spacer(0, 14))
        story.append(Paragraph("Firma autorizzata ______________________", ST["r"]))
    if not story:
        story.append(Paragraph("Nessuna busta paga.", ST["n"]))
    doc.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
    return buf.getvalue()


def details_by_rule_category(slip):
    """Porting di get_details_by_rule_category (report_payslip_details.py)."""
    lines = [ln for ln in slip.line_ids if ln.appears_on_payslip]
    by_cat = OrderedDict()
    for ln in sorted(lines, key=lambda x: (x.sequence or 0, x.category.parent_id if x.category else 0)):
        by_cat.setdefault(ln.category_id, []).append(ln)
    res = []
    for _cat_id, cat_lines in by_cat.items():
        cat = cat_lines[0].category
        chain = []
        c = cat
        while c is not None:
            chain.insert(0, c)
            c = c.parent
        total = sum(x.total for x in cat_lines)
        level = 0
        for parent in chain:
            res.append({"name": parent.name, "code": parent.code, "level": level, "total": total, "cat": True})
            level += 1
        for ln in cat_lines:
            res.append({"name": ln.name, "code": ln.code, "level": level, "total": ln.total, "cat": False})
    return res


def lines_by_contribution_register(slip):
    res = []
    regs = OrderedDict()
    for ln in slip.line_ids:
        if ln.appears_on_payslip and ln.register_id:
            regs.setdefault(ln.register_id, []).append(ln)
    for _rid, lns in regs.items():
        res.append({"register_name": lns[0].register.name, "total": sum(x.total for x in lns)})
        for ln in lns:
            res.append({"name": ln.name, "code": ln.code, "quantity": ln.quantity, "amount": ln.amount,
                        "total": ln.total})
    return res


def payslip_details_pdf(ws, slips):
    buf = io.BytesIO()
    doc = _doc(buf, "Dettaglio busta paga")
    story = []
    for i, slip in enumerate(slips):
        if i:
            story.append(PageBreak())
        story += _header(ws, slip, "Dettaglio busta paga" + (" — STORNO" if slip.credit_note else ""))
        story.append(Paragraph("Dettaglio per categoria di regola", ST["h2"]))
        rows = [["Codice", "Categoria / regola", "Totale"]]
        extra = [("ALIGN", (2, 0), (2, -1), "RIGHT")]
        for j, r in enumerate(details_by_rule_category(slip), start=1):
            ind = "&nbsp;" * 4 * r["level"]
            name = f"{ind}<b>{_esc(r['name'])}</b>" if r["cat"] else f"{ind}{_esc(r['name'])}"
            rows.append([r["code"] or "", Paragraph(name, ST["n"]), eur(r["total"])])
            if r["cat"]:
                extra.append(("BACKGROUND", (0, j), (-1, j), colors.HexColor("#eef2f7")))
        story.append(_grid(rows, [28 * mm, 122 * mm, 30 * mm], extra=extra))
        story.append(Paragraph("Righe busta paga per registro contributi", ST["h2"]))
        rows = [["Codice", "Registro / voce", "Quantità", "Importo", "Totale"]]
        extra = [("ALIGN", (2, 0), (-1, -1), "RIGHT")]
        for j, r in enumerate(lines_by_contribution_register(slip), start=1):
            if "register_name" in r:
                rows.append(["", Paragraph(f"<b>{_esc(r['register_name'])}</b>", ST["n"]), "", "", eur(r["total"])])
                extra.append(("BACKGROUND", (0, j), (-1, j), colors.HexColor("#eef2f7")))
            else:
                rows.append([r["code"] or "", Paragraph("&nbsp;&nbsp;&nbsp;&nbsp;" + _esc(r["name"]), ST["n"]),
                             qty(r["quantity"]), eur(r["amount"]), eur(r["total"])])
        if len(rows) == 1:
            rows.append(["", "Nessuna riga con registro", "", "", ""])
        story.append(_grid(rows, [28 * mm, 92 * mm, 18 * mm, 21 * mm, 21 * mm], extra=extra))
    doc.build(story or [Paragraph("Nessuna busta paga.", ST["n"])], onFirstPage=_watermark,
              onLaterPages=_watermark)
    return buf.getvalue()


def contribution_register_pdf(ws, registers, date_from, date_to):
    """Righe di buste confermate nel periodo, per registro (report_contribution_register.py)."""
    buf = io.BytesIO()
    doc = _doc(buf, "Righe busta paga per registro contributi")
    story = []
    for i, reg in enumerate(registers):
        if i:
            story.append(PageBreak())
        lines = (db.session.query(PayslipLine).join(Payslip, PayslipLine.slip_id == Payslip.id)
                 .filter(Payslip.workspace_id == ws.id, Payslip.date_from >= date_from, Payslip.date_to <= date_to,
                         PayslipLine.register_id == reg.id, Payslip.state == "done")
                 .order_by(PayslipLine.slip_id, PayslipLine.sequence).all())
        story.append(Paragraph(f"Registro contributi: {_esc(reg.name)}", ST["h1"]))
        story.append(Paragraph(f"{_esc(ws.name)} — dal {d(date_from)} al {d(date_to)}"
                               + (f" — Partner: {_esc(reg.partner.name)}" if reg.partner else ""), ST["n"]))
        story.append(Spacer(0, 6))
        rows = [["Busta paga", "Dipendente", "Codice", "Voce", "Quantità", "Importo", "Totale"]]
        tot = 0.0
        for ln in lines:
            sign = -1 if ln.slip.credit_note else 1
            tot += sign * ln.total
            rows.append([ln.slip.number or "", Paragraph(_esc(ln.employee.name if ln.employee else ""), ST["n"]),
                         ln.code or "", Paragraph(_esc(ln.name) + (" (storno)" if sign < 0 else ""), ST["n"]),
                         qty(ln.quantity), eur(ln.amount), eur(sign * ln.total)])
        rows.append(["", "", "", Paragraph("<b>Totale</b>", ST["n"]), "", "", eur(tot)])
        story.append(KeepTogether([_grid(rows, [22 * mm, 38 * mm, 20 * mm, 50 * mm, 14 * mm, 18 * mm, 18 * mm],
                                         zebra=True, extra=[("ALIGN", (4, 0), (-1, -1), "RIGHT"),
                                                            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 7.8)])]))
    doc.build(story or [Paragraph("Nessun registro selezionato.", ST["n"])], onFirstPage=_watermark,
              onLaterPages=_watermark)
    return buf.getvalue()
