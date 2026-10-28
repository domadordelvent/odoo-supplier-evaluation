from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged

from .test_deadline_confirmation import DeadlineConfirmationCase


@tagged("post_install", "-at_install")
class TestDeadlineWizard(DeadlineConfirmationCase):
    def open_wizard(self, revision):
        action = revision.with_user(self.manager).action_open_renegotiation_wizard()
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["res_model"], "supplier.evaluation.deadline.renegotiation.wizard")
        wizard = self.env[action["res_model"]].with_user(self.manager).browse(action["res_id"])
        return wizard, action

    def fill_wizard(self, wizard, attributable="yes"):
        wizard.write({"justification": "Acord explícit de renegociació per correu", "supplier_attributable": attributable})

    def view_arch(self, model, xmlid, user, kind="form"):
        view = self.env.ref(xmlid)
        return etree.fromstring(self.env[model].with_user(user).get_view(view.id, view_type=kind)["arch"])

    def test_modal_shows_original_and_last_accepted_dates_without_confirming(self):
        _, line, revision = self.prepare_revision()
        history = self.revisions(line)
        before = history.read(["previous_date", "new_date", "revision_type", "change_source", "write_date"])
        wizard, action = self.open_wizard(revision)
        self.assertEqual(action["views"][0][0], self.env.ref("supplier_evaluation.view_deadline_renegotiation_wizard_form").id)
        self.assertEqual(wizard.previous_agreed_date, line.supplier_original_date)
        self.assertEqual(wizard.new_agreed_date, revision.new_date)
        self.assertEqual(wizard.original_date, line.supplier_original_date)
        self.assertTrue(wizard.original_date_known)
        self.assertFalse(wizard.supplier_attributable)
        self.assertFalse(revision.confirmation_ids)
        self.assertEqual(history.read(["previous_date", "new_date", "revision_type", "change_source", "write_date"]), before)

    def test_form_creates_confirmation_through_existing_server_action(self):
        _, line, revision = self.prepare_revision()
        wizard, _ = self.open_wizard(revision)
        form = Form(wizard, view=self.env.ref("supplier_evaluation.view_deadline_renegotiation_wizard_form"))
        self.assertEqual(fields.Datetime.to_datetime(form.previous_agreed_date), line.supplier_original_date)
        self.assertEqual(fields.Datetime.to_datetime(form.new_agreed_date), revision.new_date)
        form.justification = "Nou termini acordat amb el proveïdor"
        form.supplier_attributable = "yes"
        saved = form.save()
        action = saved.action_confirm()
        confirmation = self.env[action["res_model"]].browse(action["res_id"])
        self.assertEqual(confirmation.revision_id, revision)
        self.assertEqual(confirmation.justification, "Nou termini acordat amb el proveïdor")
        self.assertEqual(confirmation.confirmed_by_id, self.manager)
        self.assertTrue(confirmation.supplier_attributable)
        self.assertEqual(confirmation.previous_agreed_date, fields.Datetime.to_datetime(form.previous_agreed_date))
        self.assertEqual(confirmation.new_agreed_date, revision.new_date)
        self.assertEqual(line.supplier_original_date, self.now)
        self.assertEqual(revision.revision_type, "technical")

    def test_non_supplier_attribution_is_explicitly_supported(self):
        _, _, revision = self.prepare_revision()
        wizard, _ = self.open_wizard(revision)
        self.fill_wizard(wizard, attributable="no")
        action = wizard.action_confirm()
        confirmation = self.env[action["res_model"]].browse(action["res_id"])
        self.assertFalse(confirmation.supplier_attributable)

    def test_preview_uses_accepted_date_instead_of_intermediate_technical_date(self):
        _, line, revision = self.prepare_revision()
        first = self.confirm(revision)
        line.date_planned = self.now + timedelta(days=3)
        line.date_planned = self.now + timedelta(days=5)
        new_revision = self.revisions(line)[-1]
        wizard, _ = self.open_wizard(new_revision)
        self.assertEqual(wizard.previous_agreed_date, first.new_agreed_date)
        self.assertNotEqual(wizard.previous_agreed_date, new_revision.previous_date)
        self.assertEqual(wizard.original_date, self.now)

    def test_only_managers_can_open_create_or_submit_wizard_even_with_sudo(self):
        _, _, revision = self.prepare_revision()
        wizard, _ = self.open_wizard(revision)
        self.fill_wizard(wizard)
        for user in (self.buyer, self.warehouse_user):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    revision.with_user(user).action_open_renegotiation_wizard()
                with self.assertRaises(AccessError):
                    self.env[wizard._name].with_user(user).create({"revision_id": revision.id})
                with self.assertRaises(AccessError):
                    self.env[wizard._name].with_user(user).sudo().create({"revision_id": revision.id})
                with self.assertRaises(AccessError):
                    wizard.with_user(user).sudo().action_confirm()
        self.assertFalse(revision.confirmation_ids)

    def test_missing_attribution_is_rejected_on_server(self):
        _, _, revision = self.prepare_revision()
        wizard, _ = self.open_wizard(revision)
        wizard.justification = "Acord documentat"
        with self.assertRaises(ValidationError):
            wizard.action_confirm()
        self.assertFalse(revision.confirmation_ids)

    def test_missing_justification_is_rejected_on_server(self):
        _, _, revision = self.prepare_revision()
        wizard, _ = self.open_wizard(revision)
        wizard.supplier_attributable = "yes"
        with self.assertRaises(ValidationError):
            wizard.action_confirm()
        self.assertFalse(revision.confirmation_ids)

    def test_wizard_cannot_override_preview_dates_or_selected_revision(self):
        _, line, revision = self.prepare_revision()
        wizard, _ = self.open_wizard(revision)
        with self.assertRaises(AccessError):
            wizard.write({"previous_agreed_date": self.now + timedelta(days=50)})
        with self.assertRaises(AccessError):
            wizard.write({"company_id": line.company_id.id})
        with self.assertRaises(UserError):
            wizard.write({"revision_id": self.revisions(line)[0].id})
        self.assertFalse(revision.confirmation_ids)

    def test_stale_open_wizard_rechecks_revision_at_submission(self):
        _, line, revision = self.prepare_revision()
        wizard, _ = self.open_wizard(revision)
        self.fill_wizard(wizard)
        line.date_planned += timedelta(days=1)
        with self.assertRaises(ValidationError):
            wizard.action_confirm()
        self.assertFalse(revision.confirmation_ids)

    def test_two_open_wizards_cannot_confirm_twice(self):
        _, _, revision = self.prepare_revision()
        first, _ = self.open_wizard(revision)
        second, _ = self.open_wizard(revision)
        self.fill_wizard(first)
        self.fill_wizard(second)
        first.action_confirm()
        with self.assertRaises(ValidationError):
            second.action_confirm()
        self.assertEqual(len(revision.confirmation_ids), 1)

    def test_cancel_does_not_create_confirmation_or_modify_history(self):
        _, line, revision = self.prepare_revision()
        original = line.supplier_original_date
        history = self.revisions(line)
        wizard, _ = self.open_wizard(revision)
        self.fill_wizard(wizard)
        wizard.unlink()
        self.assertFalse(revision.confirmation_ids)
        self.assertEqual(line.supplier_original_date, original)
        self.assertEqual(self.revisions(line), history)

    def test_ineligible_revision_is_rejected_before_opening_modal(self):
        order = self.make_order()
        with self.assertRaises(ValidationError):
            self.open_wizard(self.revisions(order.order_line)[0])

    def test_context_defaults_from_purchase_do_not_pollute_wizard_or_audit(self):
        _, line, revision = self.prepare_revision()
        action = revision.with_user(self.manager).with_context(
            default_company_id=line.company_id.id,
            default_previous_agreed_date=self.now + timedelta(days=50),
            default_confirmed_by_id=self.buyer.id,
        ).action_open_renegotiation_wizard()
        self.assertFalse(any(key.startswith("default_") for key in action["context"]))
        wizard = self.env[action["res_model"]].with_user(self.manager).browse(action["res_id"])
        self.assertEqual(wizard.previous_agreed_date, line.supplier_original_date)
        self.fill_wizard(wizard)
        result = wizard.action_confirm()
        confirmation = self.env[result["res_model"]].browse(result["res_id"])
        self.assertEqual(confirmation.confirmed_by_id, self.manager)

    def test_manager_confirmation_button_is_absent_for_ordinary_buyers(self):
        for kind, xmlid in (
            ("form", "supplier_evaluation.view_deadline_revision_form"),
            ("list", "supplier_evaluation.view_deadline_revision_list"),
        ):
            with self.subTest(kind=kind):
                manager = self.view_arch("supplier.evaluation.deadline.revision", xmlid, self.manager, kind)
                buyer = self.view_arch("supplier.evaluation.deadline.revision", xmlid, self.buyer, kind)
                self.assertTrue(manager.xpath(".//button[@name='action_open_renegotiation_wizard']"))
                self.assertFalse(buyer.xpath(".//button[@name='action_open_renegotiation_wizard']"))

    def test_wizard_view_warns_about_original_and_requires_explicit_inputs(self):
        arch = self.view_arch(
            "supplier.evaluation.deadline.renegotiation.wizard",
            "supplier_evaluation.view_deadline_renegotiation_wizard_form", self.manager,
        )
        text = " ".join("".join(arch.itertext()).split())
        self.assertIn("no elimina el compromís original", text)
        self.assertIn("recepcions completades es conserven", text)
        self.assertTrue(arch.xpath(".//field[@name='justification'][@required='1']"))
        self.assertTrue(arch.xpath(".//field[@name='supplier_attributable'][@required='1']"))
        self.assertTrue(arch.xpath(".//button[@special='cancel']"))

    def test_purchase_line_opens_only_its_own_history(self):
        order = self.make_order([self.now, self.now + timedelta(days=1)])
        line = order.order_line.sorted("id")[0]
        action = line.with_user(self.buyer).action_open_supplier_deadline_history()
        self.assertEqual(action["res_model"], "supplier.evaluation.deadline.revision")
        self.assertEqual(action["domain"], [("purchase_line_id", "=", line.id)])
        visible = self.env[action["res_model"]].with_user(self.buyer).search(action["domain"])
        self.assertEqual(visible.purchase_line_id, line)

    def test_unsaved_purchase_line_cannot_open_history(self):
        virtual = self.env["purchase.order.line"].new({"name": "Unsaved"})
        with self.assertRaises(UserError):
            virtual.action_open_supplier_deadline_history()

    def test_purchase_view_includes_history_access_for_line_list_and_form(self):
        arch = self.view_arch("purchase.order", "purchase.purchase_order_form", self.manager)
        self.assertTrue(arch.xpath(".//field[@name='order_line']/list//button[@name='action_open_supplier_deadline_history']"))
        self.assertTrue(arch.xpath(".//field[@name='order_line']/form//button[@name='action_open_supplier_deadline_history']"))

    def test_confirmation_views_are_readonly_and_available_from_purchase_menu(self):
        for kind, xmlid in (
            ("form", "supplier_evaluation.view_deadline_confirmation_form"),
            ("list", "supplier_evaluation.view_deadline_confirmation_list"),
        ):
            with self.subTest(kind=kind):
                arch = self.view_arch("supplier.evaluation.deadline.confirmation", xmlid, self.buyer, kind)
                for attribute in ("create", "edit", "delete"):
                    self.assertIn(arch.get(attribute), ("false", "0"))
        menus = self.env["ir.ui.menu"].with_user(self.buyer)._visible_menu_ids()
        self.assertIn(self.env.ref("supplier_evaluation.menu_supplier_deadline_confirmations").id, menus)
        self.assertIn(self.env.ref("supplier_evaluation.menu_supplier_deadline_revisions").id, menus)

    def test_registered_confirmation_is_readable_from_history(self):
        _, _, revision = self.prepare_revision()
        wizard, _ = self.open_wizard(revision)
        self.fill_wizard(wizard)
        action = wizard.action_confirm()
        confirmation = self.env[action["res_model"]].with_user(self.buyer).browse(action["res_id"])
        self.assertEqual(revision.with_user(self.buyer).confirmation_ids, confirmation)
        self.assertTrue(confirmation.read(["justification", "previous_agreed_date", "new_agreed_date"]))

    def test_modal_confirmation_preserves_completed_receipts_and_backorders(self):
        order, line, revision = self.prepare_revision()
        self.receive(order.picking_ids, {line.id: 1}, at=self.now + timedelta(days=5))
        first = order.picking_ids.filtered(lambda picking: picking.state == "done")
        move_fields = ["supplier_original_date_snapshot", "supplier_agreed_date_snapshot",
                       "supplier_receipt_date_snapshot", "supplier_deadline_revision_id",
                       "supplier_deadline_captured_at", "supplier_punctuality"]
        picking_fields = ["supplier_punctuality", "supplier_evaluation_captured_at", "date_done"]
        moves = first.move_ids.read(move_fields)
        picking = first.read(picking_fields)
        wizard, _ = self.open_wizard(revision)
        self.fill_wizard(wizard)
        wizard.action_confirm()
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(first.move_ids.read(move_fields), moves)
        self.assertEqual(first.read(picking_fields), picking)
        self.assertEqual(line.supplier_original_date, self.now)
        backorder = self.env["stock.picking"].search([("backorder_id", "=", first.id)])
        self.assertFalse(backorder.supplier_evaluation_captured_at)
        self.assertFalse(backorder.move_ids.supplier_deadline_captured_at)
