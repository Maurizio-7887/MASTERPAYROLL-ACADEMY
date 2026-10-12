import pytest

from masterpayroll.fiscale import (cuneo_detrazione, cuneo_indennita, detrazione_lavoro,
                                   irpef_annua)
from masterpayroll.safe_eval import FormulaError, evaluate


def test_irpef_scaglioni():
    assert irpef_annua(20000) == pytest.approx(4600)
    assert irpef_annua(28000) == pytest.approx(6440)
    assert irpef_annua(40000) == pytest.approx(6440 + 12000 * 0.33)
    assert irpef_annua(60000) == pytest.approx(6440 + 22000 * 0.33 + 10000 * 0.43)


def test_detrazioni():
    assert detrazione_lavoro(12000) == 1955
    assert detrazione_lavoro(20000) == pytest.approx(1910 + 1190 * 8000 / 13000)
    assert detrazione_lavoro(30000) == pytest.approx(1910 * 20000 / 22000 + 65)
    assert detrazione_lavoro(55000) == 0


def test_cuneo():
    assert cuneo_indennita(8000) == pytest.approx(568)
    assert cuneo_indennita(19000) == pytest.approx(912)
    assert cuneo_indennita(21000) == 0
    assert cuneo_detrazione(25000) == 1000
    assert cuneo_detrazione(36000) == pytest.approx(500)


def test_safe_eval_ok():
    assert evaluate("1 + 2 * 3", {}) == 7
    assert evaluate("x = 4\nresult = x * 2", {}) == 8
    assert evaluate("round(1.005, 2)", {}) == 1.01
    assert evaluate("5 if a > 1 else 0", {"a": 2}) == 5


@pytest.mark.parametrize("src", [
    "__import__('os')", "().__class__", "open('x')", "[x for x in range(3)]",
    "lambda: 1", "import os", "a[0]", "(1).real.__class__", "9 ** 99",
])
def test_safe_eval_blocca(src):
    with pytest.raises(FormulaError):
        evaluate(src, {"a": [1]})


def test_cedolino_rossi(app):
    from masterpayroll import ensure_workspace
    from masterpayroll.models import Cedolino, Dipendente, User
    with app.app_context():
        ws = ensure_workspace(User.query.first())
        c = (Cedolino.query.join(Dipendente).filter(Dipendente.cognome == "Rossi",
                                                    Cedolino.workspace_id == ws.id).one())
        assert c.stato == "confermato"
        # verifica "a mano" del percorso lordo -> netto
        assert c.lordo == pytest.approx(2410 + 150 + 3 * 32.5)
        assert c.importo("INPS_DIP") == pytest.approx(round(2658 * 0.0919, 2))
        imp_fisc = c.lordo - c.importo("INPS_DIP")
        assert c.importo("IMP_FISC") == pytest.approx(imp_fisc, abs=0.01)
        irpef_lorda = irpef_annua(imp_fisc * 12) / 12
        assert c.importo("IRPEF_LORDA") == pytest.approx(irpef_lorda, abs=0.01)
        netto = c.lordo - c.importo("INPS_DIP") - c.importo("IRPEF") - 45 - 18
        assert c.netto == pytest.approx(netto, abs=0.01)
        # Galli supera la 1a fascia pensionabile
        g = (Cedolino.query.join(Dipendente).filter(Dipendente.cognome == "Galli",
                                                    Cedolino.workspace_id == ws.id).one())
        assert g.importo("INPS_AGG") > 0
        # Ferri (part-time 50%) ha trattamento integrativo e somma esente del cuneo
        f = (Cedolino.query.join(Dipendente).filter(Dipendente.cognome == "Ferri",
                                                    Cedolino.workspace_id == ws.id).one())
        assert f.importo("TRATT_INT") == pytest.approx(100)
        assert f.importo("IND_CUNEO") > 0
