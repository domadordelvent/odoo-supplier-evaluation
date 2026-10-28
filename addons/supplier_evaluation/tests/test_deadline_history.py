from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


class DeadlineHistoryCase(TransactionCase):
    """Real ORM, purchase approvals, stock validation and transaction rollback."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.now = datetime(2026, 10, 17, 12)
        cls.vendor = cls.env["res.partner"].create({"name": "Deadline History Test Vendor"})
        cls.product = cls.env["product.product"].create({
            "name": "Deadline History Test Product", "type": "consu",
        })
        cls.receipt_type = cls.env["stock.picking.type"].search([
            ("code", "=", "incoming"), ("company_id", "=", cls.env.company.id),
        ], limit=1).copy({"name": "Deadline Test Receipts", "create_backorder": "always"})
        cls.buyer = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Deadline Test Buyer", "login": "supplier_deadline_test_buyer",
            "company_id": cls.env.company.id,
            "company_ids": [Command.set(cls.env.company.ids)],
            "groups_id": [Command.set([
                cls.env.ref("base.group_user").id,
                cls.env.ref("purchase.group_purchase_user").id,
                cls.env.ref("stock.group_stock_user").id,
            ])],
        })
        cls.warehouse_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Deadline Test Warehouse", "login": "supplier_deadline_test_stock",
            "company_id": cls.env.company.id,
            "company_ids": [Command.set(cls.env.company.ids)],
            "groups_id": [Command.set([
                cls.env.ref("base.group_user").id,
                cls.env.ref("stock.group_stock_user").id,
            ])],
        })

    def make_order(self, dates=None, qty=2, confirm=True):
        order = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "picking_type_id": self.receipt_type.id,
            "order_line": [Command.create({
                "product_id": self.product.id, "name": self.product.name,
                "product_qty": qty, "product_uom": self.product.uom_id.id,
                "price_unit": 1, "date_planned": date,
            }) for date in (dates or [self.now])],
        })
        if confirm:
            order.button_confirm()
        return order

    def receive(self, picking, quantities=None, at=None, user=None):
        for move in picking.move_ids.filtered(lambda record: record.state not in ("done", "cancel")):
            qty = (quantities or {}).get(move.purchase_line_id.id, move.product_uom_qty)
            move.quantity = qty
            move.picked = bool(qty)
        with patch("odoo.fields.Datetime.now", return_value=at or self.now):
            result = (picking.with_user(user) if user else picking).button_validate()
        self.assertIs(result, True, "Expected validation, not an unresolved stock wizard")
        self.assertEqual(picking.state, "done")

    def revisions(self, line):
        return line.supplier_deadline_revision_ids.sorted("sequence")


@tagged("post_install", "-at_install")
class TestDeadlineHistory(DeadlineHistoryCase):

    def test_original_is_captured_at_approval(self):
        order = self.make_order(confirm=False)
        line = order.order_line
        self.assertFalse(line.supplier_original_date_known)
        self.assertFalse(line.supplier_deadline_revision_ids)
        agreed = self.now + timedelta(days=2)
        line.date_planned = agreed
        order.button_confirm()
        self.assertTrue(line.supplier_original_date_known)
        self.assertEqual(line.supplier_original_date, agreed)
        self.assertEqual(self.revisions(line).revision_type, "initial")
        self.assertFalse(line.supplier_original_date_pending)

    def test_successive_changes_and_actor_are_recorded(self):
        line = self.make_order().order_line
        self.assertEqual(line.supplier_postponement_count, 0)
        for delta in (1, 2, 1):
            line.with_user(self.buyer).date_planned = self.now + timedelta(days=delta)
        revisions = self.revisions(line)
        self.assertEqual(revisions.mapped("sequence"), [1, 2, 3, 4])
        self.assertEqual(revisions.mapped("revision_type"), ["initial", "technical", "technical", "technical"])
        self.assertEqual(revisions[1:].mapped("change_direction"), ["postponed", "postponed", "advanced"])
        self.assertEqual(revisions[1:].mapped("change_source"), ["unverified"] * 3)
        self.assertEqual(revisions[1:].mapped("changed_by_id"), self.buyer)
        self.assertEqual(revisions[1].previous_date, self.now)
        self.assertEqual(revisions[1].new_date, self.now + timedelta(days=1))
        self.assertEqual(line.supplier_original_date, self.now)
        self.assertEqual(line.supplier_postponement_count, 0)
        line.date_planned = line.date_planned
        self.assertEqual(len(self.revisions(line)), 4)

    def test_several_lines_keep_independent_deadlines(self):
        order = self.make_order([self.now - timedelta(days=2), self.now + timedelta(days=2)])
        picking = order.picking_ids
        picking.ensure_one()
        self.receive(picking)
        first, second = order.order_line.sorted("id")
        first_move = picking.move_ids.filtered(lambda move: move.purchase_line_id == first)
        second_move = picking.move_ids.filtered(lambda move: move.purchase_line_id == second)
        self.assertEqual(first_move.supplier_punctuality, "late")
        self.assertEqual(second_move.supplier_punctuality, "on_time")
        self.assertEqual(picking.supplier_punctuality, "late")
        self.assertEqual(first_move.supplier_agreed_date_snapshot, first.date_planned)
        self.assertEqual(second_move.supplier_agreed_date_snapshot, second.date_planned)

    def test_exact_tolerance_and_one_second_late(self):
        for offset, expected in [(0, "on_time"), (1, "late")]:
            with self.subTest(offset=offset):
                order = self.make_order([self.now - timedelta(hours=24)])
                self.receive(order.picking_ids, at=self.now + timedelta(seconds=offset))
                self.assertEqual(order.picking_ids.supplier_punctuality, expected)

    def test_purchase_revision_is_used_instead_of_logistic_schedule(self):
        order = self.make_order([self.now - timedelta(days=5)])
        picking, line = order.picking_ids, order.order_line
        schedule = picking.scheduled_date
        line.date_planned = self.now
        self.assertEqual(picking.scheduled_date, schedule)
        self.receive(picking)
        self.assertEqual(picking.supplier_punctuality, "on_time")
        self.assertEqual(picking.move_ids.supplier_original_date_snapshot, self.now - timedelta(days=5))
        self.assertEqual(picking.move_ids.supplier_agreed_date_snapshot, self.now)
        self.assertEqual(line.supplier_postponement_count, 0)

    def test_partials_do_not_copy_snapshots_and_keep_their_own_agreement(self):
        order = self.make_order(qty=3)
        line, first = order.order_line, order.picking_ids
        self.receive(first, {line.id: 1})
        backorder = self.env["stock.picking"].search([("backorder_id", "=", first.id)])
        backorder.ensure_one()
        self.assertFalse(backorder.supplier_evaluation_captured_at)
        self.assertFalse(backorder.supplier_punctuality)
        for field in (
            "supplier_original_date_snapshot", "supplier_agreed_date_snapshot",
            "supplier_receipt_date_snapshot", "supplier_deadline_revision_id",
            "supplier_deadline_captured_at", "supplier_punctuality",
        ):
            self.assertFalse(backorder.move_ids[field], field)
        first_revision = first.move_ids.supplier_deadline_revision_id
        line.date_planned = self.now + timedelta(days=2)
        self.receive(backorder, {line.id: 1}, at=self.now + timedelta(days=2))
        self.assertEqual(first.move_ids.supplier_agreed_date_snapshot, self.now)
        self.assertEqual(first.move_ids.supplier_deadline_revision_id, first_revision)
        self.assertEqual(backorder.move_ids.supplier_agreed_date_snapshot, self.now + timedelta(days=2))
        self.assertEqual(backorder.move_ids.supplier_original_date_snapshot, self.now)
        self.assertEqual(first.supplier_punctuality, "on_time")
        self.assertEqual(backorder.supplier_punctuality, "on_time")
        third = self.env["stock.picking"].search([("backorder_id", "=", backorder.id)])
        third.ensure_one()
        self.assertFalse(third.move_ids.supplier_deadline_captured_at)

    def test_validated_receipt_is_not_reclassified(self):
        order = self.make_order([self.now - timedelta(days=2)])
        picking, line = order.picking_ids, order.order_line
        self.receive(picking)
        move = picking.move_ids
        snapshots = move.read([
            "supplier_original_date_snapshot", "supplier_agreed_date_snapshot",
            "supplier_receipt_date_snapshot", "supplier_deadline_revision_id",
            "supplier_deadline_captured_at", "supplier_punctuality",
        ])
        line.date_planned = self.now + timedelta(days=10)
        picking.date_done = self.now + timedelta(days=20)
        picking.partner_id = False
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(move.read(list(snapshots[0].keys() - {"id"})), snapshots)
        self.assertEqual(picking.supplier_punctuality, "late")

    def test_repeated_validation_does_not_recapture(self):
        order = self.make_order()
        picking, line = order.picking_ids, order.order_line
        self.receive(picking)
        marker, date_done = picking.supplier_evaluation_captured_at, picking.date_done
        move_marker = picking.move_ids.supplier_deadline_captured_at
        line.date_planned = self.now + timedelta(days=1)
        revisions = self.revisions(line)
        with patch("odoo.fields.Datetime.now", return_value=self.now + timedelta(days=2)):
            picking._action_done()
            picking._action_done()
        self.assertEqual(picking.supplier_evaluation_captured_at, marker)
        self.assertEqual(picking.date_done, date_done)
        self.assertEqual(picking.move_ids.supplier_deadline_captured_at, move_marker)
        self.assertEqual(picking.move_ids.supplier_agreed_date_snapshot, self.now)
        self.assertEqual(self.revisions(line), revisions)

    def test_ordinary_users_cannot_modify_history_or_snapshots(self):
        order = self.make_order()
        line = order.order_line
        revision = self.revisions(line).with_user(self.buyer)
        for operation in (
            lambda: revision.write({"new_date": self.now + timedelta(days=99)}),
            lambda: revision.unlink(),
            lambda: revision.copy(),
            lambda: line.with_user(self.buyer).write({"supplier_original_date": self.now}),
            lambda: line.with_user(self.buyer).write({"supplier_original_date_known": True}),
            lambda: line.with_user(self.buyer).write({"supplier_original_date_pending": True}),
        ):
            try:
                with self.cr.savepoint():
                    # Match Odoo's AccessError assertion: test permissions
                    # without a warmed cache, and roll back before catching.
                    self.env.cr.clear()
                    operation()
            except (AccessError, UserError):
                pass
            else:
                self.fail("The protected operation accepted an ordinary user's change")
        self.receive(order.picking_ids)
        for record, values in (
            (order.picking_ids, {"supplier_punctuality": "late"}),
            (order.picking_ids, {"supplier_evaluation_captured_at": False}),
            (order.picking_ids.move_ids, {"supplier_agreed_date_snapshot": self.now}),
            (order.picking_ids.move_ids, {"supplier_punctuality": "late"}),
        ):
            with self.assertRaises(AccessError), self.cr.savepoint():
                record.with_user(self.buyer).write(values)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.revisions(line).sudo().unlink()

    def test_history_survives_cancel_draft_and_reapproval(self):
        order = self.make_order()
        line = order.order_line
        order.button_cancel()
        order.button_draft()
        line.date_planned = self.now + timedelta(days=2)
        order.button_confirm()
        self.assertEqual(line.supplier_original_date, self.now)
        self.assertEqual(self.revisions(line).mapped("revision_type"), ["initial", "technical"])

    def test_new_line_on_confirmed_order_has_own_original(self):
        order = self.make_order()
        new_date = self.now + timedelta(days=3)
        line = self.env["purchase.order.line"].create({
            "order_id": order.id, "product_id": self.product.id,
            "name": "Added line", "product_qty": 1,
            "product_uom": self.product.uom_id.id, "price_unit": 1,
            "date_planned": new_date,
        })
        self.assertTrue(line.supplier_original_date_known)
        self.assertEqual(line.supplier_original_date, new_date)
        self.assertEqual(self.revisions(line).revision_type, "initial")

    def test_legacy_line_keeps_unknown_original(self):
        order = self.make_order(confirm=False)
        line = order.order_line
        # Simulate the actual upgrade default of a pre-existing row.
        line.flush_recordset()
        self.cr.execute(
            "UPDATE purchase_order_line SET supplier_original_date_pending = false WHERE id = %s",
            [line.id],
        )
        line.invalidate_recordset()
        order.button_confirm()
        self.assertFalse(line.supplier_original_date_known)
        self.assertFalse(line.supplier_original_date)
        self.assertEqual(self.revisions(line).revision_type, "unknown_initial")
        line.date_planned = self.now + timedelta(days=1)
        self.receive(order.picking_ids)
        self.assertFalse(order.picking_ids.move_ids.supplier_original_date_snapshot)
        self.assertEqual(order.picking_ids.move_ids.supplier_agreed_date_snapshot, line.date_planned)
        self.assertFalse(line.supplier_original_date_known)

    def test_old_completed_receipt_is_never_backfilled(self):
        order = self.make_order()
        picking = order.picking_ids
        # Reproduce a pre-upgrade validation by bypassing only our hook.
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        from odoo.addons.supplier_evaluation.models.stock_picking import StockPicking
        super(StockPicking, picking)._action_done()
        self.assertEqual(picking.state, "done")
        self.assertFalse(picking.supplier_evaluation_captured_at)
        picking._action_done()
        self.assertFalse(picking.supplier_evaluation_captured_at)
        self.assertFalse(picking.supplier_punctuality)

    def test_copied_order_starts_a_new_history(self):
        order = self.make_order()
        original_line = order.order_line
        original_line.date_planned = self.now + timedelta(days=2)
        self.receive(order.picking_ids, at=self.now + timedelta(days=2))
        original_revisions = self.revisions(original_line)
        original_history = original_revisions.read([
            "sequence", "previous_date", "new_date", "revision_type",
            "change_source", "change_direction", "purchase_line_id", "order_id",
        ])
        commitment_fields = ["supplier_original_date", "supplier_original_date_known"]
        original_commitment = original_line.read(commitment_fields)
        capture_fields = [
            "supplier_original_date_snapshot", "supplier_agreed_date_snapshot",
            "supplier_receipt_date_snapshot", "supplier_deadline_revision_id",
            "supplier_deadline_captured_at", "supplier_punctuality",
        ]
        original_moves = order.picking_ids.move_ids
        original_captures = original_moves.read(capture_fields)
        receipt_fields = ["supplier_punctuality", "supplier_evaluation_captured_at"]
        original_evaluation = order.picking_ids.read(receipt_fields)

        duplicate = order.copy()
        new_line = duplicate.order_line
        new_line.ensure_one()
        self.assertNotEqual(new_line.id, original_line.id)
        self.assertFalse(new_line.supplier_original_date)
        self.assertFalse(new_line.supplier_original_date_known)
        self.assertFalse(new_line.supplier_deadline_revision_ids)
        self.assertFalse(new_line.move_ids)
        self.assertFalse(duplicate.picking_ids)

        # purchase.order.copy() explicitly resets date_planned using these
        # standard purchase helpers; copying a negotiated date is not promised.
        seller = new_line.product_id._select_seller(
            partner_id=new_line.partner_id, quantity=new_line.product_qty,
            date=duplicate.date_order and duplicate.date_order.date(),
            uom_id=new_line.product_uom,
        )
        expected_date = new_line._get_date_planned(seller)
        self.assertEqual(new_line.date_planned, expected_date)
        duplicate.button_confirm()
        self.assertEqual(new_line.supplier_original_date, expected_date)
        self.assertTrue(new_line.supplier_original_date_known)
        initial = self.revisions(new_line)
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial.revision_type, "initial")
        self.assertEqual(initial.new_date, expected_date)
        self.assertEqual(initial.purchase_line_id, new_line)
        self.assertEqual(initial.order_id, duplicate)
        self.assertFalse(initial & original_revisions)

        new_receipts = duplicate.picking_ids
        self.assertTrue(new_receipts)
        self.assertFalse(new_receipts & order.picking_ids)
        for receipt in new_receipts:
            self.assertFalse(receipt.supplier_punctuality)
            self.assertFalse(receipt.supplier_evaluation_captured_at)
        self.assertTrue(new_receipts.move_ids)
        for move in new_receipts.move_ids:
            for field in capture_fields:
                self.assertFalse(move[field], field)

        new_line.date_planned = expected_date + timedelta(days=3)
        self.env.flush_all()
        new_history = self.revisions(new_line)
        self.assertEqual(new_history.mapped("sequence"), [1, 2])
        self.assertEqual(new_history[-1].revision_type, "technical")
        self.assertEqual(new_history[-1].previous_date, expected_date)
        self.assertEqual(new_history[-1].new_date, new_line.date_planned)
        self.assertEqual(new_history.mapped("purchase_line_id"), new_line)
        self.assertEqual(new_history.mapped("order_id"), duplicate)
        self.assertFalse(new_history & original_revisions)
        self.env.invalidate_all()
        self.assertEqual(self.revisions(original_line), original_revisions)
        self.assertEqual(original_revisions.read(list(original_history[0].keys() - {"id"})), original_history)
        self.assertEqual(original_line.read(commitment_fields), original_commitment)
        self.assertEqual(original_moves.read(capture_fields), original_captures)
        self.assertEqual(order.picking_ids.read(receipt_fields), original_evaluation)

    def test_stock_user_without_purchase_rights_can_validate(self):
        order = self.make_order()
        self.receive(order.picking_ids, user=self.warehouse_user)
        self.assertEqual(order.picking_ids.supplier_punctuality, "on_time")

    def test_failed_validation_rolls_back_all_captures(self):
        order = self.make_order()
        picking = order.picking_ids
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        MoveClass = type(self.env["stock.move"])
        original = MoveClass._supplier_capture_deadline

        def capture_then_fail(move, *args):
            original(move, *args)
            raise UserError("Simulated failure after capture")

        with self.assertRaises(UserError), self.cr.savepoint():
            with patch.object(MoveClass, "_supplier_capture_deadline", capture_then_fail):
                picking._action_done()
        self.assertNotEqual(picking.state, "done")
        self.assertFalse(picking.supplier_evaluation_captured_at)
        self.assertFalse(picking.move_ids.supplier_deadline_captured_at)

    def test_unreceived_late_line_does_not_make_receipt_late(self):
        order = self.make_order([self.now - timedelta(days=5), self.now])
        first, second = order.order_line.sorted("id")
        picking = order.picking_ids
        self.receive(picking, {first.id: 0, second.id: 1})
        self.assertEqual(picking.supplier_punctuality, "on_time")
        self.assertEqual(picking.move_ids.purchase_line_id, second)
        backorder = self.env["stock.picking"].search([("backorder_id", "=", picking.id)])
        self.assertTrue(backorder.move_ids.filtered(lambda move: move.purchase_line_id == first))
        self.assertFalse(any(backorder.move_ids.mapped("supplier_deadline_captured_at")))

    def test_missing_purchase_link_prevents_false_on_time(self):
        order = self.make_order()
        picking = order.picking_ids
        picking.move_ids.copy({"purchase_line_id": False})
        self.receive(picking)
        self.assertTrue(picking.supplier_evaluation_captured_at)
        self.assertFalse(picking.supplier_punctuality)
        unknown = picking.move_ids.filtered(lambda move: not move.purchase_line_id)
        self.assertTrue(unknown.supplier_deadline_captured_at)
        self.assertFalse(unknown.supplier_agreed_date_snapshot)

    def test_proven_lateness_wins_over_missing_data(self):
        order = self.make_order([self.now - timedelta(days=5)])
        picking = order.picking_ids
        picking.move_ids.copy({"purchase_line_id": False})
        self.receive(picking)
        self.assertEqual(picking.supplier_punctuality, "late")

    def test_double_approval_captures_only_final_agreement(self):
        self.env.company.write({"po_double_validation": "two_step", "po_double_validation_amount": 0})
        order = self.make_order(confirm=False)
        order.with_user(self.buyer).button_confirm()
        self.assertEqual(order.state, "to approve")
        self.assertFalse(order.order_line.supplier_deadline_revision_ids)
        order.order_line.date_planned = self.now + timedelta(days=2)
        order.button_approve()
        self.assertEqual(order.order_line.supplier_original_date, self.now + timedelta(days=2))
        self.assertEqual(len(self.revisions(order.order_line)), 1)

    def make_order_with_supplier_delay(self):
        self.env["product.supplierinfo"].create({
            "partner_id": self.vendor.id,
            "product_tmpl_id": self.product.product_tmpl_id.id,
            "min_qty": 0, "price": 1, "delay": 3,
        })
        order = self.make_order()
        order.date_order = self.now
        self.env.flush_all()
        return order

    def test_recompute_quantity_records_a_single_technical_change(self):
        order = self.make_order_with_supplier_delay()
        line = order.order_line
        before = self.revisions(line)
        original, old_date = line.supplier_original_date, line.date_planned
        line.product_qty = 5
        self.env.flush_all()
        self.assertNotEqual(line.date_planned, old_date)
        added = self.revisions(line) - before
        self.assertEqual(len(added), 1)
        self.assertEqual(added.previous_date, old_date)
        self.assertEqual(added.new_date, line.date_planned)
        self.assertEqual(added.revision_type, "technical")
        self.assertEqual(added.change_source, "unverified")
        self.assertEqual(added.change_direction, "postponed")
        self.assertEqual(line.supplier_original_date, original)
        self.assertEqual(line.supplier_postponement_count, 0)
        self.env.flush_all()
        line.invalidate_recordset()
        self.assertEqual(self.revisions(line) - before, added)

    def test_recompute_same_date_does_not_add_revision(self):
        line = self.make_order_with_supplier_delay().order_line
        line.product_qty = 5
        self.env.flush_all()
        revisions = self.revisions(line)
        # Same seller and delay: a second calculation produces the same date.
        line.product_qty = 6
        self.env.flush_all()
        self.assertEqual(self.revisions(line), revisions)

    def test_explicit_date_and_computation_in_one_write_are_not_duplicated(self):
        line = self.make_order_with_supplier_delay().order_line
        before = self.revisions(line)
        explicit = self.now + timedelta(days=8)
        line.write({"product_qty": 5, "date_planned": explicit})
        self.env.flush_all()
        added = self.revisions(line) - before
        self.assertEqual(len(added), 1)
        self.assertEqual(line.date_planned, explicit)
        self.assertEqual(added.new_date, explicit)
        self.assertEqual(added.revision_type, "technical")
        self.assertEqual(line.supplier_postponement_count, 0)

    def test_separate_explicit_writes_preserve_intermediate_dates(self):
        line = self.make_order().order_line
        before = self.revisions(line)
        line.date_planned = self.now + timedelta(days=1)
        line.date_planned = self.now + timedelta(days=2)
        line.date_planned = self.now + timedelta(days=2)
        self.env.flush_all()
        added = (self.revisions(line) - before).sorted("sequence")
        self.assertEqual(added.mapped("new_date"), [self.now + timedelta(days=1), self.now + timedelta(days=2)])
        self.assertEqual(added.mapped("revision_type"), ["technical", "technical"])

    def test_partner_recompute_is_technical_and_line_specific(self):
        order = self.make_order([self.now, self.now + timedelta(days=1)])
        alternate = self.env["res.partner"].create({"name": "Deadline Alternate Vendor"})
        self.env["product.supplierinfo"].create({
            "partner_id": alternate.id, "product_tmpl_id": self.product.product_tmpl_id.id,
            "min_qty": 0, "price": 1, "delay": 7,
        })
        order.date_order = self.now
        before = {line.id: self.revisions(line) for line in order.order_line}
        old_dates = {line.id: line.date_planned for line in order.order_line}
        order.partner_id = alternate
        self.env.flush_all()
        for line in order.order_line:
            added = self.revisions(line) - before[line.id]
            self.assertEqual(len(added), 1)
            self.assertEqual(added.previous_date, old_dates[line.id])
            self.assertEqual(added.new_date, line.date_planned)
            self.assertEqual(added.revision_type, "technical")
            self.assertEqual(added.change_source, "unverified")
            self.assertEqual(line.supplier_postponement_count, 0)

    def test_virtual_existing_line_never_changes_persisted_history(self):
        line = self.make_order_with_supplier_delay().order_line
        before, original_date = self.revisions(line), line.date_planned
        virtual = line.new({
            "order_id": line.order_id.id, "product_id": line.product_id.id,
            "product_uom": line.product_uom.id, "product_qty": 20,
            "date_planned": line.date_planned, "name": line.name,
        }, origin=line)
        self.assertFalse(virtual.id)
        virtual._compute_price_unit_and_date_planned_and_name()
        virtual.update({"date_planned": self.now + timedelta(days=20)})
        self.env.flush_all()
        line.invalidate_recordset()
        self.assertEqual(line.date_planned, original_date)
        self.assertEqual(self.revisions(line), before)

    def test_unsaved_new_form_line_has_no_history(self):
        order = self.make_order(confirm=False)
        virtual = self.env["purchase.order.line"].new({
            "order_id": order.id, "product_id": self.product.id,
            "product_uom": self.product.uom_id.id, "product_qty": 4,
        })
        Revision = self.env["supplier.evaluation.deadline.revision"]
        before = Revision.search_count([])
        virtual._compute_price_unit_and_date_planned_and_name()
        virtual.update({"date_planned": self.now + timedelta(days=7)})
        self.env.flush_all()
        self.assertEqual(Revision.search_count([]), before)
        self.assertFalse(virtual.supplier_deadline_revision_ids)

    def test_automatic_recompute_preserves_completed_captures(self):
        order = self.make_order_with_supplier_delay()
        line, picking = order.order_line, order.picking_ids
        self.receive(picking)
        snapshot_fields = [
            "supplier_original_date_snapshot", "supplier_agreed_date_snapshot",
            "supplier_receipt_date_snapshot", "supplier_deadline_revision_id",
            "supplier_deadline_captured_at", "supplier_punctuality",
        ]
        move = picking.move_ids
        snapshot = move.read(snapshot_fields)
        receipt = picking.read(["supplier_punctuality", "supplier_evaluation_captured_at"])
        line.product_qty = 5
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(move.read(snapshot_fields), snapshot)
        self.assertEqual(picking.read(["supplier_punctuality", "supplier_evaluation_captured_at"]), receipt)
        self.assertEqual(self.revisions(line)[-1].revision_type, "technical")

    def test_preapproval_recomputation_does_not_create_commitment(self):
        order = self.make_order_with_supplier_delay().copy()
        line = order.order_line
        self.assertFalse(line.supplier_deadline_revision_ids)
        line.product_qty = 10
        self.env.flush_all()
        self.assertFalse(line.supplier_deadline_revision_ids)
        self.assertFalse(line.supplier_original_date_known)
        effective_date = line.date_planned
        order.button_confirm()
        self.assertEqual(line.supplier_original_date, effective_date)
        self.assertEqual(len(self.revisions(line)), 1)

    def test_legacy_automatic_change_records_unknown_baseline(self):
        order = self.make_order_with_supplier_delay().copy()
        line = order.order_line
        line.date_planned = self.now
        self.env.flush_all()
        # Simulate an already-approved pre-upgrade line without using new hooks.
        self.cr.execute("UPDATE purchase_order SET state = 'purchase' WHERE id = %s", [order.id])
        self.cr.execute(
            "UPDATE purchase_order_line SET supplier_original_date_pending = false WHERE id = %s",
            [line.id],
        )
        order.invalidate_recordset()
        line.invalidate_recordset()
        old_date = line.date_planned
        line.product_qty = 10
        self.env.flush_all()
        self.assertNotEqual(line.date_planned, old_date)
        revisions = self.revisions(line)
        self.assertEqual(revisions.mapped("revision_type"), ["unknown_initial", "technical"])
        self.assertEqual(revisions[0].new_date, old_date)
        self.assertEqual(revisions[1].new_date, line.date_planned)
        self.assertFalse(line.supplier_original_date_known)
        self.assertFalse(line.supplier_original_date)

    def test_uom_recomputation_is_recorded_as_technical(self):
        line = self.make_order_with_supplier_delay().order_line
        before, old_date = self.revisions(line), line.date_planned
        line.product_uom = self.env.ref("uom.product_uom_dozen")
        self.env.flush_all()
        self.assertNotEqual(line.date_planned, old_date)
        added = self.revisions(line) - before
        self.assertEqual(len(added), 1)
        self.assertEqual(added.revision_type, "technical")
        self.assertEqual(added.new_date, line.date_planned)
        self.assertEqual(line.supplier_postponement_count, 0)

    def test_rollback_reverts_persisted_recomputation_and_audit_together(self):
        line = self.make_order_with_supplier_delay().order_line
        before, old_date = self.revisions(line), line.date_planned
        with self.assertRaises(UserError), self.cr.savepoint():
            line.product_qty = 5
            self.env.flush_all()
            self.assertNotEqual(line.date_planned, old_date)
            self.assertEqual(len(self.revisions(line) - before), 1)
            raise UserError("Simulated transaction failure after recomputation")
        self.assertEqual(line.date_planned, old_date)
        self.assertEqual(self.revisions(line), before)
