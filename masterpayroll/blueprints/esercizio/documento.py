"""Documento PDF dell'esercizio: gli stessi passi della finestra a destra, con menu, campi, pulsanti e risultato atteso."""
import io
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fonts")
VIOLA = colors.HexColor("#714B67")
GRIGIO = colors.HexColor("#f3f0f2")


def _font():
    try:
        pdfmetrics.getFont("DejaVu")
    except KeyError:
        pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Oblique", os.path.join(FONT_DIR, "DejaVuSans-Oblique.ttf")))
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu-Oblique", boldItalic="DejaVu-Bold")


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pdf_esercizio(es, ws=None, url_for=None):
    _font()
    st = {
        "tit": ParagraphStyle("tit", fontName="DejaVu-Bold", fontSize=19, leading=24, textColor=VIOLA, spaceAfter=6),
        "sot": ParagraphStyle("sot", fontName="DejaVu", fontSize=10.5, leading=14, textColor=colors.HexColor("#555555")),
        "cap": ParagraphStyle("cap", fontName="DejaVu-Bold", fontSize=14, leading=18, textColor=VIOLA, spaceBefore=8, spaceAfter=6),
        "h": ParagraphStyle("h", fontName="DejaVu-Bold", fontSize=11, leading=14, spaceAfter=3),
        "p": ParagraphStyle("p", fontName="DejaVu", fontSize=9.2, leading=12.5),
        "pk": ParagraphStyle("pk", fontName="DejaVu-Bold", fontSize=8.8, leading=12),
        "pv": ParagraphStyle("pv", fontName="DejaVu", fontSize=8.8, leading=12),
        "nota": ParagraphStyle("nota", fontName="DejaVu-Oblique", fontSize=8.6, leading=11.5, textColor=colors.HexColor("#5a4a00")),
        "att": ParagraphStyle("att", fontName="DejaVu", fontSize=8.8, leading=12, textColor=colors.HexColor("#0f5132")),
        "piccolo": ParagraphStyle("piccolo", fontName="DejaVu", fontSize=8, leading=10, textColor=colors.grey, alignment=TA_CENTER),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=es["titolo"], author="MasterPayroll Academy")
    passi = es["passi"]
    n_op = sum(1 for p in passi if p["check"] is not None)
    s = [Paragraph("MasterPayroll Academy", st["sot"]), Paragraph(_esc(es["titolo"]), st["tit"]),
         Paragraph(f"Ferro &amp; Transenne Srl (azienda fittizia) · {len(passi)} passi: {n_op} operazioni che si verificano da "
                   f"sole e {len(passi) - n_op} letture · documento generato il {date.today():%d/%m/%Y}", st["sot"]),
         Spacer(1, 6 * mm)]
    come = [
        ("Dove trovi gli stessi passi", "nella finestra «Esercizio passo passo» a destra di ogni pagina del programma: "
                                         "se è chiusa, premi il pulsante giallo «Esercizio» in basso a destra. "
                                         "In alto nella finestra puoi scegliere l'esercizio."),
        ("Come leggere un passo", "la riga «Menu» dice quale voce aprire nella barra in alto; le righe seguenti sono i "
                                  "campi da compilare e i pulsanti da premere, con i nomi che vedi sullo schermo. "
                                  "Nella finestra il pulsante «Apri la pagina» ti porta direttamente alla pagina giusta."),
        ("Operazioni", "si spuntano da sole quando i tuoi dati sono giusti: non serve fare altro."),
        ("Letture", "servono a capire: quando hai letto, premi «Fatto: ho letto» nella finestra."),
        ("Si può rifare", "Cruscotto → in fondo scrivi RIPRISTINA → «Ripristina l'ambiente». Il ripristino cancella solo il "
                          "tuo ambiente."),
    ]
    t = Table([[Paragraph(_esc(k), st["pk"]), Paragraph(_esc(v), st["pv"])] for k, v in come], colWidths=[42 * mm, 136 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GRIGIO), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BOX", (0, 0), (-1, -1), 0.4, VIOLA), ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.white),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    s += [t, Spacer(1, 5 * mm)]
    # indice
    caps = []
    for i, p in enumerate(passi, 1):
        if not caps or caps[-1][0] != p["cap"]:
            caps.append([p["cap"], []])
        caps[-1][1].append((i, p["titolo"]))
    s.append(Paragraph("Indice dei passi", st["h"]))
    righe, spans = [], []
    for cap, elenco in caps:
        spans.append(("SPAN", (0, len(righe)), (1, len(righe))))
        righe.append([Paragraph(f"<b>{_esc(cap)}</b>", st["pv"]), ""])
        for i, tit in elenco:
            righe.append([Paragraph(str(i), st["pv"]), Paragraph(_esc(tit), st["pv"])])
    ti = Table(righe, colWidths=[14 * mm, 164 * mm])
    ti.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1)] + spans))
    s += [ti, PageBreak()]
    cap_corr = None
    for i, p in enumerate(passi, 1):
        if p["cap"] != cap_corr:
            cap_corr = p["cap"]
            s.append(Paragraph(_esc(cap_corr), st["cap"]))
        blocco = [Paragraph(f"Passo {i} · {_esc(p['titolo'])}", st["h"])]
        dati = []
        for k, v in p["campi"]:
            dati.append([Paragraph(_esc(k), st["pk"]), Paragraph(_esc(v), st["pv"])])
        if dati:
            tb = Table(dati, colWidths=[46 * mm, 132 * mm])
            stile = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9d0d6")),
                     ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
            if p["campi"] and p["campi"][0][0] == "Menu":
                stile.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efe6ec")))
            tb.setStyle(TableStyle(stile))
            blocco.append(tb)
        if p.get("attesa"):
            blocco += [Spacer(1, 1.5 * mm), Paragraph(f"<b>Cosa deve succedere:</b> {_esc(p['attesa'])}", st["att"])]
        if p.get("nota"):
            blocco += [Spacer(1, 1 * mm), Paragraph(f"Nota: {_esc(p['nota'])}", st["nota"])]
        tipo = ("Operazione: si spunta da sola quando i dati sono giusti." if p["check"] is not None
                else "Lettura: quando hai finito premi «Fatto: ho letto» nella finestra.")
        blocco += [Spacer(1, 1 * mm), Paragraph(f"<font color='#777777'>{tipo}</font>", st["pv"]), Spacer(1, 4.5 * mm)]
        s.append(KeepTogether(blocco))

    def piede(canvas, d):
        canvas.saveState()
        canvas.setFont("DejaVu", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(16 * mm, 9 * mm, "MasterPayroll Academy · ambiente formativo, dati simulati · non usare per paghe reali")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"pagina {d.page}")
        canvas.restoreState()

    doc.build(s, onFirstPage=piede, onLaterPages=piede)
    return buf.getvalue()
