from datetime import timedelta
from lxml import etree
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .test_deadline_confirmation import DeadlineConfirmationCase
from .test_line_otd import OTD_FIELDS, MOVE_CAPTURE_FIELDS, PICKING_CAPTURE_FIELDS


CTX = {'supplier_otd_overview': True}


@tagged('post_install', '-at_install')
class TestSupplierOTDUI(DeadlineConfirmationCase):
    def provider(self, name, outcomes):
        vendor = self.env['res.partner'].create({'name': name, 'supplier_rank': 1})
        for late in outcomes:
            order = self.make_order(confirm=False)
            order.partner_id = vendor
            # Partner changes trigger Odoo's date_planned recomputation.
            # Establish the intended draft promise after that real onchange.
            order.order_line.date_planned = self.now
            order.button_confirm()
            self.receive(order.picking_ids, at=self.now + timedelta(days=2) if late else self.now)
        return vendor

    def model(self, user=None):
        return self.env['res.partner'].with_user(user or self.buyer).with_context(**CTX)

    def test_sort_descending_and_native_heading_ascending_with_pagination(self):
        low = self.provider('OTD UI Low', [False, True, True])
        high = self.provider('OTD UI High', [False])
        empty = self.provider('OTD UI Empty', [])
        domain = [('id', 'in', (low | high | empty).ids)]
        self.assertEqual(self.model().search(domain, order='supplier_otd_percentage desc,name,id').ids, (high | low | empty).ids)
        self.assertEqual(self.model().search(domain, order='supplier_otd_display asc,name,id').ids, (low | high | empty).ids)
        self.assertEqual(self.model().search(domain, order='supplier_otd_percentage desc,name,id', offset=1, limit=1), low)

    def test_equal_percentages_have_stable_name_and_id_order(self):
        second = self.provider('UI B', [False])
        first = self.provider('UI A', [False])
        domain = [('id', 'in', (first | second).ids)]
        self.assertEqual(self.model().search(domain, order='supplier_otd_percentage desc,name,id').ids, (first | second).ids)

    def test_under_50_excludes_no_data_and_exactly_50_but_includes_real_zero(self):
        zero = self.provider('UI Zero', [True])
        fifty = self.provider('UI Fifty', [False, True])
        empty = self.provider('UI Empty', [])
        scope = [('id', 'in', (zero | fifty | empty).ids)]
        self.assertEqual(self.model().search(scope + [('supplier_otd_percentage', '<', 50)]), zero)
        self.assertEqual(self.model().search_count(scope + [('supplier_otd_percentage', '<', 50)]), 1)
        self.assertEqual(self.model().search(scope + [('supplier_otd_has_data', '=', False)]), empty)
        self.assertEqual(self.model().search(scope + [('supplier_otd_has_data', '!=', False)]).ids, self.model().search(scope + [('supplier_otd_has_data', '=', True)]).ids)

    def test_display_differentiates_zero_and_no_data(self):
        zero = self.provider('UI Zero', [True]).with_user(self.buyer)
        empty = self.provider('UI Empty', []).with_user(self.buyer)
        self.assertEqual(zero.supplier_otd_display, '0.00 %')
        self.assertEqual(empty.supplier_otd_display, 'No data')

    def test_field_sortability_available_to_native_view_metadata(self):
        for field in ('supplier_otd_percentage', 'supplier_otd_display'):
            self.assertTrue(self.model().fields_get([field], ['sortable'])[field]['sortable'])
            self.assertTrue(self.env['res.partner'].with_user(self.buyer).fields_get([field], ['sortable'])[field]['sortable'])

    def test_web_search_read_orders_before_pagination_and_counts_filter(self):
        first = self.provider('UI High', [False])
        second = self.provider('UI Mid', [False, True])
        third = self.provider('UI Low', [True])
        domain = [('id', 'in', (first | second | third).ids)]
        result = self.model().web_search_read(domain, {'name': {}, 'supplier_otd_display': {}, 'supplier_otd_evaluated_count': {}}, offset=1, limit=1, order='supplier_otd_display desc,name,id')
        self.assertEqual(result['length'], 3)
        self.assertEqual([row['id'] for row in result['records']], second.ids)

    def test_drilldown_contains_exactly_contributing_lines_and_is_readonly(self):
        vendor = self.provider('UI Audit', [False, True])
        pending = self.make_order(confirm=False)
        pending.partner_id = vendor
        pending.button_confirm()
        action = vendor.with_user(self.buyer).action_open_supplier_otd_lines()
        lines = self.env['purchase.order.line'].with_user(self.buyer).search(action['domain'])
        self.assertEqual(len(lines), vendor.with_user(self.buyer).supplier_otd_evaluated_count)
        self.assertNotIn(pending.order_line, lines)
        self.assertEqual(set(lines.mapped('supplier_otd_status')), {'on_time', 'late'})
        for xmlid, kind in (('view_supplier_otd_line_list', 'list'), ('view_supplier_otd_line_form', 'form')):
            view = self.env['ir.ui.view'].browse(self.env.ref('supplier_evaluation.' + xmlid).id)
            arch = etree.fromstring(self.env['purchase.order.line'].with_user(self.buyer).get_view(view.id, view_type=kind)['arch'])
            for operation in ('create', 'edit', 'delete'):
                self.assertEqual(arch.get(operation), 'false')

    def test_drilldown_empty_for_no_data_and_clears_inherited_search_defaults(self):
        vendor = self.provider('UI Empty', [])
        action = vendor.with_user(self.buyer).with_context(search_default_otd_below_50=1, default_partner_id=self.vendor.id, **CTX).action_open_supplier_otd_lines()
        self.assertFalse(self.env['purchase.order.line'].with_user(self.buyer).search(action['domain']))
        self.assertNotIn('search_default_otd_below_50', action['context'])
        self.assertNotIn('supplier_otd_overview', action['context'])
        self.assertNotIn('default_partner_id', action['context'])

    def test_non_purchase_users_cannot_sort_filter_or_open_lines_even_sudo(self):
        vendor = self.provider('UI Security', [False])
        for sudo in (False, True):
            model = self.model(self.warehouse_user)
            record = vendor.with_user(self.warehouse_user)
            if sudo:
                model, record = model.sudo(), record.sudo()
            with self.assertRaises(AccessError):
                model.search([('id', '=', vendor.id)], order='supplier_otd_percentage desc')
            with self.assertRaises(AccessError):
                model.search([('supplier_otd_percentage', '<', 50)])
            with self.assertRaises(AccessError):
                record.action_open_supplier_otd_lines()

    def test_record_rules_match_counters_filter_order_and_drilldown(self):
        vendor = self.provider('UI Rules', [False, True])
        hidden = self.env['purchase.order.line'].search([('supplier_otd_supplier_id', '=', vendor.id), ('supplier_otd_status', '=', 'late')])
        self.env['ir.rule'].create({'name': 'UI Hide Late Line', 'model_id': self.env['ir.model']._get_id('purchase.order.line'), 'domain_force': repr([('id', 'not in', hidden.ids)])})
        scoped = vendor.with_user(self.buyer)
        self.assertEqual(scoped.supplier_otd_percentage, 100)
        self.assertFalse(self.model().search([('id', '=', vendor.id), ('supplier_otd_percentage', '<', 50)]))
        self.assertEqual(self.model().search([('id', '=', vendor.id)], order='supplier_otd_percentage desc'), vendor)
        action = scoped.action_open_supplier_otd_lines()
        self.assertEqual(len(self.env['purchase.order.line'].with_user(self.buyer).search(action['domain'])), 1)

    def test_partner_record_rules_prevent_drilldown_even_with_sudo(self):
        vendor = self.provider('UI Hidden Vendor', [False])
        self.env['ir.rule'].create({'name': 'UI Hide Partner', 'model_id': self.env['ir.model']._get_id('res.partner'), 'domain_force': repr([('id', '!=', vendor.id)])})
        with self.assertRaises(AccessError):
            vendor.with_user(self.buyer).sudo().action_open_supplier_otd_lines()

    def test_companies_separated_for_sort_filter_and_drilldown(self):
        vendor = self.provider('UI Companies', [False])
        other = self.env['res.company'].create({'name': 'UI Other Company'})
        env = self.env['purchase.order'].sudo().with_company(other).env
        wh = env['stock.warehouse'].create({'name': 'UI Warehouse', 'code': 'UIOTD', 'company_id': other.id})
        order = env['purchase.order'].create({
            'partner_id': vendor.id, 'picking_type_id': wh.in_type_id.id,
            'order_line': [Command.create({'product_id': self.product.id, 'name': self.product.name,
                'product_qty': 1, 'product_uom': self.product.uom_id.id, 'price_unit': 1, 'date_planned': self.now})],
        })
        order.button_confirm()
        self.receive(order.picking_ids, at=self.now + timedelta(days=2))
        self.buyer.company_ids |= other
        main = self.env.company
        for companies, percentage, count in ((main, 100, 1), (other, 0, 1), (main | other, 50, 2)):
            model = self.model().with_context(allowed_company_ids=companies.ids)
            result = model.search([('id', '=', vendor.id)], order='supplier_otd_percentage desc')
            self.assertEqual(result.supplier_otd_percentage, percentage)
            filtered = model.search([('id', '=', vendor.id), ('supplier_otd_percentage', '<', 50)])
            self.assertEqual(bool(filtered), percentage < 50)
            action = result.action_open_supplier_otd_lines()
            lines = self.env['purchase.order.line'].with_user(self.buyer).with_context(allowed_company_ids=companies.ids).search(action['domain'])
            self.assertEqual(len(lines), count)
            self.assertTrue(set(lines.company_id.ids) <= set(companies.ids))

    def test_ui_queries_preserve_all_historical_snapshots(self):
        vendor = self.provider('UI Frozen', [False, True])
        lines = self.env['purchase.order.line'].search([('supplier_otd_supplier_id', '=', vendor.id)])
        pickings = lines.move_ids.picking_id
        before = (lines.read(OTD_FIELDS), pickings.read(PICKING_CAPTURE_FIELDS), lines.move_ids.read(MOVE_CAPTURE_FIELDS))
        self.model().search([('id', '=', vendor.id)], order='supplier_otd_percentage desc').read(['supplier_otd_display'])
        self.model().search([('supplier_otd_percentage', '<', 50)])
        vendor.with_user(self.buyer).action_open_supplier_otd_lines()
        self.env.flush_all()
        self.assertEqual(before, (lines.read(OTD_FIELDS), pickings.read(PICKING_CAPTURE_FIELDS), lines.move_ids.read(MOVE_CAPTURE_FIELDS)))

    def test_native_views_and_dedicated_action_leave_contacts_unchanged(self):
        action = self.env.ref('supplier_evaluation.action_supplier_otd_overview')
        self.assertEqual(action.view_mode, 'list,form')
        self.assertEqual(action.view_ids.filtered(lambda v: v.view_mode == 'list').view_id, self.env.ref('supplier_evaluation.view_supplier_otd_list'))
        standard = self.env.ref('account.res_partner_action_supplier')
        self.assertNotEqual(standard, action)
        self.assertNotEqual(standard.search_view_id, action.search_view_id)
        self.assertTrue(self.env.ref('supplier_evaluation.menu_supplier_otd_overview').groups_id)
        context_model = self.model()
        arch = etree.fromstring(context_model.get_view(self.env.ref('supplier_evaluation.view_supplier_otd_list').id, view_type='list')['arch'])
        self.assertEqual(arch.get('default_order'), 'supplier_otd_display desc,name,id')
        form = etree.fromstring(context_model.get_view(self.env.ref('base.view_partner_form').id, view_type='form')['arch'])
        self.assertTrue(form.xpath(".//page[@name='supplier_otd']//field[@widget='progressbar']"))
        self.assertTrue(form.xpath(".//page[@name='supplier_otd']//button[@name='action_open_supplier_otd_lines']"))

    def test_unsafe_percentage_search_values_are_rejected(self):
        for operator, value in (('like', 'x'), ('<', float('nan')), ('<', float('inf')), ('<', '50; DROP TABLE x')):
            with self.assertRaises(ValueError):
                self.model()._search_supplier_otd_percentage(operator, value)

    def test_standard_punctuality_hidden_only_in_evaluation_form(self):
        action = self.env.ref('supplier_evaluation.action_supplier_otd_overview')
        dedicated = self.env.ref('supplier_evaluation.view_supplier_otd_form')
        self.assertEqual(dedicated.mode, 'primary')
        self.assertEqual(action.view_ids.filtered(lambda v: v.view_mode == 'form').view_id, dedicated)
        for view, hidden in ((dedicated, True), (self.env.ref('base.view_partner_form'), False)):
            arch = etree.fromstring(self.model().get_view(view.id, view_type='form')['arch'])
            buttons = arch.xpath(".//button[.//field[@name='on_time_rate']]")
            self.assertEqual(len(buttons), 1)
            self.assertEqual(buttons[0].get('invisible') in ('1', 'True'), hidden)
            self.assertTrue(arch.xpath(".//page[@name='supplier_otd']//div[contains(@class, 'o_supplier_otd_progress')]//field[@widget='progressbar']"))

    def test_drilldown_contains_frozen_delivery_details(self):
        arch = etree.fromstring(self.env['purchase.order.line'].with_user(self.buyer).get_view(
            self.env.ref('supplier_evaluation.view_supplier_otd_line_list').id, view_type='list')['arch'])
        for name in ('order_id', 'product_id', 'supplier_otd_deadline', 'supplier_otd_completed_at', 'supplier_otd_status'):
            self.assertTrue(arch.xpath("./field[@name='%s']" % name))
