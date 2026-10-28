from odoo import api, fields, models
from odoo import _
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare


_EVALUATION_FIELDS = {"supplier_punctuality", "supplier_evaluation_captured_at"}


class StockPicking(models.Model):
    _inherit = "stock.picking"

    supplier_punctuality = fields.Selection(
        selection=[("on_time", "Puntual"), ("late", "Amb retard")],
        string="Puntualitat del proveïdor",
        readonly=True, copy=False,
        help="Resultat immutable segons els acords previs a la validació; tolerància de 24 hores.",
    )
    supplier_evaluation_captured_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(_EVALUATION_FIELDS.intersection(vals) for vals in vals_list):
            raise AccessError(_("L'avaluació només es pot crear en validar la recepció."))
        return super().create(vals_list)

    def write(self, vals):
        if _EVALUATION_FIELDS.intersection(vals):
            raise AccessError(_("La classificació de la recepció és immutable."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_supplier_evaluation(self):
        if self.filtered("supplier_evaluation_captured_at"):
            raise UserError(_("No es poden eliminar recepcions amb avaluacions històriques."))

    def _action_done(self):
        self.check_access("write")
        if self:
            self.flush_recordset(["state", "supplier_evaluation_captured_at"])
            self.env.cr.execute(
                "SELECT id FROM stock_picking WHERE id IN %s ORDER BY id FOR UPDATE",
                [tuple(sorted(self.ids))],
            )
            self.invalidate_recordset(["state", "supplier_evaluation_captured_at"])
        # Never backfill legacy done receipts or revalidate an existing one.
        pending = self.filtered(lambda picking: picking.state not in ("done", "cancel"))
        candidates = pending.filtered(
            lambda picking: not picking.supplier_evaluation_captured_at
            and picking.picking_type_id.code == "incoming"
            and picking.location_id.usage == "supplier" and picking.partner_id
        )
        # Stock users can validate without purchase CRUD rights. Only this
        # private, locked audit operation reads the purchase agreement as sudo.
        lines = candidates.move_ids.purchase_line_id.sudo()
        lines._supplier_lock_deadlines()
        lines._supplier_ensure_history()
        agreements = {}
        for line in lines:
            revision = self.env["supplier.evaluation.deadline.revision"].sudo().search(
                [("purchase_line_id", "=", line.id)], limit=1,
            )
            agreements[line.id] = (
                line.supplier_original_date if line.supplier_original_date_known else False,
                line.date_planned, revision.id or False,
            )
        # Stock splits moves here: match completed moves by purchase line,
        # not pre-validation move IDs. Backorders retain empty captures.
        result = super(StockPicking, pending)._action_done() if pending else True
        captured_at = fields.Datetime.now()
        for picking in candidates.filtered(lambda record: record.state == "done"):
            received = picking.move_ids.filtered(
                lambda move: move.state == "done" and not move.scrapped
                and float_compare(move.quantity, 0, precision_rounding=move.product_uom.rounding) > 0
            )
            for move in received:
                if move.purchase_line_id and move.purchase_line_id.id not in agreements:
                    raise UserError(_("La validació ha afegit una línia de compra sense acord capturat."))
                move._supplier_capture_deadline(
                    agreements.get(move.purchase_line_id.id, (False, False, False)),
                    picking.date_done, captured_at,
                )
            statuses = received.mapped("supplier_punctuality")
            status = "late" if "late" in statuses else (
                "on_time" if statuses and all(value == "on_time" for value in statuses) else False
            )
            super(StockPicking, picking.sudo()).write({
                "supplier_punctuality": status,
                "supplier_evaluation_captured_at": captured_at,
            })
        return result
