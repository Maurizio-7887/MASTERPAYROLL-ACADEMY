"""Funzioni fiscali italiane usate dalle formule delle regole salariali.

ATTENZIONE - USO DIDATTICO: i valori riproducono la normativa come nota
al momento della scrittura (IRPEF a 3 scaglioni, detrazioni art. 13 TUIR,
cuneo fiscale L. 207/2024). Gli scaglioni IRPEF sono modificabili dalla
pagina "Tabelle"; gli altri importi sono qui, ben visibili, per poterli
spiegare in aula. Prima di usarli fuori dall'aula vanno verificati.
"""

# Scaglioni di default (modificabili per ambiente nella pagina Tabelle).
SCAGLIONI_IRPEF_DEFAULT = [
    # (da, a, aliquota %)   a=None significa "oltre"
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
    for da, a, aliquota in scaglioni:
        if a is None or reddito <= a:
            return aliquota
    return scaglioni[-1][2]


def detrazione_lavoro(reddito):
    """Detrazione annua per lavoro dipendente (art. 13 c.1 TUIR).

    Valori per contratto a tempo indeterminato, 365 giorni di lavoro.
    """
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


def cuneo_indennita(reddito):
    """Somma esente (non tassata) per redditi fino a 20.000 euro (L. 207/2024).

    Percentuale applicata al reddito di lavoro dipendente annuo.
    Restituisce l'importo ANNUO.
    """
    r = float(reddito)
    if r <= 0 or r > 20000:
        return 0.0
    if r <= 8500:
        perc = 7.1
    elif r <= 15000:
        perc = 5.3
    else:
        perc = 4.8
    return r * perc / 100


def cuneo_detrazione(reddito):
    """Ulteriore detrazione annua per redditi tra 20.000 e 40.000 euro."""
    r = float(reddito)
    if r <= 20000 or r > 40000:
        return 0.0
    if r <= 32000:
        return 1000.0
    return 1000 * (40000 - r) / 8000


def trattamento_integrativo_spetta(reddito, scaglioni=None):
    """Trattamento integrativo (ex bonus 100 euro) - versione base.

    Spetta se reddito <= 15.000 e l'imposta lorda supera la detrazione
    per lavoro dipendente diminuita di 75 euro (non si è "incapienti").
    """
    r = float(reddito)
    if r <= 0 or r > 15000:
        return False
    return irpef_annua(r, scaglioni) > detrazione_lavoro(r) - 75


def make_helpers(scaglioni=None):
    """Funzioni messe a disposizione delle formule (con gli scaglioni dell'ambiente)."""
    return {
        "irpef_annua": lambda reddito: irpef_annua(reddito, scaglioni),
        "aliquota_marginale": lambda reddito: aliquota_marginale(reddito, scaglioni),
        "detrazione_lavoro": detrazione_lavoro,
        "cuneo_indennita": cuneo_indennita,
        "cuneo_detrazione": cuneo_detrazione,
        "trattamento_integrativo_spetta":
            lambda reddito: trattamento_integrativo_spetta(reddito, scaglioni),
    }


HELPER_DOCS = [
    ("irpef_annua(reddito)", "Imposta lorda annua calcolata sugli scaglioni della pagina Tabelle."),
    ("aliquota_marginale(reddito)", "Aliquota % dello scaglione in cui cade il reddito."),
    ("detrazione_lavoro(reddito)", "Detrazione annua per lavoro dipendente (art. 13 TUIR)."),
    ("cuneo_indennita(reddito)", "Somma esente annua del cuneo fiscale (redditi fino a 20.000)."),
    ("cuneo_detrazione(reddito)", "Ulteriore detrazione annua del cuneo fiscale (20.000-40.000)."),
    ("trattamento_integrativo_spetta(reddito)", "Vero/Falso: spetta il trattamento integrativo?"),
    ("min(a, b) · max(a, b) · abs(x)", "Minimo, massimo, valore assoluto."),
    ("round(x, n) · arrotonda(x, n)", "Arrotondamento commerciale a n decimali (default 2)."),
]
