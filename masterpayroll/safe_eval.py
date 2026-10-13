"""Equivalente di ``odoo.tools.safe_eval`` per le regole stipendio.

Come in Odoo il codice delle regole è Python vero: assegnazioni, if/else,
cicli for, comprensioni, chiamate di funzione e metodi. Per proteggere un
server condiviso da tutta la classe:

* l'albero sintattico è controllato nodo per nodo (niente import, lambda,
  def, classi, with, try, global; niente nomi o attributi che iniziano con
  ``_``; niente metodi di stringa che permettono di leggere attributi interni
  o di allocare memoria enorme);
* moltiplicazioni e potenze passano da funzioni che limitano le dimensioni;
* ``range`` è limitato e l'esecuzione si interrompe dopo un numero massimo di
  righe eseguite (cicli infiniti o troppo lunghi).

Uso, come in Odoo:
    safe_eval("contract.wage * 0.1", localdict)              # mode="eval"
    safe_eval("result = contract.wage", localdict, mode="exec")  # localdict["result"]
"""
import ast
import builtins
import functools
import sys
from decimal import ROUND_HALF_UP, Decimal


class SafeEvalError(Exception):
    """Errore leggibile nel codice di una regola."""


_ALLOWED_NODES = (
    ast.Module, ast.Expression, ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.If, ast.For,
    ast.While, ast.Break, ast.Continue, ast.Pass,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Name, ast.Load, ast.Store, ast.Del, ast.Constant, ast.Attribute, ast.Call, ast.keyword,
    ast.Subscript, ast.Slice, ast.Tuple, ast.List, ast.Dict, ast.Set, ast.Starred,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.JoinedStr, ast.FormattedValue,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not, ast.Invert, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
)
_DENIED_ATTRS = {
    "format", "format_map", "ljust", "rjust", "center", "zfill", "expandtabs", "mro",
    "gi_frame", "gi_code", "f_globals", "f_locals", "f_builtins", "func_globals",
}
MAX_CODE_LEN = 10000
MAX_LINES = 200_000
MAX_RANGE = 100_000
MAX_SEQ = 1_000_000


def _round_half_up(x, n=2):
    """Arrotondamento commerciale (0,005 → 0,01) senza errori di virgola mobile."""
    n = int(n)
    return float(Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def _safe_mul(a, b):
    for seq, k in ((a, b), (b, a)):
        if isinstance(seq, (str, bytes, list, tuple)) and isinstance(k, int):
            if len(seq) * max(k, 0) > MAX_SEQ:
                raise SafeEvalError("Sequenza troppo grande")
    return a * b


def _safe_pow(a, b):
    if isinstance(b, (int, float)) and abs(b) > 100:
        raise SafeEvalError("Esponente troppo grande")
    if isinstance(a, int) and isinstance(b, int) and abs(a) > 10 ** 6 and b > 10:
        raise SafeEvalError("Numero troppo grande")
    return a ** b


def _safe_range(*args):
    r = range(*args)
    if len(r) > MAX_RANGE:
        raise SafeEvalError(f"range troppo lungo (massimo {MAX_RANGE})")
    return r


SAFE_BUILTINS = {
    "True": True, "False": False, "None": None,
    "abs": abs, "all": all, "any": any, "bool": bool, "chr": chr, "dict": dict, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float, "int": int, "isinstance": isinstance,
    "len": len, "list": list, "map": map, "max": max, "min": min, "ord": ord, "range": _safe_range,
    "reduce": functools.reduce, "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "zip": zip, "Exception": Exception,
    "arrotonda": _round_half_up,
}


class _Transformer(ast.NodeTransformer):
    def visit_BinOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Mult):
            fn = "__mp_mul"
        elif isinstance(node.op, ast.Pow):
            fn = "__mp_pow"
        else:
            return node
        return ast.copy_location(ast.Call(func=ast.Name(id=fn, ctx=ast.Load()),
                                          args=[node.left, node.right], keywords=[]), node)

    def visit_AugAssign(self, node):
        self.generic_visit(node)
        if isinstance(node.op, (ast.Mult, ast.Pow)) and isinstance(node.target, ast.Name):
            fn = "__mp_mul" if isinstance(node.op, ast.Mult) else "__mp_pow"
            value = ast.Call(func=ast.Name(id=fn, ctx=ast.Load()),
                             args=[ast.Name(id=node.target.id, ctx=ast.Load()), node.value], keywords=[])
            return ast.copy_location(ast.Assign(targets=[ast.Name(id=node.target.id, ctx=ast.Store())],
                                                value=value), node)
        return node


def check_code(source, mode="eval"):
    """Controlla e compila. Solleva SafeEvalError con un messaggio per l'allievo."""
    if source is None:
        source = ""
    source = str(source).replace("\r\n", "\n")
    if len(source) > MAX_CODE_LEN:
        raise SafeEvalError("Codice troppo lungo")
    try:
        tree = ast.parse(source.strip() if mode == "eval" else source, mode=mode)
    except SyntaxError as exc:
        raise SafeEvalError(f"Errore di sintassi alla riga {exc.lineno}: {exc.msg}") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise SafeEvalError(f"Costrutto non ammesso: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise SafeEvalError(f"Nome non ammesso: {node.id}")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in _DENIED_ATTRS):
            raise SafeEvalError(f"Attributo non ammesso: {node.attr}")
        if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
            raise SafeEvalError("Costanti bytes non ammesse")
    tree = ast.fix_missing_locations(_Transformer().visit(tree))
    return compile(tree, "<regola>", mode)


def _line_limited(fn):
    counter = {"n": 0}

    def tracer(frame, event, arg):
        if frame.f_code.co_filename != "<regola>":
            return None
        if event == "line":
            counter["n"] += 1
            if counter["n"] > MAX_LINES:
                raise SafeEvalError("Esecuzione troppo lunga (ciclo infinito?)")
        return tracer

    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        return fn()
    finally:
        sys.settrace(old)


def safe_eval(expr, localdict=None, mode="eval"):
    """Valuta ``expr``. In mode="exec" modifica ``localdict`` (come Odoo) e restituisce None."""
    code = check_code(expr, mode)
    # Come Odoo, il localdict è usato come dizionario globale: così le comprensioni
    # vedono le variabili e le assegnazioni (result, result_qty...) restano nel localdict.
    glb = localdict if localdict is not None else {}
    injected = {"__builtins__": SAFE_BUILTINS, "__mp_mul": _safe_mul, "__mp_pow": _safe_pow}
    glb.update(injected)
    try:
        if mode == "eval":
            return _line_limited(lambda: eval(code, glb))  # noqa: S307 - albero verificato
        _line_limited(lambda: exec(code, glb))  # noqa: S102 - albero verificato
        return None
    except SafeEvalError:
        raise
    except ZeroDivisionError:
        raise SafeEvalError("Divisione per zero") from None
    except NameError as exc:
        raise SafeEvalError(f"Nome non definito: {exc.name}. Se è il codice di una regola, "
                            "forse non è stata calcolata (condizione falsa o sequenza successiva).") from None
    except Exception as exc:  # noqa: BLE001
        raise SafeEvalError(f"{type(exc).__name__}: {exc}") from None
    finally:
        for k in injected:
            glb.pop(k, None)


assert "eval" not in SAFE_BUILTINS and builtins  # promemoria: mai esporre eval/exec/open/__import__
