"""Exercise the production persistence hook without installing Odoo/schema.

The SQL cursor and ORM parent are substitutes, not an ORM integration test.
"""
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


class FakeParent:
    def __iter__(self):
        return iter(SimpleNamespace(id=record_id) for record_id in self.ids)

    def browse(self, record_id):
        return SimpleNamespace(id=record_id)

    def _write_multi(self, values):
        for record_id, vals in zip(self.ids, values):
            if "date_planned" in vals and record_id in self.env.cr.rows:
                value = vals["date_planned"]
                if isinstance(value, str):
                    value = datetime.fromisoformat(value)
                self.env.cr.rows[record_id]["date"] = value or None
        return "parent result"


def load_line_class():
    odoo = ModuleType("odoo")
    odoo.models = SimpleNamespace(Model=FakeParent)
    odoo.fields = SimpleNamespace(**{
        name: lambda *args, **kwargs: None
        for name in ("Datetime", "Boolean", "One2many", "Integer")
    })
    odoo.api = SimpleNamespace(
        depends=lambda *args: lambda method: method,
        model_create_multi=lambda method: method,
    )
    odoo._ = lambda value: value
    exceptions = ModuleType("odoo.exceptions")
    exceptions.AccessError = type("AccessError", (Exception,), {})
    exceptions.UserError = type("UserError", (Exception,), {})
    path = Path(__file__).resolve().parents[1] / "addons/supplier_evaluation/models/purchase_order_line.py"
    spec = importlib.util.spec_from_file_location("supplier_line_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"odoo": odoo, "odoo.exceptions": exceptions}):
        spec.loader.exec_module(module)
    return module.PurchaseOrderLine


Line = load_line_class()


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.result = []
        self.queries = []

    def execute(self, sql, params):
        sql = " ".join(sql.split())
        self.queries.append(sql)
        ids = params[0]
        if sql.startswith("SELECT DISTINCT order_id"):
            self.result = [(record_id,) for record_id in sorted({self.rows[i]["order"] for i in ids if i in self.rows})]
        elif sql.startswith("SELECT id FROM purchase_order"):
            self.result = [(i,) for i in ids]
        elif sql.startswith("SELECT line.id"):
            self.result = [
                (i, row["date"], row["pending"], row["display_type"], row["state"])
                for i in sorted(ids) if (row := self.rows.get(i))
            ]
        elif sql.startswith("SELECT id, date_planned"):
            self.result = [(i, self.rows[i]["date"]) for i in sorted(ids) if i in self.rows]
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return self.result


class FakeRevisions:
    def __init__(self):
        self.events = []

    def sudo(self):
        return self

    def search(self, domain, limit):
        self.assert_limit = limit
        line_id = domain[0][2]
        return next((event for event in reversed(self.events) if event.line_id == line_id), False)

    def _append_revision(self, line, previous_date, new_date, revision_type):
        event = SimpleNamespace(
            line_id=line.id, previous_date=previous_date,
            new_date=new_date or False, revision_type=revision_type,
        )
        self.events.append(event)
        return event


class FakeEnv:
    def __init__(self, rows, revisions):
        self.cr = FakeCursor(rows)
        self.revisions = revisions

    def __getitem__(self, model):
        assert model == "supplier.evaluation.deadline.revision"
        return self.revisions


class TestDeadlinePersistence(unittest.TestCase):
    def setUp(self):
        self.date = datetime(2026, 10, 17, 12)
        self.revisions = FakeRevisions()
        self.rows = {1: self.row()}
        self.lines = object.__new__(Line)
        self.lines.ids = [1]
        self.lines.env = FakeEnv(self.rows, self.revisions)

    def row(self, **values):
        result = dict(date=self.date, pending=False, display_type=False, state="purchase", order=10)
        result.update(values)
        return result

    def initial(self, line_id=1):
        self.revisions._append_revision(SimpleNamespace(id=line_id), False, self.date, "initial")

    def persist(self, date):
        return self.lines._write_multi([{"date_planned": date}])

    def test_real_change_is_technical(self):
        self.initial()
        new = self.date + timedelta(days=2)
        self.assertEqual(self.persist(new), "parent result")
        self.assertEqual(len(self.revisions.events), 2)
        revision = self.revisions.events[-1]
        self.assertEqual((revision.previous_date, revision.new_date), (self.date, new))
        self.assertEqual(revision.revision_type, "technical")
        self.assertTrue(any("FOR UPDATE OF line" in sql for sql in self.lines.env.cr.queries))

    def test_identical_values_and_repeated_flush_are_not_events(self):
        self.initial()
        self.persist(self.date.isoformat(sep=" "))
        self.persist(self.date)
        self.lines._write_multi([{"name": "Other field"}])
        self.assertEqual(len(self.revisions.events), 1)

    def test_successive_dates_preserve_each_persisted_transition(self):
        self.initial()
        for days in (1, 2, 2, -1):
            self.persist(self.date + timedelta(days=days))
        self.assertEqual(len(self.revisions.events), 4)
        self.assertEqual([event.revision_type for event in self.revisions.events[1:]], ["technical"] * 3)

    def test_new_and_unconfirmed_records_do_not_emit_revisions(self):
        for row in (self.row(pending=True), self.row(state="draft"), self.row(display_type="line_note")):
            with self.subTest(row=row):
                self.rows[1] = row
                self.persist(self.date + timedelta(days=2))
                self.assertFalse(self.revisions.events)

    def test_legacy_change_records_unknown_baseline(self):
        self.persist(self.date + timedelta(days=2))
        self.assertEqual([event.revision_type for event in self.revisions.events], ["unknown_initial", "technical"])
        self.assertEqual(self.revisions.events[0].new_date, self.date)

    def test_virtual_ids_are_not_audited_by_the_hook(self):
        self.lines.ids = [object()]
        self.lines._write_multi([{"date_planned": self.date + timedelta(days=2)}])
        self.assertFalse(self.lines.env.cr.queries)
        self.assertFalse(self.revisions.events)

    def test_batch_changes_are_per_line(self):
        self.rows[2] = self.row(order=11)
        self.lines.ids = [1, 2]
        self.initial(1)
        self.initial(2)
        self.lines._write_multi([
            {"date_planned": self.date + timedelta(days=1)},
            {"date_planned": self.date + timedelta(days=3)},
        ])
        changes = self.revisions.events[2:]
        self.assertEqual([event.line_id for event in changes], [1, 2])
        self.assertEqual([event.new_date for event in changes], [self.date + timedelta(days=1), self.date + timedelta(days=3)])

    def test_current_revision_is_not_duplicated(self):
        new = self.date + timedelta(days=2)
        self.revisions._append_revision(SimpleNamespace(id=1), self.date, new, "technical")
        self.persist(new)
        self.assertEqual(len(self.revisions.events), 1)


def load_revision_class():
    class Parent:
        def sudo(self):
            return self

        def search(self, domain, limit):
            return SimpleNamespace(sequence=0)

        def create(self, values):
            return values

    class DateField:
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def now():
            return datetime(2026, 10, 17, 12)

    odoo = ModuleType("odoo")
    odoo.models = SimpleNamespace(Model=Parent)
    odoo.fields = SimpleNamespace(Datetime=DateField, **{
        name: lambda *args, **kwargs: None
        for name in ("Many2one", "One2many", "Integer", "Selection", "Char", "Text")
    })
    odoo.api = SimpleNamespace(
        model_create_multi=lambda method: method,
        model=lambda method: method,
        ondelete=lambda **kwargs: lambda method: method,
    )
    odoo._ = lambda value: value
    exceptions = ModuleType("odoo.exceptions")
    exceptions.AccessError = type("AccessError", (Exception,), {})
    exceptions.UserError = type("UserError", (Exception,), {})
    path = Path(__file__).resolve().parents[1] / "addons/supplier_evaluation/models/deadline_revision.py"
    spec = importlib.util.spec_from_file_location("supplier_revision_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"odoo": odoo, "odoo.exceptions": exceptions}):
        spec.loader.exec_module(module)
    return module.SupplierDeadlineRevision


Revision = load_revision_class()


class TestRevisionAttribution(unittest.TestCase):
    def setUp(self):
        self.date = datetime(2026, 10, 17, 12)
        self.revisions = object.__new__(Revision)
        self.revisions.env = SimpleNamespace(uid=42)
        self.line = SimpleNamespace(
            id=1, ensure_one=lambda: None, company_id=SimpleNamespace(id=1),
            name="Test line", order_id=SimpleNamespace(
                id=10, name="PO10", partner_id=SimpleNamespace(id=2, display_name="Test vendor"),
            ),
        )

    def test_technical_postponement_has_no_supplier_attribution(self):
        values = self.revisions._append_revision(
            self.line, self.date, self.date + timedelta(days=2), "technical",
        )
        self.assertEqual(values["revision_type"], "technical")
        self.assertEqual(values["change_source"], "unverified")
        self.assertEqual(values["change_direction"], "postponed")
        self.assertEqual(values["changed_by_id"], 42)

    def test_baselines_do_not_misrepresent_unknown_originals(self):
        for kind in ("initial", "unknown_initial"):
            with self.subTest(kind=kind):
                values = self.revisions._append_revision(self.line, False, self.date, kind)
                self.assertEqual(values["revision_type"], kind)
                self.assertEqual(values["change_source"], "baseline")
