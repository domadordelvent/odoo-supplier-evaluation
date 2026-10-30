"""Aggregate only production OTD snapshots; fixtures live in a test transaction."""
from datetime import timedelta
from unittest.mock import patch

from lxml import etree
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .test_deadline_confirmation import DeadlineConfirmationCase
from .test_line_otd import OTD_FIELDS, MOVE_CAPTURE_FIELDS, PICKING_CAPTURE_FIELDS


SUMMARY = [
    'supplier_otd_has_data', 'supplier_otd_percentage', 'supplier_otd_evaluated_count',
    'supplier_otd_on_time_count', 'supplier_otd_late_count',
]


@tagged('post_install', '-at_install')
class TestSupplierOTD(DeadlineConfirmationCase):
    def summary(self, partner=None, user=None, companies=None):
        partner = (partner if partner is not None else self.vendor).with_user(user or self.buyer)
        if companies is not None:
            partner = partner.with_context(allowed_company_ids=companies.ids)
        return partner.read(SUMMARY)[0]

    def evaluated(self, late=False, qty=2, price=1):
        order = self.make_order(qty=qty)
        order.order_line.price_unit = price
        self.receive(order.picking_ids, at=self.now + timedelta(days=2) if late else self.now)
        return order

    def assert_summary(self, on_time, late, partner=None, user=None, companies=None):
        result = self.summary(partner, user, companies)
        total = on_time + late
        self.assertEqual(result['supplier_otd_has_data'], bool(total))
        self.assertEqual(result['supplier_otd_evaluated_count'], total)
        self.assertEqual(result['supplier_otd_on_time_count'], on_time)
        self.assertEqual(result['supplier_otd_late_count'], late)
        if total:
            self.assertAlmostEqual(result['supplier_otd_percentage'], 100 * on_time / total, places=2)
        return result

    def other_company_order(self, late=True):
        company = self.env['res.company'].create({'name': 'OTD Aggregate Other Company'})
        env = self.env['purchase.order'].sudo().with_company(company).env
        warehouse = env['stock.warehouse'].create({
            'name': 'OTD Aggregate Warehouse', 'code': 'OTDA', 'company_id': company.id,
        })
        order = env['purchase.order'].create({
            'partner_id': self.vendor.id, 'picking_type_id': warehouse.in_type_id.id,
            'order_line': [Command.create({
                'product_id': self.product.id, 'name': self.product.name, 'product_qty': 1,
                'product_uom': self.product.uom_id.id, 'price_unit': 1, 'date_planned': self.now,
            })],
        })
        order.button_confirm()
        self.receive(order.picking_ids, at=self.now + timedelta(days=2) if late else self.now)
        return company, order

    def test_empty_supplier_has_no_data(self):
        self.assert_summary(0, 0)

    def test_all_on_time_is_100_percent(self):
        self.evaluated()
        self.evaluated()
        self.assert_summary(2, 0)

    def test_all_late_is_real_zero_percent_with_data(self):
        self.evaluated(late=True)
        self.assertEqual(self.assert_summary(0, 1)['supplier_otd_percentage'], 0)

    def test_mixed_results_count_lines_not_quantities_or_prices(self):
        self.evaluated(qty=1, price=1)
        self.evaluated(qty=1000, price=50000, late=True)
        self.assertEqual(self.assert_summary(1, 1)['supplier_otd_percentage'], 50)

    def test_non_integer_percentage_keeps_precision(self):
        self.evaluated()
        self.evaluated(late=True)
        self.evaluated(late=True)
        self.assertEqual(self.assert_summary(1, 2)['supplier_otd_percentage'], 33.33)

    def test_partial_is_excluded_until_completed_and_counted_once(self):
        order = self.make_order(qty=3)
        line = order.order_line
        self.assert_summary(0, 0)  # Cache the pre-receipt summary.
        self.receive(order.picking_ids, {line.id: 1})
        self.assert_summary(0, 0)
        pending = order.picking_ids.filtered(lambda p: p.state != 'done')
        self.receive(pending, at=self.now + timedelta(days=2))
        self.assert_summary(0, 1)
        order.picking_ids._action_done()
        self.assert_summary(0, 1)

    def test_unknown_and_legacy_missing_capture_are_excluded(self):
        order = self.make_order(confirm=False)
        line = order.order_line
        self.env.cr.execute('UPDATE purchase_order_line SET supplier_original_date_pending=false WHERE id=%s', [line.id])
        line.invalidate_recordset(['supplier_original_date_pending'])
        order.button_confirm()
        self.receive(order.picking_ids)
        self.assertEqual(line.supplier_otd_status, 'unknown')
        from odoo.addons.supplier_evaluation.models.stock_picking import StockPicking
        legacy = self.make_order()
        for move in legacy.picking_ids.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        super(StockPicking, legacy.picking_ids)._action_done()
        self.assertFalse(legacy.order_line.supplier_otd_captured_at)
        self.assert_summary(0, 0)

    def test_cancelled_pending_order_is_excluded(self):
        order = self.make_order()
        order.button_cancel()
        self.assert_summary(0, 0)

    def test_cancelled_historical_order_is_excluded_without_changing_snapshot(self):
        order = self.evaluated()
        before = order.order_line.read(OTD_FIELDS)
        self.assert_summary(1, 0)
        # Odoo's button disallows cancellation after receipt. Simulate a legacy
        # cancelled order in the temporary test DB to exercise the domain.
        order.write({'state': 'cancel'})
        self.assert_summary(0, 0)
        self.assertEqual(order.order_line.read(OTD_FIELDS), before)

    def test_technical_dates_prices_quantities_and_later_agreements_do_not_recompute(self):
        order = self.evaluated()
        line = order.order_line
        before = line.read(OTD_FIELDS)
        line.write({'date_planned': self.now + timedelta(days=10), 'price_unit': 9999, 'product_qty': 50})
        with patch('odoo.fields.Datetime.now', return_value=self.now + timedelta(days=1)):
            self.confirm(self.revisions(line)[-1])
        self.assert_summary(1, 0)
        self.assertEqual(line.read(OTD_FIELDS), before)

    def test_attribution_uses_captured_supplier_even_if_order_partner_changes(self):
        order = self.evaluated()
        other = self.env['res.partner'].create({'name': 'OTD New Order Vendor'})
        order.partner_id = other
        self.assert_summary(1, 0)
        self.assert_summary(0, 0, partner=other)

    def test_supplier_contacts_are_not_silently_rolled_up(self):
        parent = self.env['res.partner'].create({'name': 'OTD Vendor Parent', 'is_company': True})
        self.vendor.parent_id = parent
        self.evaluated()
        self.assert_summary(1, 0)
        self.assert_summary(0, 0, partner=parent)

    def test_batch_computation_keeps_suppliers_separate(self):
        self.evaluated()
        other = self.env['res.partner'].create({'name': 'OTD Empty Supplier'})
        rows = (self.vendor | other).with_user(self.buyer).read(SUMMARY)
        counts = {row['id']:row['supplier_otd_evaluated_count'] for row in rows}
        self.assertEqual(counts, {self.vendor.id:1, other.id:0})

    def test_summary_never_writes_capture_fields(self):
        order = self.evaluated()
        before = (order.order_line.read(OTD_FIELDS), order.picking_ids.read(PICKING_CAPTURE_FIELDS),
                  order.picking_ids.move_ids.read(MOVE_CAPTURE_FIELDS))
        self.assert_summary(1, 0)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assert_summary(1, 0)
        after = (order.order_line.read(OTD_FIELDS), order.picking_ids.read(PICKING_CAPTURE_FIELDS),
                 order.picking_ids.move_ids.read(MOVE_CAPTURE_FIELDS))
        self.assertEqual(before, after)

    def test_buyer_and_manager_can_read(self):
        self.evaluated()
        self.assert_summary(1, 0, user=self.buyer)
        self.assert_summary(1, 0, user=self.manager)

    def test_warehouse_user_and_portal_cannot_read_even_with_sudo(self):
        self.evaluated()
        portal = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'OTD Portal', 'login': 'otd_summary_portal',
            'groups_id': [Command.set([self.env.ref('base.group_portal').id])],
        })
        for user in (self.warehouse_user, portal):
            for sudo in (False, True):
                with self.subTest(user=user.login, sudo=sudo):
                    record = self.vendor.with_user(user)
                    if sudo:
                        record = record.sudo()
                    with self.assertRaises(AccessError):
                        record.read(SUMMARY)

    def test_purchase_line_record_rules_are_respected(self):
        visible = self.evaluated()
        hidden = self.evaluated(late=True)
        self.env['ir.rule'].create({
            'name': 'OTD Aggregate Hide One Line',
            'model_id': self.env['ir.model']._get_id('purchase.order.line'),
            'domain_force': repr([('id','!=',hidden.order_line.id)]),
        })
        self.assert_summary(1, 0)
        self.assertEqual(self.vendor.with_user(self.buyer).sudo().read(SUMMARY)[0]['supplier_otd_evaluated_count'], 1)
        self.assertTrue(visible.order_line)

    def test_return_after_completion_keeps_one_historical_observation(self):
        order = self.evaluated()
        before = order.order_line.read(OTD_FIELDS)
        self.assert_summary(1, 0)
        wizard = self.env['stock.return.picking'].with_context(
            active_model='stock.picking', active_id=order.picking_ids.id, active_ids=order.picking_ids.ids,
        ).create({})
        wizard.product_return_moves.quantity = 1
        wizard.product_return_moves.to_refund = True
        returned = self.env['stock.picking'].browse(wizard.action_create_returns()['res_id'])
        self.receive(returned, at=self.now + timedelta(days=3))
        self.assertEqual(order.order_line.qty_received, 1)
        self.assert_summary(1, 0)
        self.assertEqual(order.order_line.read(OTD_FIELDS), before)

    def test_companies_selected_separately_and_together_do_not_share_cache(self):
        self.evaluated()
        other, _order = self.other_company_order()
        self.buyer.company_ids |= other
        main = self.env.company
        self.assert_summary(1, 0, companies=main)
        self.assert_summary(0, 1, companies=other)
        self.assert_summary(1, 1, companies=main | other)
        self.assert_summary(1, 0, companies=main)

    def test_unauthorized_company_context_is_rejected_and_sudo_still_limits_companies(self):
        self.evaluated()
        other, _order = self.other_company_order()
        record = self.vendor.with_user(self.buyer).with_context(allowed_company_ids=(self.env.company | other).ids)
        with self.assertRaises(AccessError):
            record.read(SUMMARY)
        values = record.sudo().read(SUMMARY)[0]
        self.assertEqual(values['supplier_otd_evaluated_count'], 1)
        self.assertEqual(values['supplier_otd_on_time_count'], 1)

    def test_partner_form_has_counts_and_no_data_visibility_for_purchase_users(self):
        view_id = self.env.ref('base.view_partner_form').id
        arch = etree.fromstring(self.env['res.partner'].with_user(self.buyer).get_view(view_id, view_type='form')['arch'])
        page = arch.xpath(".//page[@name='supplier_otd']")[0]
        for name in SUMMARY:
            self.assertTrue(page.xpath(".//field[@name='%s']" % name))
        self.assertTrue(page.xpath(".//span[@invisible='supplier_otd_has_data' and text()='No data']"))
        self.assertTrue(page.xpath(".//span[@invisible='not supplier_otd_has_data']/field[@name='supplier_otd_percentage']"))
        stock_arch = etree.fromstring(self.env['res.partner'].with_user(self.warehouse_user).get_view(view_id, view_type='form')['arch'])
        self.assertFalse(stock_arch.xpath(".//page[@name='supplier_otd']"))
