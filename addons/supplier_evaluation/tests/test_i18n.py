"""English source and standard Catalan translations, with unchanged OTD data."""
from datetime import timedelta
from lxml import etree
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .test_deadline_confirmation import DeadlineConfirmationCase
from .test_line_otd import OTD_FIELDS


@tagged('post_install', '-at_install')
class TestSupplierI18n(DeadlineConfirmationCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_lang('ca_ES')
        cls.env['ir.module.module']._load_module_terms(['supplier_evaluation'], ['ca_ES'], overwrite=True)

    def test_menu_filters_fields_and_statuses_in_both_languages(self):
        for lang, menu, no_data, below, status, label in (
            ('en_US', 'Supplier evaluation', 'No data', 'OTD below 50%', 'On time', 'Evaluated lines'),
            ('ca_ES', 'Avaluació de proveïdors', 'Sense dades', 'OTD inferior al 50 %', 'Puntual', 'Línies avaluades'),
        ):
            with self.subTest(lang=lang):
                partner = self.vendor.with_user(self.buyer).with_context(lang=lang)
                module = self.env.ref('base.module_supplier_evaluation').with_context(lang=lang)
                self.assertEqual(module.shortdesc, 'Supplier Evaluation' if lang == 'en_US' else 'Avaluació de proveïdors')
                self.assertTrue(module.summary.startswith('Completed-line OTD' if lang == 'en_US' else 'OTD per línia'))
                self.assertEqual(partner.supplier_otd_display, no_data)
                self.assertEqual(self.env.ref('supplier_evaluation.menu_supplier_otd_overview').with_context(lang=lang).name, menu)
                self.assertEqual(self.env.ref('supplier_evaluation.action_supplier_otd_overview').with_context(lang=lang).name, menu)
                search = etree.fromstring(partner.get_view(self.env.ref('supplier_evaluation.view_supplier_otd_search').id, view_type='search')['arch'])
                self.assertEqual(search.xpath(".//filter[@name='otd_below_50']/@string"), [below])
                self.assertEqual(partner.fields_get(['supplier_otd_evaluated_count'])['supplier_otd_evaluated_count']['string'], label)
                selection = self.env['purchase.order.line'].with_context(lang=lang).fields_get(['supplier_otd_status'])['supplier_otd_status']['selection']
                self.assertEqual(dict(selection)['on_time'], status)

    def test_renegotiation_wizard_and_errors_are_translated(self):
        order = self.make_order()
        order.order_line.date_planned = self.now + timedelta(days=3)
        revision = self.revisions(order.order_line)[-1]
        for lang, title, button, warning, error in (
            ('en_US', 'Confirm deadline renegotiation', 'Confirm renegotiation', 'does not remove the original commitment', 'Only Purchase managers'),
            ('ca_ES', 'Confirmar renegociació de termini', 'Confirmar renegociació', 'no elimina el compromís original', 'Només els responsables de compres'),
        ):
            with self.subTest(lang=lang):
                action = revision.with_user(self.manager).with_context(lang=lang).action_open_renegotiation_wizard()
                self.assertEqual(action['name'], title)
                wizard = self.env['supplier.evaluation.deadline.renegotiation.wizard'].with_user(self.manager).with_context(lang=lang)
                arch = etree.fromstring(wizard.get_view(self.env.ref('supplier_evaluation.view_deadline_renegotiation_wizard_form').id, view_type='form')['arch'])
                self.assertEqual(arch.xpath(".//button[@name='action_confirm']/@string"), [button])
                self.assertIn(warning, ' '.join(''.join(arch.itertext()).split()))
                with self.assertRaisesRegex(AccessError, error):
                    revision.with_user(self.buyer).with_context(lang=lang).action_open_renegotiation_wizard()

    def test_language_switch_preserves_percentages_and_frozen_snapshots(self):
        first = self.make_order()
        second = self.make_order()
        self.receive(first.picking_ids, at=self.now)
        self.receive(second.picking_ids, at=self.now + timedelta(days=2))
        lines = first.order_line | second.order_line
        before = lines.read(OTD_FIELDS)
        for lang in ('en_US', 'ca_ES', 'en_US'):
            supplier = self.vendor.with_user(self.buyer).with_context(lang=lang)
            self.assertEqual((supplier.supplier_otd_percentage, supplier.supplier_otd_evaluated_count, supplier.supplier_otd_on_time_count, supplier.supplier_otd_late_count), (50, 2, 1, 1))
            action = supplier.action_open_supplier_otd_lines()
            self.assertEqual(self.env['purchase.order.line'].with_user(self.buyer).search_count(action['domain']), 2)
        self.assertEqual(before, lines.read(OTD_FIELDS))
