from datetime import timedelta
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_deadline_history import DeadlineHistoryCase


class DeadlineConfirmationCase(DeadlineHistoryCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Deadline Test Manager", "login": "supplier_deadline_test_manager",
            "company_id": cls.env.company.id,
            "company_ids": [Command.set(cls.env.company.ids)],
            "groups_id": [Command.set([
                cls.env.ref("base.group_user").id,
                cls.env.ref("purchase.group_purchase_manager").id,
                cls.env.ref("stock.group_stock_user").id,
            ])],
        })

    def prepare_revision(self, days=2):
        order = self.make_order()
        line = order.order_line
        line.date_planned = self.now + timedelta(days=days)
        return order, line, self.revisions(line)[-1]

    def confirm(self, revision, attributable=True, reason="Acord explícit documentat amb el proveïdor"):
        action = revision.with_user(self.manager).action_confirm_renegotiation(reason, attributable)
        self.assertEqual(action["res_model"], "supplier.evaluation.deadline.confirmation")
        return self.env["supplier.evaluation.deadline.confirmation"].browse(action["res_id"])

    def values(self, revision, **extra):
        return dict({
            "revision_id": revision.id, "justification": "Acord documentat",
            "supplier_attributable": True,
        }, **extra)


@tagged("post_install", "-at_install")
class TestDeadlineConfirmation(DeadlineConfirmationCase):

    def test_manager_confirms_without_modifying_revision(self):
        order, line, revision = self.prepare_revision()
        fields = ["previous_date", "new_date", "revision_type", "change_source",
                  "change_direction", "changed_by_id", "changed_at", "write_date"]
        history = self.revisions(line)
        before = history.read(fields)
        moment = self.now + timedelta(hours=1)
        with patch("odoo.fields.Datetime.now", return_value=moment):
            confirmation = self.confirm(revision, reason="  Acord per correu  ")
        self.assertEqual(confirmation.revision_id, revision)
        self.assertEqual(confirmation.purchase_line_id, line)
        self.assertEqual(confirmation.order_id, order)
        self.assertEqual(confirmation.company_id, order.company_id)
        self.assertEqual(confirmation.supplier_id, order.partner_id)
        self.assertEqual(confirmation.previous_agreed_date, self.now)
        self.assertEqual(confirmation.new_agreed_date, line.date_planned)
        self.assertEqual(confirmation.confirmed_by_id, self.manager)
        self.assertEqual(confirmation.confirmed_at, moment)
        self.assertEqual(confirmation.justification, "Acord per correu")
        self.assertTrue(confirmation.supplier_attributable)
        self.assertEqual(confirmation.change_direction, "postponed")
        self.assertFalse(confirmation.previous_confirmation_id)
        self.assertEqual(revision.confirmation_ids, confirmation)
        self.assertEqual(line.supplier_deadline_confirmation_ids, confirmation)
        self.assertEqual(self.revisions(line), history)
        self.assertEqual(history.read(fields), before)
        # Phase one records attribution, without changing reliability metrics.
        self.assertEqual(line.supplier_postponement_count, 0)

    def test_buyers_and_stock_users_cannot_confirm_even_with_sudo(self):
        _, _, revision = self.prepare_revision()
        Model = self.env["supplier.evaluation.deadline.confirmation"]
        for user in (self.buyer, self.warehouse_user):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    revision.with_user(user).action_confirm_renegotiation("Acord", True)
                with self.assertRaises(AccessError):
                    Model.with_user(user).create(self.values(revision))
                with self.assertRaises(AccessError):
                    Model.with_user(user).sudo().create(self.values(revision))
        self.assertFalse(revision.confirmation_ids)

    def test_direct_create_still_validates_and_derives_server_fields(self):
        _, line, revision = self.prepare_revision()
        confirmation = self.env["supplier.evaluation.deadline.confirmation"].with_user(self.manager).create(
            self.values(revision, supplier_attributable=False),
        )
        self.assertEqual(confirmation.confirmed_by_id, self.manager)
        self.assertEqual(confirmation.previous_agreed_date, line.supplier_original_date)
        self.assertEqual(confirmation.new_agreed_date, revision.new_date)
        self.assertFalse(confirmation.supplier_attributable)

    def test_both_reader_groups_can_read_but_not_create(self):
        _, _, revision = self.prepare_revision()
        confirmation = self.confirm(revision)
        for user in (self.buyer, self.warehouse_user):
            with self.subTest(user=user.login):
                self.assertEqual(confirmation.with_user(user).read(["justification"])[0]["justification"], confirmation.justification)
                with self.assertRaises(AccessError):
                    self.env[confirmation._name].with_user(user).check_access("create")

    def test_justification_is_mandatory(self):
        _, _, revision = self.prepare_revision()
        for reason in (None, False, "", " \n\t "):
            with self.subTest(reason=reason), self.assertRaises(ValidationError):
                self.confirm(revision, reason=reason)

    def test_attribution_must_be_an_explicit_boolean(self):
        _, _, revision = self.prepare_revision()
        Model = self.env["supplier.evaluation.deadline.confirmation"].with_user(self.manager)
        missing = self.values(revision)
        missing.pop("supplier_attributable")
        with self.assertRaises(ValidationError):
            Model.create(missing)
        for value in (None, "true", 1, 0):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Model.create(self.values(revision, supplier_attributable=value))

    def test_duplicate_confirmation_is_rejected(self):
        _, _, revision = self.prepare_revision()
        confirmation = self.confirm(revision)
        with self.assertRaises(ValidationError):
            self.confirm(revision)
        self.assertEqual(revision.confirmation_ids, confirmation)

    def test_duplicate_batch_is_atomic(self):
        _, _, revision = self.prepare_revision()
        with self.assertRaises(ValidationError):
            self.env["supplier.evaluation.deadline.confirmation"].with_user(self.manager).create([
                self.values(revision), self.values(revision),
            ])
        self.assertFalse(revision.confirmation_ids)

    def test_sql_constraint_protects_against_duplicate_insert(self):
        _, _, revision = self.prepare_revision()
        confirmation = self.confirm(revision)
        confirmation.flush_recordset()
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.cr.execute("""
                INSERT INTO supplier_evaluation_deadline_confirmation
                    (revision_id, purchase_line_id, order_id, company_id, supplier_id,
                     previous_agreed_date, new_agreed_date, confirmed_by_id, confirmed_at,
                     justification, supplier_attributable, change_direction)
                SELECT revision_id, purchase_line_id, order_id, company_id, supplier_id,
                       previous_agreed_date, new_agreed_date, confirmed_by_id, confirmed_at,
                       justification, supplier_attributable, change_direction
                  FROM supplier_evaluation_deadline_confirmation WHERE id = %s
            """, [confirmation.id])
        self.assertEqual(revision.confirmation_ids, confirmation)

    def test_confirmation_and_copy_are_immutable_even_for_sudo(self):
        _, _, revision = self.prepare_revision()
        confirmation = self.confirm(revision)
        with self.assertRaises(AccessError):
            confirmation.sudo().write({"supplier_attributable": False})
        with self.assertRaises(UserError):
            confirmation.sudo().unlink()
        with self.assertRaises(UserError):
            confirmation.copy()

    def test_caller_cannot_forge_audit_dates_or_links(self):
        order, _, revision = self.prepare_revision()
        Model = self.env["supplier.evaluation.deadline.confirmation"].with_user(self.manager)
        for field, value in (
            ("confirmed_by_id", self.buyer.id), ("confirmed_at", self.now),
            ("previous_agreed_date", self.now), ("new_agreed_date", self.now),
            ("company_id", order.company_id.id), ("previous_confirmation_id", False),
            ("create_uid", self.buyer.id), ("change_direction", "advanced"),
        ):
            with self.subTest(field=field), self.assertRaises(AccessError):
                Model.create(self.values(revision, **{field: value}))
        with self.assertRaises(AccessError):
            Model.with_context(default_confirmed_by_id=self.buyer.id).create(self.values(revision))
        self.assertFalse(revision.confirmation_ids)

    def test_initial_and_unknown_baselines_are_not_renegotiations(self):
        order = self.make_order()
        with self.assertRaises(ValidationError):
            self.confirm(self.revisions(order.order_line)[0])
        legacy = self.make_order(confirm=False)
        line = legacy.order_line
        line.flush_recordset()
        self.cr.execute("UPDATE purchase_order_line SET supplier_original_date_pending = false WHERE id = %s", [line.id])
        line.invalidate_recordset()
        legacy.button_confirm()
        with self.assertRaises(ValidationError):
            self.confirm(self.revisions(line)[0])
        line.date_planned = self.now + timedelta(days=2)
        with self.assertRaises(ValidationError):
            self.confirm(self.revisions(line)[-1])
        self.assertFalse(line.supplier_original_date_known)
        self.assertFalse(line.supplier_deadline_confirmation_ids)

    def test_stale_revision_is_not_confirmable(self):
        _, line, revision = self.prepare_revision()
        line.date_planned += timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.confirm(revision)
        self.assertFalse(revision.confirmation_ids)

    def test_return_to_accepted_date_is_not_a_renegotiation(self):
        _, line, _ = self.prepare_revision()
        line.date_planned = line.supplier_original_date
        with self.assertRaises(ValidationError):
            self.confirm(self.revisions(line)[-1])
        self.assertFalse(line.supplier_deadline_confirmation_ids)

    def test_missing_or_unchanged_dates_are_not_confirmable(self):
        _, line, _ = self.prepare_revision()
        line._supplier_lock_deadlines()
        Revision = self.env["supplier.evaluation.deadline.revision"]
        for old, new in ((False, line.date_planned), (line.date_planned, False), (line.date_planned, line.date_planned)):
            revision = Revision._append_revision(line, old, new, "technical")
            with self.assertRaises(ValidationError):
                self.confirm(revision)

    def test_cancelled_order_is_not_confirmable(self):
        order, _, revision = self.prepare_revision()
        order.button_cancel()
        with self.assertRaises(ValidationError):
            self.confirm(revision)

    def test_supplier_change_invalidates_old_revision(self):
        order, _, revision = self.prepare_revision()
        alternate = self.env["res.partner"].create({"name": "Confirmation Alternate Vendor"})
        order.partner_id = alternate
        with self.assertRaises(ValidationError):
            self.confirm(revision)

    def test_new_supplier_cannot_inherit_another_suppliers_accepted_date(self):
        order, line, _ = self.prepare_revision()
        alternate = self.env["res.partner"].create({"name": "Confirmation New Supplier"})
        order.partner_id = alternate
        line.date_planned = self.now + timedelta(days=6)
        revision = self.revisions(line)[-1]
        self.assertEqual(revision.supplier_id, alternate)
        with self.assertRaises(ValidationError):
            self.confirm(revision)
        self.assertFalse(line.supplier_deadline_confirmation_ids)

    def test_chain_uses_last_accepted_date_not_last_technical_date(self):
        _, line, first_revision = self.prepare_revision()
        first = self.confirm(first_revision)
        line.date_planned = self.now + timedelta(days=3)
        line.date_planned = self.now + timedelta(days=5)
        second = self.confirm(self.revisions(line)[-1], attributable=False)
        self.assertEqual(second.previous_confirmation_id, first)
        self.assertEqual(second.previous_agreed_date, first.new_agreed_date)
        self.assertNotEqual(second.previous_agreed_date, second.revision_id.previous_date)
        self.assertEqual(second.new_agreed_date, line.date_planned)
        self.assertFalse(second.supplier_attributable)

    def test_earlier_accepted_date_is_supported(self):
        _, _, revision = self.prepare_revision(days=-2)
        confirmation = self.confirm(revision)
        self.assertEqual(confirmation.change_direction, "advanced")
        self.assertLess(confirmation.new_agreed_date, confirmation.previous_agreed_date)

    def test_confirmations_do_not_change_completed_evaluations_or_history(self):
        order, line, revision = self.prepare_revision()
        self.receive(order.picking_ids, at=self.now + timedelta(days=5))
        move_fields = ["supplier_original_date_snapshot", "supplier_agreed_date_snapshot",
                       "supplier_receipt_date_snapshot", "supplier_deadline_revision_id",
                       "supplier_deadline_captured_at", "supplier_punctuality"]
        picking_fields = ["supplier_punctuality", "supplier_evaluation_captured_at", "date_done"]
        moves = order.picking_ids.move_ids
        before_moves = moves.read(move_fields)
        before_pickings = order.picking_ids.read(picking_fields)
        history = self.revisions(line)
        before_history = history.read(["previous_date", "new_date", "revision_type", "change_source", "write_date"])
        self.confirm(revision)
        order.picking_ids._action_done()
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(moves.read(move_fields), before_moves)
        self.assertEqual(order.picking_ids.read(picking_fields), before_pickings)
        self.assertEqual(history.read(["previous_date", "new_date", "revision_type", "change_source", "write_date"]), before_history)
        self.assertEqual(self.revisions(line), history)

    def test_partial_receipt_and_backorder_remain_independent(self):
        order, line, revision = self.prepare_revision()
        self.receive(order.picking_ids, {line.id: 1})
        first = order.picking_ids.filtered(lambda picking: picking.state == "done")
        before = first.move_ids.read(["supplier_deadline_revision_id", "supplier_agreed_date_snapshot", "supplier_deadline_captured_at"])
        self.confirm(revision)
        backorder = self.env["stock.picking"].search([("backorder_id", "=", first.id)])
        self.assertFalse(backorder.supplier_evaluation_captured_at)
        self.assertFalse(backorder.move_ids.supplier_deadline_captured_at)
        self.assertEqual(first.move_ids.read(["supplier_deadline_revision_id", "supplier_agreed_date_snapshot", "supplier_deadline_captured_at"]), before)

    def test_duplicate_order_does_not_inherit_confirmations(self):
        order, _, revision = self.prepare_revision()
        self.confirm(revision)
        duplicate = order.copy()
        self.assertFalse(duplicate.order_line.supplier_deadline_confirmation_ids)
        self.assertFalse(duplicate.order_line.supplier_deadline_revision_ids)
        duplicate.button_confirm()
        self.assertFalse(duplicate.order_line.supplier_deadline_confirmation_ids)

    def test_multiple_lines_keep_separate_confirmation_chains(self):
        order = self.make_order([self.now, self.now + timedelta(days=1)])
        for index, line in enumerate(order.order_line):
            original = line.supplier_original_date
            line.date_planned += timedelta(days=3)
            confirmation = self.confirm(self.revisions(line)[-1], attributable=bool(index))
            self.assertEqual(confirmation.purchase_line_id, line)
            self.assertEqual(confirmation.previous_agreed_date, original)
            self.assertFalse(confirmation.previous_confirmation_id)
        self.assertEqual(len(order.order_line.supplier_deadline_confirmation_ids), 2)

    def test_foreign_company_is_rejected_even_with_sudo(self):
        company = self.env["res.company"].create({"name": "Confirmation Other Company"})
        env = self.env["purchase.order"].with_company(company).env
        warehouse = env["stock.warehouse"].create({
            "name": "Confirmation Other Warehouse", "code": "DCF", "company_id": company.id,
        })
        receipt_type = warehouse.in_type_id
        order = env["purchase.order"].create({
            "partner_id": self.vendor.id, "picking_type_id": receipt_type.id,
            "order_line": [Command.create({"product_id": self.product.id, "name": self.product.name,
                                           "product_qty": 1, "product_uom": self.product.uom_id.id,
                                           "price_unit": 1, "date_planned": self.now})],
        })
        order.button_confirm()
        order.order_line.date_planned += timedelta(days=2)
        revision = self.revisions(order.order_line)[-1]
        Model = env["supplier.evaluation.deadline.confirmation"].with_user(self.manager).sudo()
        with self.assertRaises(AccessError):
            Model.create(self.values(revision))
        self.assertFalse(revision.confirmation_ids)
