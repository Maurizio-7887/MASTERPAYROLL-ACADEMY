"""Motore di calcolo del cedolino.

Stessa logica del modulo Payroll di OCA/Odoo, riscritta per l'aula:
  1. si prende la struttura retributiva del contratto;
  2. le regole vengono eseguite in ordine di sequenza;
  3. ogni regola ha una CONDIZIONE (se falsa la regola è saltata) e una
     FORMULA che calcola l'importo;
  4. ogni importo si somma al totale della sua CATEGORIA, così le regole
     successive possono usare  categories.BASE,  rules.INPS_DIP, ecc.
"""

from .fiscale import SCAGLIONI_IRPEF_DEFAULT, make_helpers
from .models import (now, Cedolino, CedolinoRiga, Parametro, ScaglioneIrpef, db,
                     INPUT_CODES)
from .safe_eval import FormulaError, evaluate, _round_half_up


class Bag:
    """Contenitore a sola lettura: bag.CODICE restituisce 0 se non esiste."""

    def __init__(self, data=None, default=0.0):
        object.__setattr__(self, "_data", dict(data or {}))
        object.__setattr__(self, "_default", default)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name, self._default)

    def __setattr__(self, name, value):
        raise FormulaError("I dati del calcolo sono in sola lettura")

    def add(self, name, value):
        self._data[name] = self._data.get(name, 0.0) + value

    def set(self, name, value):
        self._data[name] = value

    def as_dict(self):
        return dict(self._data)


class CalcoloError(Exception):
    def __init__(self, codice, messaggio):
        super().__init__(f"Regola {codice}: {messaggio}")
        self.codice = codice
        self.messaggio = messaggio


def scaglioni_ws(workspace_id):
    rows = ScaglioneIrpef.query.filter_by(workspace_id=workspace_id).order_by(ScaglioneIrpef.da).all()
    if not rows:
        return SCAGLIONI_IRPEF_DEFAULT
    return [(r.da, r.a, r.aliquota) for r in rows]


def parametri_ws(workspace_id):
    return {p.codice: p.valore for p in Parametro.query.filter_by(workspace_id=workspace_id)}


def _num(value, codice, campo):
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    raise CalcoloError(codice, f"la {campo} deve dare un numero, ha dato {value!r}")


def build_namespace(ced: Cedolino, param: dict, scaglioni):
    c = ced.contratto
    d = ced.dipendente
    contract = Bag({
        "minimo": c.minimo or 0.0,
        "superminimo": c.superminimo or 0.0,
        "scatti_n": c.scatti_n or 0,
        "scatto_importo": c.scatto_importo or 0.0,
        "part_time": c.part_time or 0.0,
        "ore_settimanali": c.ore_settimanali or 0.0,
        "divisore": c.divisore_orario or 173.0,
        "add_reg_rata": c.add_reg_rata or 0.0,
        "add_com_rata": c.add_com_rata or 0.0,
        "livello": c.livello.codice if c.livello else "",
        "tipo": c.tipo,
        "retribuzione_mensile": c.retribuzione_mensile,
    })
    employee = Bag({
        "qualifica": d.qualifica, "reparto": d.reparto, "matricola": d.matricola,
    }, default="")
    inputs = Bag({code: 0.0 for code in INPUT_CODES})
    for i in ced.inputs:
        inputs.set(i.codice, i.valore or 0.0)
    inps_dip = param.get("INPS_DIP", 9.19)
    mensilita = param.get("MENSILITA", 13)
    ns = {
        "contract": contract,
        "employee": employee,
        "inputs": inputs,
        "param": Bag(param),
        "categories": Bag(),
        "rules": Bag(),
        "anno": ced.anno,
        "mese": ced.mese,
        "tipo": ced.tipo,
        "giorni": ced.giorni_lavorati or 0.0,
        "ore": ced.ore_lavorate or 0.0,
        "retribuzione_mensile": contract.retribuzione_mensile,
        "reddito_ordinario_annuo": round(contract.retribuzione_mensile * 12 * (1 - inps_dip / 100), 2),
        "reddito_presunto_annuo": round(contract.retribuzione_mensile * mensilita * (1 - inps_dip / 100), 2),
    }
    ns.update(make_helpers(scaglioni))
    return ns


def calcola(ced: Cedolino, commit=True):
    """Esegue le regole e salva le righe. Restituisce (ok, messaggio)."""
    if ced.stato == "confermato":
        return False, "Cedolino confermato: non si può ricalcolare."
    if not ced.contratto:
        ced.errore = "Il dipendente non ha un contratto."
        ced.stato = "bozza"
        if commit:
            db.session.commit()
        return False, ced.errore
    struttura = ced.struttura or ced.contratto.struttura
    if not struttura:
        ced.errore = "Nessuna struttura retributiva assegnata."
        if commit:
            db.session.commit()
        return False, ced.errore
    ced.struttura = struttura

    param = parametri_ws(ced.workspace_id)
    ns = build_namespace(ced, param, scaglioni_ws(ced.workspace_id))
    righe = []
    try:
        for regola in sorted(struttura.regole, key=lambda r: (r.sequenza, r.id or 0)):
            if not regola.attiva:
                continue
            cod = regola.codice
            try:
                if regola.condizione and regola.condizione.strip():
                    if not evaluate(regola.condizione, ns, default=True):
                        continue
                importo = _round_half_up(_num(evaluate(regola.formula, ns), cod, "formula"), 2)
                qta = evaluate(regola.quantita_formula, ns, default=None)
                base = evaluate(regola.base_formula, ns, default=None)
            except FormulaError as exc:
                raise CalcoloError(cod, str(exc)) from None
            except (ArithmeticError, ValueError, TypeError) as exc:
                raise CalcoloError(cod, f"risultato non valido ({exc})") from None
            qta = None if qta is None else _round_half_up(_num(qta, cod, "quantità"), 2)
            base = None if base is None else _round_half_up(_num(base, cod, "base"), 4)
            ns["rules"].set(cod, importo)
            cat = regola.categoria
            if cat:
                ns["categories"].add(cat.codice, importo)
            righe.append(CedolinoRiga(
                sequenza=regola.sequenza, codice=cod, nome=regola.nome,
                categoria_codice=cat.codice if cat else "",
                categoria_tipo=cat.tipo if cat else "info",
                quantita=qta, base=base, importo=importo,
                stampa=regola.stampa, registro=regola.registro or ""))
    except CalcoloError as exc:
        ced.errore = str(exc)
        ced.stato = "bozza"
        if commit:
            db.session.commit()
        return False, ced.errore

    ced.righe = righe
    rules = ns["rules"]
    ced.lordo = rules.LORDO
    ced.netto = rules.NETTO
    ced.costo = rules.COSTO
    ced.errore = ""
    ced.stato = "calcolato"
    ced.calcolato_at = now()
    if commit:
        db.session.commit()
    return True, "Cedolino calcolato."
