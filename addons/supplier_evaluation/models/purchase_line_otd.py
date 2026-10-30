"""One immutable OTD observation at the first full receipt of a purchase line."""
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare


_OTD_FIELDS = {
    "supplier_otd_status", "supplier_otd_deadline", "supplier_otd_completed_at",
    "supplier_otd_captured_at", "supplier_otd_confirmation_id",
    "supplier_otd_ordered_qty", "supplier_otd_received_qty", "supplier_otd_uom_id",
    "supplier_otd_supplier_id",
}


def classify_otd(deadline, completed_at):
    if not deadline or not completed_at:
        return "unknown"
    return "on_time" if completed_at <= deadline + timedelta(hours=24) else "late"


class PurchaseLineOTD(models.Model):
    _inherit = "purchase.order.line"

    supplier_otd_status = fields.Selection([
        ("on_time", "On time"), ("late", "Late"), ("unknown", "Unknown"),
    ], string="Completed-line OTD", readonly=True, copy=False,
        help="One observation per completed line; 24-hour tolerance. Empty: not yet evaluated.")
    supplier_otd_deadline = fields.Datetime(string="OTD deadline", readonly=True, copy=False)
    supplier_otd_completed_at = fields.Datetime(string="Delivery completed on", readonly=True, copy=False)
    supplier_otd_captured_at = fields.Datetime(readonly=True, copy=False, string="OTD captured on")
    supplier_otd_confirmation_id = fields.Many2one(
        "supplier.evaluation.deadline.confirmation", readonly=True, copy=False,
        ondelete="restrict", check_company=True,
        string="Applied agreement",
    )
    supplier_otd_ordered_qty = fields.Float(readonly=True, copy=False, digits="Product Unit of Measure", string="Captured ordered quantity")
    supplier_otd_received_qty = fields.Float(readonly=True, copy=False, digits="Product Unit of Measure", string="Captured received quantity")
    supplier_otd_uom_id = fields.Many2one("uom.uom", readonly=True, copy=False, ondelete="restrict", string="Captured unit of measure")
    supplier_otd_supplier_id = fields.Many2one("res.partner", readonly=True, copy=False, ondelete="restrict", string="Captured supplier")

    @api.model_create_multi
    def create(self, vals_list):
        if any(_OTD_FIELDS.intersection(vals) for vals in vals_list) or any(
            f"default_{name}" in self.env.context for name in _OTD_FIELDS
        ):
            raise AccessError(_("OTD can only be captured when completing a line."))
        return super().create(vals_list)

    def write(self, vals):
        if _OTD_FIELDS.intersection(vals):
            raise AccessError(_("The line OTD snapshot is immutable."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_supplier_otd(self):
        if self.filtered("supplier_otd_captured_at"):
            raise UserError(_("Lines with OTD snapshots cannot be deleted."))

    def _supplier_otd_is_eligible(self):
        self.ensure_one()
        return (
            not self.supplier_otd_captured_at and not self.display_type
            and self.order_id.state in ("purchase", "done")
            and self.qty_received_method == "stock_moves"
            and self.product_id.type != "service"
            and float_compare(self.product_qty, 0, precision_rounding=self.product_uom.rounding) > 0
        )

    def _supplier_otd_is_complete(self):
        self.ensure_one()
        return float_compare(
            self.qty_received, self.product_qty, precision_rounding=self.product_uom.rounding,
        ) >= 0

    def _supplier_otd_pending_lines(self):
        """Called under the purchase line locks, BEFORE stock validation."""
        # The caller may have read these before waiting for a concurrent receipt.
        # Flush local edits, then discard cached quantities/relations under lock.
        self.invalidate_recordset([
            "qty_received", "move_ids", "product_qty", "product_uom", "product_id",
            "supplier_otd_captured_at",
        ])
        return self.filtered(
            lambda line: line._supplier_otd_is_eligible() and not line._supplier_otd_is_complete()
        )

    def _supplier_otd_confirmation_limits(self):
        """Record confirmations already present before stock validation.

        Datetimes have second precision. A prior agreement in the same second
        is valid; one created after receipt must never become eligible.
        Caller holds the line locks shared with confirmation creation.
        """
        limits = {}
        for line in self:
            last = self.env["supplier.evaluation.deadline.confirmation"].sudo().search([
                ("purchase_line_id", "=", line.id),
            ], order="id desc", limit=1)
            limits[line.id] = last.id if last else 0
        return limits

    def _supplier_otd_agreement(self, completed_at, confirmation_limit):
        """Never consult date_planned; a later confirmation cannot rewrite OTD."""
        self.ensure_one()
        if not completed_at:
            return False, False
        confirmation = self.env["supplier.evaluation.deadline.confirmation"].sudo().search([
            ("purchase_line_id", "=", self.id),
            ("supplier_id", "=", self.order_id.partner_id.id),
            ("confirmed_at", "<=", completed_at),
            ("id", "<=", confirmation_limit),
        ], order="confirmed_at desc, id desc", limit=1)
        if confirmation:
            return confirmation.new_agreed_date, confirmation.id
        baseline = self.env["supplier.evaluation.deadline.revision"].sudo().search([
            ("purchase_line_id", "=", self.id), ("revision_type", "=", "initial"),
        ], order="sequence, id", limit=1)
        if self.supplier_original_date_known and baseline.supplier_id == self.order_id.partner_id:
            return self.supplier_original_date, False
        return False, False

    def _supplier_capture_otd(self, confirmation_limits):
        """Capture only lines that were incomplete before this validation.

        Caller holds the same line locks used by confirmation creation. Native
        qty_received includes Odoo's return handling and UoM conversion. Later
        returns/quantity edits never replace this first-completion observation.
        """
        for line in self:
            if not line._supplier_otd_is_eligible() or not line._supplier_otd_is_complete():
                continue
            receipts = line.with_context(accrual_entry_date=False)._get_po_line_moves().filtered(
                lambda move: move.state == "done" and not move.scrapped
                and move.location_id.usage == "supplier"
                and move.location_dest_id.usage != "supplier"
                and float_compare(move.quantity, 0, precision_rounding=move.product_uom.rounding) > 0
            )
            # Never infer old receipt dates from mutable move.date/date_done.
            known = bool(receipts) and all(
                move.supplier_deadline_captured_at and move.supplier_receipt_date_snapshot
                and move.picking_id.partner_id == line.order_id.partner_id
                for move in receipts
            )
            completed_at = max(receipts.mapped("supplier_receipt_date_snapshot")) if known else False
            deadline, confirmation_id = line._supplier_otd_agreement(
                completed_at, confirmation_limits[line.id],
            )
            super(PurchaseLineOTD, line.sudo()).write({
                "supplier_otd_status": classify_otd(deadline, completed_at),
                "supplier_otd_deadline": deadline,
                "supplier_otd_completed_at": completed_at,
                "supplier_otd_captured_at": fields.Datetime.now(),
                "supplier_otd_confirmation_id": confirmation_id,
                "supplier_otd_ordered_qty": line.product_qty,
                "supplier_otd_received_qty": line.qty_received,
                "supplier_otd_uom_id": line.product_uom.id,
                "supplier_otd_supplier_id": line.order_id.partner_id.id,
            })
