"""Strumenti fiscali italiani messi a disposizione delle regole come ``tools.xxx``.

In Odoo il metodo ``hr.payslip._get_tools_dict()`` esiste proprio perché le
localizzazioni aggiungano funzioni utili alle regole: qui la localizzazione
italiana aggiunge IRPEF, detrazioni, cuneo fiscale e trattamento integrativo.

USO DIDATTICO: valori secondo la normativa nota al momento della scrittura
(IRPEF 23/33/43% dal 2026, detrazioni artt. 12-13 TUIR, cuneo fiscale
L. 207/2024). Gli scaglioni si modificano dalla pagina Tabelle; tutto il resto
è qui, leggibile, per poterlo spiegare e verificare in aula.
"""
from .safe_eval import _round_half_up

SCAGLIONI_IRPEF_DEFAULT = [
    (0, 28000, 23.0),
    (28000, 50000, 33.0),
    (50000, None, 43.0),
]


def irpef_annua(reddito, scaglioni=None):
    """Imposta lorda annua per scaglioni progressivi."""
    scaglioni = scaglioni or SCAGLIONI_IRPEF_DEFAULT
    reddito = max(0.0, float(reddito))
    imposta = 0.0
    for da, a, aliquota in scaglioni:
        if reddito <= da:
            break
        tetto = reddito if a is None else min(reddito, a)
        imposta += (tetto - da) * aliquota / 100
    return imposta


def aliquota_marginale(reddito, scaglioni=None):
    scaglioni = scaglioni or SCAGLIONI_IRPEF_DEFAULT
    for _da, a, aliquota in scaglioni:
        if a is None or reddito <= a:
            return aliquota
    return scaglioni[-1][2]


def detrazione_lavoro(reddito):
    """Detrazione annua per lavoro dipendente (art. 13 c.1 TUIR), 365 giorni."""
    r = float(reddito)
    if r <= 0:
        return 0.0
    if r <= 15000:
        d = 1955.0
    elif r <= 28000:
        d = 1910 + 1190 * (28000 - r) / 13000
    elif r <= 50000:
        d = 1910 * (50000 - r) / 22000
    else:
        d = 0.0
    if 25000 < r <= 35000:
        d += 65
    return max(0.0, d)


def detrazione_coniuge(reddito):
    """Detrazione annua per coniuge a carico (art. 12 c.1 lett. a TUIR)."""
    r = float(reddito)
    if r <= 15000:
        d = 800 - 110 * r / 15000
    elif r <= 40000:
        d = 690
        for lo, hi, extra in ((29000, 29200, 10), (29200, 34700, 20), (34700, 35000, 30),
                              (35000, 35100, 20), (35100, 35200, 10)):
            if lo < r <= hi:
                d += extra
    elif r <= 80000:
        d = 690 * (80000 - r) / 40000
    else:
        d = 0.0
    return max(0.0, d)


def detrazione_figli(reddito, n_figli):
    """Detrazione annua per figli a carico dai 21 ai 30 anni (dal 2025): 950 € ciascuno,
    ridotta con coefficiente (95.000 + 15.000 per ogni figlio oltre il primo - reddito)."""
    if n_figli <= 0:
        return 0.0
    base = 95000 + 15000 * (n_figli - 1)
    coeff = max(0.0, (base - float(reddito)) / base)
    return 950 * n_figli * coeff


def detrazione_altri(reddito, n):
    """Detrazione annua per altri familiari a carico (ascendenti conviventi): 750 € ciascuno."""
    if n <= 0:
        return 0.0
    return 750 * n * max(0.0, (80000 - float(reddito)) / 80000)


def detrazioni_familiari(reddito, familiari, ref_date=None):
    """Somma delle detrazioni annue per i familiari a carico.

    I figli sotto i 21 anni non danno detrazione: per loro c'è l'Assegno Unico (INPS).
    La percentuale di carico (50% / 100%) riduce la detrazione del figlio.
    """
    from datetime import date
    ref_date = ref_date or date.today()
    totale = 0.0
    figli = [f for f in familiari if f.relazione == "figlio"]
    figli_validi = [f for f in figli if f.eta_al(ref_date) is not None and 21 <= f.eta_al(ref_date) < 30]
    if figli_validi:
        unitaria = detrazione_figli(reddito, len(figli_validi)) / len(figli_validi)
        totale += sum(unitaria * (f.percentuale or 100) / 100 for f in figli_validi)
    if any(f.relazione == "coniuge" for f in familiari):
        totale += detrazione_coniuge(reddito)
    altri = [f for f in familiari if f.relazione == "altro"]
    if altri:
        unitaria = detrazione_altri(reddito, len(altri)) / len(altri)
        totale += sum(unitaria * (f.percentuale or 100) / 100 for f in altri)
    return totale


def cuneo_indennita(reddito):
    """Somma esente annua del cuneo fiscale (redditi fino a 20.000 €)."""
    r = float(reddito)
    if r <= 0 or r > 20000:
        return 0.0
    perc = 7.1 if r <= 8500 else 5.3 if r <= 15000 else 4.8
    return r * perc / 100


def cuneo_detrazione(reddito):
    """Ulteriore detrazione annua del cuneo fiscale (20.000 - 40.000 €)."""
    r = float(reddito)
    if r <= 20000 or r > 40000:
        return 0.0
    if r <= 32000:
        return 1000.0
    return 1000 * (40000 - r) / 8000


def trattamento_integrativo_spetta(reddito, scaglioni=None):
    """Trattamento integrativo (ex bonus 100 €): reddito fino a 15.000 € e non incapiente."""
    r = float(reddito)
    if r <= 0 or r > 15000:
        return False
    return irpef_annua(r, scaglioni) > detrazione_lavoro(r) - 75


def irpef_dovuta_annua(imponibile, familiari=(), giorni=365, scaglioni=None, ref_date=None):
    """IRPEF netta dell'anno per il CONGUAGLIO: imposta lorda sugli scaglioni meno le detrazioni annue.

    La detrazione per lavoro dipendente spetta per i giorni di lavoro nell'anno (art. 13 TUIR: × giorni / 365);
    le detrazioni per familiari e l'ulteriore detrazione del cuneo si calcolano sul reddito dell'anno."""
    r = max(0.0, float(imponibile))
    lorda = irpef_annua(r, scaglioni)
    detr = detrazione_lavoro(r) * min(365, max(0, giorni)) / 365
    detr += detrazioni_familiari(r, list(familiari or []), ref_date)
    if 20000 < r <= 40000:
        detr += cuneo_detrazione(r)
    return round(max(0.0, lorda - detr), 2)


def aliquota_media_tfr(imponibile, mesi_servizio, scaglioni=None):
    """Tassazione separata del TFR (art. 19 TUIR): reddito di riferimento = imponibile × 12 / mesi di servizio;
    aliquota media = IRPEF del reddito di riferimento / reddito di riferimento."""
    if imponibile <= 0 or mesi_servizio <= 0:
        return 0.0
    rif = imponibile * 12 / mesi_servizio
    return round(irpef_annua(rif, scaglioni) / rif * 100, 2)


def make_helpers(scaglioni=None, ref_date=None):
    return {
        "arrotonda": _round_half_up,
        "irpef_annua": lambda reddito: irpef_annua(reddito, scaglioni),
        "aliquota_marginale": lambda reddito: aliquota_marginale(reddito, scaglioni),
        "detrazione_lavoro": detrazione_lavoro,
        "detrazione_coniuge": detrazione_coniuge,
        "detrazione_figli": detrazione_figli,
        "detrazioni_familiari": lambda reddito, familiari: detrazioni_familiari(
            reddito, [getattr(f, "_record", f) for f in familiari], ref_date),
        "cuneo_indennita": cuneo_indennita,
        "cuneo_detrazione": cuneo_detrazione,
        "trattamento_integrativo_spetta": lambda reddito: trattamento_integrativo_spetta(reddito, scaglioni),
        "irpef_dovuta_annua": lambda imponibile, familiari=(), giorni=365: irpef_dovuta_annua(
            imponibile, [getattr(f, "_record", f) for f in familiari], giorni, scaglioni, ref_date),
        "aliquota_media_tfr": lambda imponibile, mesi: aliquota_media_tfr(imponibile, mesi, scaglioni),
    }


HELPER_DOCS = [
    ("tools.arrotonda(x, n=2)", "Arrotondamento commerciale a n decimali (0,005 → 0,01). Anche senza 'tools.'."),
    ("tools.irpef_annua(reddito)", "Imposta lorda annua sugli scaglioni della pagina Tabelle."),
    ("tools.aliquota_marginale(reddito)", "Aliquota % dello scaglione in cui cade il reddito."),
    ("tools.detrazione_lavoro(reddito)", "Detrazione annua per lavoro dipendente (art. 13 TUIR)."),
    ("tools.detrazioni_familiari(reddito, employee.familiari)",
     "Detrazioni annue per coniuge, figli 21-30 anni, altri familiari a carico."),
    ("tools.detrazione_coniuge(reddito)", "Detrazione annua per il coniuge a carico."),
    ("tools.detrazione_figli(reddito, n)", "Detrazione annua per n figli a carico dai 21 ai 30 anni."),
    ("tools.cuneo_indennita(reddito)", "Somma esente annua del cuneo fiscale (fino a 20.000 €)."),
    ("tools.cuneo_detrazione(reddito)", "Ulteriore detrazione annua del cuneo fiscale (20.000-40.000 €)."),
    ("tools.trattamento_integrativo_spetta(reddito)", "Vero/Falso: spetta il trattamento integrativo?"),
    ("tools.irpef_dovuta_annua(imponibile, employee.familiari, giorni)",
     "Conguaglio: IRPEF netta dell'anno (scaglioni − detrazioni annue, lavoro × giorni/365)."),
    ("tools.aliquota_media_tfr(imponibile, mesi)", "Tassazione separata del TFR: aliquota media sul reddito di riferimento."),
    ("tools.math.floor(x) · ceil · sqrt …", "Funzioni matematiche (come tools.math in Odoo)."),
]
