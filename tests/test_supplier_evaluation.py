"""Fast tests of the production snapshot compute; Odoo declarations are stubbed."""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


def load_move_class():
    odoo = ModuleType("odoo")
    odoo.models = SimpleNamespace(Model=object)
    odoo.fields = SimpleNamespace(**{
        name: lambda *args, **kwargs: None for name in ("Selection", "Datetime", "Many2one")
    })
    odoo.api = SimpleNamespace(
        depends=lambda *args: lambda method: method,
        model_create_multi=lambda method: method,
        ondelete=lambda **kwargs: lambda method: method,
    )
    odoo._ = lambda value: value
    exceptions = ModuleType("odoo.exceptions")
    exceptions.AccessError = type("AccessError", (Exception,), {})
    exceptions.UserError = type("UserError", (Exception,), {})
    path = Path(__file__).resolve().parents[1] / "addons/supplier_evaluation/models/stock_move.py"
    spec = importlib.util.spec_from_file_location("supplier_move_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"odoo": odoo, "odoo.exceptions": exceptions}):
        spec.loader.exec_module(module)
    return module.StockMove


StockMove = load_move_class()


class TestSupplierPunctuality(unittest.TestCase):
    def move(self, hours=0, **values):
        agreed = datetime(2026, 10, 17, 12)
        record = dict(
            supplier_agreed_date_snapshot=agreed,
            supplier_receipt_date_snapshot=agreed + timedelta(hours=hours),
            supplier_punctuality="late",
        )
        record.update(values)
        return SimpleNamespace(**record)

    def test_early_on_time_and_boundary(self):
        moves = [self.move(hours) for hours in (-48, 0, 12, 24)]
        StockMove._compute_supplier_punctuality(moves)
        self.assertEqual([move.supplier_punctuality for move in moves], ["on_time"] * 4)

    def test_one_second_after_tolerance(self):
        move = self.move(24)
        move.supplier_receipt_date_snapshot += timedelta(seconds=1)
        StockMove._compute_supplier_punctuality([move])
        self.assertEqual(move.supplier_punctuality, "late")

    def test_missing_dates_are_unclassified(self):
        for field in ("supplier_agreed_date_snapshot", "supplier_receipt_date_snapshot"):
            with self.subTest(field=field):
                move = self.move(**{field: False})
                StockMove._compute_supplier_punctuality([move])
                self.assertIs(move.supplier_punctuality, False)

    def test_live_dates_do_not_affect_snapshot_result(self):
        move = self.move(48, date_planned=datetime(2030, 1, 1), date=datetime(2030, 1, 1))
        StockMove._compute_supplier_punctuality([move])
        self.assertEqual(move.supplier_punctuality, "late")
