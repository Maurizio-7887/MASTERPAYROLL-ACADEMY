"""Valutatore sicuro delle formule delle regole salariali.

Le regole (come nel modulo Payroll di OCA/Odoo) contengono formule scritte
dagli allievi. Qui NON si usa eval() di Python: l'albero sintattico viene
controllato nodo per nodo e sono ammessi solo aritmetica, confronti,
condizioni, accesso ad attributi "pubblici" e poche funzioni di libreria.

Una formula può essere:
  * una singola espressione:         contract.minimo * contract.part_time / 100
  * più righe con assegnazioni, che terminano con  result = ...
        base = categories.BASE
        result = base * 9.19 / 100
"""
import ast
from decimal import ROUND_HALF_UP, Decimal


class FormulaError(Exception):
    """Errore in una formula: messaggio leggibile per l'allievo."""


_ALLOWED_NODES = (
    ast.Module, ast.Expression, ast.Expr, ast.Assign, ast.If, ast.Pass,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.Attribute, ast.Call,
    ast.Tuple, ast.List,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.keyword,
)

_MAX_FORMULA_LEN = 2000


def _check(tree):
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise FormulaError(
                f"Costrutto non ammesso nelle formule: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise FormulaError("Attributi che iniziano con '_' non ammessi")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise FormulaError("Nomi che iniziano con '_' non ammessi")
        if isinstance(node, ast.Constant) and not isinstance(
                node.value, (int, float, bool, str, type(None))):
            raise FormulaError("Costante non ammessa")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            # evita numeri enormi tipo 10**10**10
            if isinstance(node.right, ast.Constant) and abs(node.right.value) > 10:
                raise FormulaError("Esponente troppo grande")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaError("Si possono chiamare solo le funzioni elencate nella guida")


def _round_half_up(x, n=2):
    """Arrotondamento commerciale (0,005 -> 0,01), senza gli errori dei float."""
    n = int(n)
    q = Decimal(1).scaleb(-n)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))


BASE_FUNCTIONS = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": _round_half_up,
    "arrotonda": _round_half_up,
    "int": int,
    "float": float,
}


def compile_formula(source):
    if source is None or not str(source).strip():
        return None
    source = str(source).replace("\r\n", "\n").strip()
    if len(source) > _MAX_FORMULA_LEN:
        raise FormulaError("Formula troppo lunga")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise FormulaError(f"Errore di sintassi alla riga {exc.lineno}: {exc.msg}") from None
    _check(tree)
    single_expr = len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)
    if single_expr:
        expr = ast.Expression(tree.body[0].value)
        return ("expr", compile(expr, "<formula>", "eval"))
    return ("exec", compile(tree, "<formula>", "exec"))


def evaluate(source, namespace, default=0.0):
    """Valuta la formula e restituisce il risultato.

    Per formule su più righe il risultato è la variabile ``result``.
    """
    compiled = compile_formula(source)
    if compiled is None:
        return default
    env = {"__builtins__": {}}
    env.update(BASE_FUNCTIONS)
    env.update(namespace)
    kind, code = compiled
    try:
        if kind == "expr":
            return eval(code, env)  # noqa: S307 - albero verificato da _check
        exec(code, env)  # noqa: S102 - albero verificato da _check
    except FormulaError:
        raise
    except ZeroDivisionError:
        raise FormulaError("Divisione per zero") from None
    except Exception as exc:  # noqa: BLE001
        raise FormulaError(f"{type(exc).__name__}: {exc}") from None
    if "result" not in env:
        raise FormulaError("Formula su più righe: manca l'assegnazione 'result = ...'")
    return env["result"]
