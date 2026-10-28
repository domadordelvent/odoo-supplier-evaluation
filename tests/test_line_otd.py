"""Run production OTD methods locally; ORM substitutes do not validate SQL/Odoo."""
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch


class Records(list):
    def filtered(self, predicate):
        if isinstance(predicate, str):
            return Records(row for row in self if getattr(row, predicate))
        return Records(row for row in self if predicate(row))

    def mapped(self, name):
        return [getattr(row, name) for row in self]


class Parent:
    def __iter__(self):
        return iter([self])

    def ensure_one(self):
        pass

    def sudo(self):
        return self

    def with_context(self, **kwargs):
        return self

    def invalidate_recordset(self, names):
        pass

    def filtered(self, predicate):
        return Records([self]).filtered(predicate)

    def write(self, values):
        self.writes.append(values)
        self.__dict__.update(values)
        return True

    def create(self, values):
        return values


class SearchModel:
    def __init__(self, rows=()):
        self.rows = rows
        self.domains = []

    def sudo(self):
        return self

    def search(self, domain, order, limit):
        self.domains.append(domain)
        rows = list(self.rows)
        for name, op, value in domain:
            if op == '=':
                rows = [r for r in rows if getattr(r, name) == value]
            elif op == '<=':
                rows = [r for r in rows if getattr(r, name) <= value]
            elif op == '<':
                rows = [r for r in rows if getattr(r, name) < value]
            else:
                raise AssertionError(op)
        if order == 'confirmed_at desc, id desc':
            rows.sort(key=lambda r: (r.confirmed_at, r.id), reverse=True)
        elif order == 'id desc':
            rows.sort(key=lambda r: r.id, reverse=True)
        elif order == 'sequence, id':
            rows.sort(key=lambda r: (r.sequence, r.id))
        else:
            raise AssertionError(order)
        return rows[0] if rows else EmptyRecord()


# An actual falsy empty record, with accessible empty relational fields.
class EmptyRecord:
    supplier_id = False

    def __bool__(self):
        return False


class Env(dict):
    context = {}


def load_production():
    class DateField:
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def now():
            return datetime(2026, 10, 28, 12)

    odoo = ModuleType('odoo')
    odoo.models = NS(Model=Parent)
    odoo.fields = NS(Datetime=DateField, **{
        name: lambda *args, **kwargs: None for name in ('Selection', 'Float', 'Many2one')
    })
    odoo.api = NS(model_create_multi=lambda f: f, ondelete=lambda **kw: lambda f: f)
    odoo._ = lambda text: text
    exceptions = ModuleType('odoo.exceptions')
    exceptions.AccessError = type('AccessError', (Exception,), {})
    exceptions.UserError = type('UserError', (Exception,), {})
    floats = ModuleType('odoo.tools.float_utils')
    # Fixtures use integral unit multiples; rounding behavior is tested in Odoo.
    floats.float_compare = lambda a, b, precision_rounding: (a > b) - (a < b)
    path = Path(__file__).resolve().parents[1] / 'addons/supplier_evaluation/models/purchase_line_otd.py'
    spec = importlib.util.spec_from_file_location('line_otd_under_test', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict('sys.modules', {
        'odoo': odoo, 'odoo.exceptions': exceptions, 'odoo.tools.float_utils': floats,
    }):
        spec.loader.exec_module(module)
    return module


production = load_production()


class TestLineOTD(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 28, 12)
        self.vendor = NS(id=7)
        self.confirmations = SearchModel()
        self.baselines = SearchModel([NS(
            id=1, purchase_line_id=3, revision_type='initial', sequence=1, supplier_id=self.vendor,
        )])
        self.line = production.PurchaseLineOTD()
        self.line.__dict__.update(
            id=3, env=Env({
                'supplier.evaluation.deadline.confirmation': self.confirmations,
                'supplier.evaluation.deadline.revision': self.baselines,
            }), writes=[], supplier_otd_captured_at=False, display_type=False,
            order_id=NS(state='purchase', partner_id=self.vendor),
            qty_received_method='stock_moves', product_id=NS(type='consu'),
            product_qty=2, qty_received=2, product_uom=NS(id=1, rounding=1),
            supplier_original_date_known=True, supplier_original_date=self.now,
            date_planned=self.now + timedelta(days=50),
        )
        self.receipts = Records([self.receipt()])
        self.line._get_po_line_moves = lambda: self.receipts

    def receipt(self, **values):
        record = dict(
            state='done', scrapped=False, location_id=NS(usage='supplier'),
            location_dest_id=NS(usage='internal'), quantity=2, product_uom=NS(rounding=1),
            supplier_deadline_captured_at=self.now,
            supplier_receipt_date_snapshot=self.now,
            picking_id=NS(partner_id=self.vendor),
        )
        record.update(values)
        return NS(**record)

    def confirmation(self, days, confirmed_hours=-1, **values):
        record = dict(
            id=len(self.confirmations.rows) + 1, purchase_line_id=3, supplier_id=7,
            confirmed_at=self.now + timedelta(hours=confirmed_hours),
            new_agreed_date=self.now + timedelta(days=days),
        )
        record.update(values)
        result = NS(**record)
        self.confirmations.rows = [*self.confirmations.rows, result]
        return result

    def capture(self):
        self.line._supplier_capture_otd(self.line._supplier_otd_confirmation_limits())
        return self.line.writes[-1]

    def test_original_is_used_despite_unconfirmed_planned_date(self):
        self.line.supplier_original_date = self.now - timedelta(days=3)
        result = self.capture()
        self.assertEqual(result['supplier_otd_status'], 'late')
        self.assertEqual(result['supplier_otd_deadline'], self.line.supplier_original_date)
        self.assertFalse(result['supplier_otd_confirmation_id'])

    def test_latest_confirmation_before_completion_wins(self):
        self.confirmation(-5, -3)
        latest = self.confirmation(1, -2)
        self.confirmation(20, 1)
        result = self.capture()
        self.assertEqual(result['supplier_otd_confirmation_id'], latest.id)
        self.assertEqual(result['supplier_otd_deadline'], latest.new_agreed_date)
        self.assertEqual(result['supplier_otd_status'], 'on_time')

    def test_confirmed_advance_can_make_completion_late(self):
        confirmation = self.confirmation(-2)
        result = self.capture()
        self.assertEqual(result['supplier_otd_confirmation_id'], confirmation.id)
        self.assertEqual(result['supplier_otd_status'], 'late')

    def test_confirmation_ties_use_last_id(self):
        self.confirmation(-2)
        last = self.confirmation(1)
        self.assertEqual(self.capture()['supplier_otd_confirmation_id'], last.id)

    def test_returned_net_quantity_keeps_line_incomplete(self):
        self.line.qty_received = 1
        self.receipts = Records([self.receipt(quantity=2), self.receipt(quantity=1)])
        self.line._supplier_capture_otd({self.line.id: 0})
        self.assertEqual(self.line.writes, [])

    def test_already_complete_legacy_line_is_not_pending(self):
        self.assertFalse(self.line._supplier_otd_pending_lines())

    def test_future_and_unrelated_confirmations_are_excluded(self):
        for kwargs in ({'confirmed_hours': 1},
                       {'supplier_id': 8}, {'purchase_line_id': 4}):
            with self.subTest(**kwargs):
                self.confirmations.rows = []
                self.confirmation(10, **kwargs)
                self.assertEqual(self.line._supplier_otd_agreement(self.now, 100), (self.now, False))

    def test_same_second_agreement_requires_presence_before_receipt(self):
        limit = self.line._supplier_otd_confirmation_limits()[self.line.id]
        agreement = self.confirmation(10, confirmed_hours=0)
        self.assertEqual(self.line._supplier_otd_agreement(self.now, limit), (self.now, False))
        limit = self.line._supplier_otd_confirmation_limits()[self.line.id]
        self.assertEqual(
            self.line._supplier_otd_agreement(self.now, limit),
            (agreement.new_agreed_date, agreement.id),
        )

    def test_24_hour_boundary_and_one_second_late(self):
        for seconds, status in ((-1, 'on_time'), (0, 'on_time'), (1, 'late')):
            with self.subTest(seconds=seconds):
                self.line.supplier_otd_captured_at = False
                self.receipts[0].supplier_receipt_date_snapshot = self.now + timedelta(hours=24, seconds=seconds)
                self.assertEqual(self.capture()['supplier_otd_status'], status)

    def test_partial_waits_until_last_receipt(self):
        self.line.qty_received = 1
        self.assertEqual(self.line._supplier_otd_pending_lines(), [self.line])
        self.line._supplier_capture_otd({self.line.id: 0})
        self.assertEqual(self.line.writes, [])
        self.line.qty_received = 2
        self.receipts.append(self.receipt(supplier_receipt_date_snapshot=self.now + timedelta(days=2)))
        self.assertEqual(self.capture()['supplier_otd_status'], 'late')

    def test_overreceipt_is_one_observation_with_quantity_context(self):
        self.line.qty_received = 3
        result = self.capture()
        self.assertEqual(result['supplier_otd_ordered_qty'], 2)
        self.assertEqual(result['supplier_otd_received_qty'], 3)
        self.assertEqual(result['supplier_otd_uom_id'], 1)
        self.assertEqual(result['supplier_otd_supplier_id'], 7)

    def test_later_confirmation_dates_quantities_and_returns_cannot_rewrite(self):
        first = self.capture().copy()
        self.confirmation(20, 1)
        self.line.product_qty = 50
        self.line.qty_received = 0
        self.line.supplier_original_date = self.now + timedelta(days=100)
        self.line._supplier_capture_otd({self.line.id: 0})
        self.assertEqual(self.line.writes, [first])
        self.assertEqual(self.line._supplier_otd_pending_lines(), [])

    def test_unknown_original_or_changed_supplier_does_not_invent_deadline(self):
        for unknown in ('unknown', 'different_vendor'):
            with self.subTest(unknown=unknown):
                self.line.supplier_otd_captured_at = False
                if unknown == 'unknown':
                    self.line.supplier_original_date_known = False
                else:
                    self.line.supplier_original_date_known = True
                    self.baselines.rows[0].supplier_id = NS(id=8)
                result = self.capture()
                self.assertEqual(result['supplier_otd_status'], 'unknown')
                self.assertFalse(result['supplier_otd_deadline'])

    def test_missing_legacy_receipt_capture_is_unknown_without_modifying_receipts(self):
        self.receipts.append(self.receipt(supplier_deadline_captured_at=False))
        before = [vars(r).copy() for r in self.receipts]
        result = self.capture()
        self.assertEqual(result['supplier_otd_status'], 'unknown')
        self.assertFalse(result['supplier_otd_completed_at'])
        self.assertEqual([vars(r) for r in self.receipts], before)

    def test_cancelled_scrapped_outgoing_and_zero_moves_do_not_set_completion(self):
        self.receipts += [
            self.receipt(state='cancel'), self.receipt(scrapped=True),
            self.receipt(location_id=NS(usage='internal')),
            self.receipt(location_dest_id=NS(usage='supplier')), self.receipt(quantity=0),
        ]
        for receipt in self.receipts[1:]:
            receipt.supplier_receipt_date_snapshot = self.now + timedelta(days=100)
        self.assertEqual(self.capture()['supplier_otd_completed_at'], self.now)

    def test_empty_receipts_are_unknown(self):
        self.receipts.clear()
        self.assertEqual(self.capture()['supplier_otd_status'], 'unknown')

    def test_ineligible_lines_are_not_captured(self):
        for attribute, value in (
            ('display_type', 'line_note'), ('product_qty', 0), ('qty_received_method', 'manual'),
            ('order_id', NS(state='cancel', partner_id=self.vendor)),
            ('product_id', NS(type='service')),
        ):
            with self.subTest(attribute=attribute):
                old = getattr(self.line, attribute)
                setattr(self.line, attribute, value)
                self.line._supplier_capture_otd({self.line.id: 0})
                self.assertEqual(self.line.writes, [])
                setattr(self.line, attribute, old)

    def test_all_capture_fields_reject_public_write_create_and_context_defaults(self):
        for name in production._OTD_FIELDS:
            with self.subTest(field=name):
                with self.assertRaises(production.AccessError):
                    self.line.write({name: False})
                with self.assertRaises(production.AccessError):
                    self.line.create([{name: False}])
                self.line.env.context = {'default_' + name: False}
                with self.assertRaises(production.AccessError):
                    self.line.create([{}])
                self.line.env.context = {}
        self.line.write({'name': 'Ordinary edit'})
        self.assertEqual(self.line.name, 'Ordinary edit')

    def test_captured_line_cannot_be_deleted(self):
        self.capture()
        with self.assertRaises(production.UserError):
            self.line._unlink_except_supplier_otd()
