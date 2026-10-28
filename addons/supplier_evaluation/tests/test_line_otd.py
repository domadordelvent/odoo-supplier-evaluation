"""Real ORM coverage; requires the updated module in an authorized test database."""
from datetime import timedelta
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_deadline_confirmation import DeadlineConfirmationCase


OTD_FIELDS = [
    'supplier_otd_status', 'supplier_otd_deadline', 'supplier_otd_completed_at',
    'supplier_otd_captured_at', 'supplier_otd_confirmation_id',
    'supplier_otd_ordered_qty', 'supplier_otd_received_qty', 'supplier_otd_uom_id',
    'supplier_otd_supplier_id',
]
MOVE_CAPTURE_FIELDS = [
    'supplier_original_date_snapshot', 'supplier_agreed_date_snapshot',
    'supplier_deadline_revision_id', 'supplier_receipt_date_snapshot',
    'supplier_deadline_captured_at', 'supplier_punctuality',
]
PICKING_CAPTURE_FIELDS = ['supplier_punctuality', 'supplier_evaluation_captured_at']


@tagged('post_install', '-at_install')
class TestLineOTD(DeadlineConfirmationCase):
    def confirm_at(self, line, date, at, attributable=True):
        line.date_planned = date
        with patch('odoo.fields.Datetime.now', return_value=at):
            return self.confirm(self.revisions(line)[-1], attributable=attributable)

    def test_partial_only_captures_when_line_is_complete(self):
        order = self.make_order(qty=3)
        line = order.order_line
        self.receive(order.picking_ids, {line.id: 1})
        first = order.picking_ids.filtered(lambda p: p.state == 'done')
        before_moves = first.move_ids.read(MOVE_CAPTURE_FIELDS)
        before_picking = first.read(PICKING_CAPTURE_FIELDS)
        self.assertFalse(line.supplier_otd_captured_at)
        self.receive(order.picking_ids - first, at=self.now + timedelta(days=2))
        self.assertEqual(line.supplier_otd_status, 'late')
        self.assertEqual(line.supplier_otd_completed_at, self.now + timedelta(days=2))
        self.assertEqual(line.supplier_otd_ordered_qty, 3)
        self.assertEqual(line.supplier_otd_received_qty, 3)
        self.assertEqual(first.move_ids.read(MOVE_CAPTURE_FIELDS), before_moves)
        self.assertEqual(first.read(PICKING_CAPTURE_FIELDS), before_picking)

    def test_unconfirmed_date_changes_do_not_set_otd_deadline(self):
        order = self.make_order([self.now - timedelta(days=3)])
        line = order.order_line
        line.date_planned = self.now + timedelta(days=10)
        self.receive(order.picking_ids)
        self.assertEqual(line.supplier_otd_status, 'late')
        self.assertEqual(line.supplier_otd_deadline, self.now - timedelta(days=3))
        self.assertFalse(line.supplier_otd_confirmation_id)
        # Existing receipt metric is intentionally preserved, even if different.
        self.assertEqual(order.picking_ids.supplier_punctuality, 'on_time')

    def test_latest_prior_confirmation_ignores_attribution_and_technical_edits(self):
        order = self.make_order([self.now - timedelta(days=5)])
        line = order.order_line
        self.confirm_at(line, self.now - timedelta(days=3), self.now - timedelta(hours=3))
        accepted = self.confirm_at(line, self.now, self.now - timedelta(hours=2), attributable=False)
        line.date_planned = self.now - timedelta(days=10)
        self.receive(order.picking_ids)
        self.assertEqual(line.supplier_otd_status, 'on_time')
        self.assertEqual(line.supplier_otd_deadline, self.now)
        self.assertEqual(line.supplier_otd_confirmation_id, accepted)

    def test_agreement_between_partials_is_used_at_completion(self):
        order = self.make_order(qty=2)
        line = order.order_line
        self.receive(order.picking_ids, {line.id: 1})
        agreement = self.confirm_at(line, self.now + timedelta(days=3), self.now + timedelta(days=1))
        self.receive(order.picking_ids.filtered(lambda p: p.state != 'done'), at=self.now + timedelta(days=3))
        self.assertEqual(line.supplier_otd_status, 'on_time')
        self.assertEqual(line.supplier_otd_confirmation_id, agreement)

    def test_late_confirmation_cannot_change_frozen_result_or_existing_captures(self):
        order = self.make_order([self.now - timedelta(days=3)])
        line = order.order_line
        self.receive(order.picking_ids)
        before = line.read(OTD_FIELDS)
        moves = order.picking_ids.move_ids.read(MOVE_CAPTURE_FIELDS)
        pickings = order.picking_ids.read(PICKING_CAPTURE_FIELDS)
        self.confirm_at(line, self.now + timedelta(days=10), self.now + timedelta(hours=1))
        line.date_planned = self.now + timedelta(days=100)
        order.picking_ids._action_done()
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(line.read(OTD_FIELDS), before)
        self.assertEqual(order.picking_ids.move_ids.read(MOVE_CAPTURE_FIELDS), moves)
        self.assertEqual(order.picking_ids.read(PICKING_CAPTURE_FIELDS), pickings)

    def test_confirmation_timestamp_and_prior_presence_are_respected(self):
        for hours in (0, 1):
            with self.subTest(hours=hours):
                order = self.make_order([self.now - timedelta(days=3)])
                line = order.order_line
                self.confirm_at(line, self.now + timedelta(days=2), self.now + timedelta(hours=hours))
                self.receive(order.picking_ids)
                if hours == 0:
                    self.assertTrue(line.supplier_otd_confirmation_id)
                    self.assertEqual(line.supplier_otd_status, 'on_time')
                else:
                    self.assertFalse(line.supplier_otd_confirmation_id)
                    self.assertEqual(line.supplier_otd_status, 'late')

    def test_24_hour_boundary_and_one_second_late(self):
        for seconds, status in ((0, 'on_time'), (1, 'late')):
            with self.subTest(seconds=seconds):
                order = self.make_order()
                self.receive(order.picking_ids, at=self.now + timedelta(hours=24, seconds=seconds))
                self.assertEqual(order.order_line.supplier_otd_status, status)

    def test_multiple_lines_are_separate_observations(self):
        order = self.make_order([self.now, self.now - timedelta(days=3)])
        self.receive(order.picking_ids)
        self.assertEqual(order.order_line.mapped('supplier_otd_status'), ['on_time', 'late'])

    def test_unknown_original_remains_unknown(self):
        order = self.make_order(confirm=False)
        line = order.order_line
        # Simulate a pre-module line; never set a fictitious historical original.
        self.env.cr.execute(
            'UPDATE purchase_order_line SET supplier_original_date_pending = false WHERE id = %s',
            [line.id],
        )
        line.invalidate_recordset(['supplier_original_date_pending'])
        order.button_confirm()
        self.receive(order.picking_ids)
        self.assertEqual(line.supplier_otd_status, 'unknown')
        self.assertFalse(line.supplier_otd_deadline)
        self.assertTrue(line.supplier_otd_completed_at)

    def test_legacy_completed_line_is_not_backfilled_on_revalidation(self):
        from odoo.addons.supplier_evaluation.models.stock_picking import StockPicking
        order = self.make_order()
        picking = order.picking_ids
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        super(StockPicking, picking)._action_done()
        picking._action_done()
        self.assertFalse(order.order_line.supplier_otd_captured_at)

    def test_legacy_partial_missing_capture_is_unknown(self):
        from odoo.addons.supplier_evaluation.models.stock_picking import StockPicking
        order = self.make_order(qty=2)
        picking = order.picking_ids
        picking.move_ids.quantity = 1
        picking.move_ids.picked = True
        super(StockPicking, picking)._action_done()
        before = picking.move_ids.read(MOVE_CAPTURE_FIELDS)
        self.receive(order.picking_ids - picking)
        self.assertEqual(order.order_line.supplier_otd_status, 'unknown')
        self.assertEqual(picking.move_ids.read(MOVE_CAPTURE_FIELDS), before)

    def test_quantity_edits_and_copy_do_not_recalculate_or_copy_otd(self):
        order = self.make_order()
        self.receive(order.picking_ids)
        line = order.order_line
        before = line.read(OTD_FIELDS)
        line.product_qty = 4
        self.assertEqual(line.read(OTD_FIELDS), before)
        duplicate = order.copy()
        self.assertFalse(duplicate.order_line.supplier_otd_captured_at)
        self.assertFalse(duplicate.order_line.supplier_otd_status)

    def test_public_writes_creates_and_context_defaults_are_protected_even_sudo(self):
        order = self.make_order()
        line = order.order_line
        self.receive(order.picking_ids)
        for name in OTD_FIELDS:
            with self.subTest(field=name):
                with self.assertRaises(AccessError):
                    line.sudo().write({name: False})
                with self.assertRaises(AccessError):
                    self.env['purchase.order.line'].sudo().create({'order_id': order.id, name: False})
                with self.assertRaises(AccessError):
                    self.env['purchase.order.line'].with_context(**{'default_' + name: False}).create({})
        with self.assertRaises(UserError):
            line._unlink_except_supplier_otd()

    def test_stock_user_can_capture_without_purchase_write_permission(self):
        order = self.make_order()
        self.receive(order.picking_ids, user=self.warehouse_user)
        self.assertEqual(order.order_line.supplier_otd_status, 'on_time')

    def test_return_after_completion_does_not_replace_otd(self):
        order = self.make_order()
        self.receive(order.picking_ids)
        line = order.order_line
        before = line.read(OTD_FIELDS)
        wizard = self.env['stock.return.picking'].with_context(
            active_model='stock.picking', active_id=order.picking_ids.id,
            active_ids=order.picking_ids.ids,
        ).create({})
        wizard.product_return_moves.quantity = 1
        wizard.product_return_moves.to_refund = True
        returned = self.env['stock.picking'].browse(wizard.action_create_returns()['res_id'])
        self.receive(returned, at=self.now + timedelta(days=2))
        self.assertEqual(line.qty_received, 1)
        self.assertEqual(line.read(OTD_FIELDS), before)

    def test_cancelled_balance_does_not_complete_partial_line(self):
        order = self.make_order(qty=2)
        line = order.order_line
        self.receive(order.picking_ids, {line.id: 1})
        pending = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        pending.action_cancel()
        self.assertFalse(line.supplier_otd_captured_at)

    def test_unit_conversion_and_overreceipt(self):
        order = self.make_order(qty=12)
        line = order.order_line
        move = order.picking_ids.move_ids
        dozen = self.env.ref('uom.product_uom_dozen')
        self.assertEqual(dozen.category_id, line.product_uom.category_id)
        move.write({'product_uom': dozen.id, 'product_uom_qty': 1})
        self.receive(order.picking_ids, {line.id: 2})
        self.assertEqual(line.supplier_otd_status, 'on_time')
        self.assertEqual(line.supplier_otd_received_qty, 24)
        self.assertEqual(line.supplier_otd_ordered_qty, 12)
        self.assertEqual(line.supplier_otd_uom_id, line.product_uom)

    def test_refund_return_before_completion_requires_replacement(self):
        order = self.make_order(qty=3)
        line = order.order_line
        first = order.picking_ids
        self.receive(first, {line.id: 2})
        wizard = self.env['stock.return.picking'].with_context(
            active_model='stock.picking', active_id=first.id, active_ids=first.ids,
        ).create({})
        wizard.product_return_moves.quantity = 1
        wizard.product_return_moves.to_refund = True
        action = wizard.action_create_returns()
        returned = self.env['stock.picking'].browse(action['res_id'])
        self.receive(returned)
        self.assertEqual(line.qty_received, 1)
        self.assertFalse(line.supplier_otd_captured_at)
        backorder = order.picking_ids.filtered(lambda p: p.backorder_id == first and p.state != 'done')
        self.receive(backorder)
        self.assertEqual(line.qty_received, 2)
        self.assertFalse(line.supplier_otd_captured_at)
        replacement = self.env['stock.picking'].create({
            'partner_id': self.vendor.id, 'picking_type_id': self.receipt_type.id,
            'location_id': first.location_id.id, 'location_dest_id': first.location_dest_id.id,
            'move_ids': [Command.create({
                'name': self.product.name, 'product_id': self.product.id,
                'product_uom_qty': 1, 'product_uom': self.product.uom_id.id,
                'location_id': first.location_id.id, 'location_dest_id': first.location_dest_id.id,
                'purchase_line_id': line.id,
            })],
        })
        replacement.action_confirm()
        self.receive(replacement, at=self.now + timedelta(days=2))
        self.assertEqual(line.qty_received, 3)
        self.assertEqual(line.supplier_otd_status, 'late')

    def test_service_and_zero_quantity_lines_have_no_observation(self):
        order = self.make_order(confirm=False)
        service = self.env['product.product'].create({'name': 'OTD service', 'type': 'service'})
        order.order_line = [Command.create({
            'product_id': service.id, 'name': service.name, 'product_qty': 1,
            'product_uom': service.uom_id.id, 'price_unit': 1, 'date_planned': self.now,
        })]
        order.button_confirm()
        lines = order.order_line
        self.assertFalse(lines.filtered(lambda l: l.product_id == service)._supplier_otd_is_eligible())
        zero = self.make_order(qty=0).order_line
        self.assertFalse(zero._supplier_otd_is_eligible())
