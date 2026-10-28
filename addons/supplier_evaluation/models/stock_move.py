from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


_CAPTURE_FIELDS = {
    "supplier_original_date_snapshot", "supplier_agreed_date_snapshot",
    "supplier_deadline_revision_id", "supplier_receipt_date_snapshot",
    "supplier_deadline_captured_at", "supplier_punctuality",
}


class StockMove(models.Model):
    _inherit = "stock.move"

    supplier_original_date_snapshot = fields.Datetime(readonly=True, copy=False)
    supplier_agreed_date_snapshot = fields.Datetime(readonly=True, copy=False)
    supplier_deadline_revision_id = fields.Many2one(
        "supplier.evaluation.deadline.revision", readonly=True, copy=False,
        ondelete="restrict", check_company=True,
    )
    supplier_receipt_date_snapshot = fields.Datetime(readonly=True, copy=False)
    supplier_deadline_captured_at = fields.Datetime(readonly=True, copy=False)
    supplier_punctuality = fields.Selection(
        [("on_time", "Puntual"), ("late", "Amb retard")],
        compute="_compute_supplier_punctuality", store=True, copy=False,
    )

    @api.depends("supplier_agreed_date_snapshot", "supplier_receipt_date_snapshot")
    def _compute_supplier_punctuality(self):
        for move in self:
            agreed = move.supplier_agreed_date_snapshot
            received = move.supplier_receipt_date_snapshot
            move.supplier_punctuality = (
                "on_time" if received <= agreed + timedelta(hours=24) else "late"
            ) if agreed and received else False

    @api.model_create_multi
    def create(self, vals_list):
        if any(_CAPTURE_FIELDS.intersection(vals) for vals in vals_list):
            raise AccessError(_("Les captures només es poden crear en validar la recepció."))
        return super().create(vals_list)

    def write(self, vals):
        if _CAPTURE_FIELDS.intersection(vals):
            raise AccessError(_("Les captures de recepció són immutables."))
        if {"purchase_line_id", "picking_id"}.intersection(vals):
            for move in self.filtered("supplier_deadline_captured_at"):
                if any(vals[field] != move[field].id for field in ("purchase_line_id", "picking_id") if field in vals):
                    raise UserError(_("No es pot canviar l'origen d'una captura històrica."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_supplier_capture(self):
        if self.filtered("supplier_deadline_captured_at"):
            raise UserError(_("No es poden eliminar moviments amb captures històriques."))

    def _supplier_capture_deadline(self, agreement, received_at, captured_at):
        self.ensure_one()
        if self.supplier_deadline_captured_at:
            return
        original, agreed, revision_id = agreement
        super(StockMove, self.sudo()).write({
            "supplier_original_date_snapshot": original,
            "supplier_agreed_date_snapshot": agreed,
            "supplier_deadline_revision_id": revision_id,
            "supplier_receipt_date_snapshot": received_at,
            "supplier_deadline_captured_at": captured_at,
        })
