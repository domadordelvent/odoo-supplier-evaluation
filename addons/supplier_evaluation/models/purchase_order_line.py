from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


_ORIGINAL_FIELDS = {
    "supplier_original_date", "supplier_original_date_known",
    "supplier_original_date_pending", "supplier_deadline_revision_ids",
    "supplier_postponement_count",
    "supplier_deadline_confirmation_ids",
}


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    supplier_original_date = fields.Datetime(readonly=True, copy=False)
    supplier_original_date_known = fields.Boolean(readonly=True, copy=False)
    # No True default: rows predating the upgrade must keep an unknown origin.
    supplier_original_date_pending = fields.Boolean(readonly=True, copy=False)
    supplier_deadline_revision_ids = fields.One2many(
        "supplier.evaluation.deadline.revision", "purchase_line_id", readonly=True, copy=False,
    )
    supplier_postponement_count = fields.Integer(
        compute="_compute_supplier_postponement_count", compute_sudo=True,
    )
    supplier_deadline_confirmation_ids = fields.One2many(
        "supplier.evaluation.deadline.confirmation", "purchase_line_id",
        readonly=True, copy=False,
    )

    @api.depends("supplier_deadline_revision_ids.revision_type")
    def _compute_supplier_postponement_count(self):
        for line in self:
            line.supplier_postponement_count = len(
                line.supplier_deadline_revision_ids.filtered(
                    lambda revision: revision.revision_type == "postponement"
                )
            )

    def action_open_supplier_deadline_history(self):
        self.ensure_one()
        if not isinstance(self.id, int):
            raise UserError(_("Cal desar una línia de producte abans de consultar-ne els terminis."))
        self.check_access("read")
        if self.display_type:
            raise UserError(_("Cal desar una línia de producte abans de consultar-ne els terminis."))
        action = self.env["ir.actions.actions"]._for_xml_id("supplier_evaluation.action_deadline_revisions")
        action["domain"] = [("purchase_line_id", "=", self.id)]
        return action

    def _supplier_lock_deadlines(self):
        """Serialize approval, date edits and receipts in a stable row order.

        A concurrent stale row version raises PostgreSQL SerializationFailure
        under Odoo's REPEATABLE READ; the request retry re-reads the agreement.
        """
        if not self:
            return
        orders = self.order_id.sorted("id")
        orders._supplier_lock_orders()
        self.flush_recordset(["date_planned", "supplier_original_date",
                             "supplier_original_date_known", "supplier_original_date_pending"])
        self.env.cr.execute(
            "SELECT id FROM purchase_order_line WHERE id IN %s ORDER BY id FOR UPDATE",
            [tuple(sorted(self.ids))],
        )
        self.invalidate_recordset([
            "date_planned", "supplier_original_date", "supplier_original_date_known",
            "supplier_original_date_pending", "supplier_deadline_revision_ids",
        ])
        orders.invalidate_recordset(["state"])

    def _supplier_ensure_history(self):
        """Initialize once; existing rows retain an explicitly unknown origin."""
        Revision = self.env["supplier.evaluation.deadline.revision"]
        for line in self.filtered(lambda record: not record.display_type):
            if Revision.sudo().search([("purchase_line_id", "=", line.id)], limit=1):
                continue
            known = bool(
                line.supplier_original_date_pending and line.date_planned
                and line.order_id.state in ("purchase", "done")
            )
            super(PurchaseOrderLine, line.sudo()).write({
                "supplier_original_date": line.date_planned if known else False,
                "supplier_original_date_known": known,
                "supplier_original_date_pending": False,
            })
            Revision._append_revision(
                line, False, line.date_planned, "initial" if known else "unknown_initial",
            )

    @api.model_create_multi
    def create(self, vals_list):
        if any(_ORIGINAL_FIELDS.intersection(vals) for vals in vals_list) or any(
            f"default_{name}" in self.env.context for name in _ORIGINAL_FIELDS
        ):
            raise AccessError(_("Els compromisos originals els gestiona el mòdul."))
        # Serialize line insertion with approval, including context defaults.
        order_ids = {
            vals.get("order_id", self.env.context.get("default_order_id"))
            for vals in vals_list
        } - {None, False}
        self.env["purchase.order"].browse(sorted(order_ids))._supplier_lock_orders()
        # Set this in the INSERT, before any post-create stored recomputation.
        # Old rows keep False. While True, dates are still being initialized,
        # not revisions of an already established supplier commitment.
        lines = super().create([
            dict(vals, supplier_original_date_pending=not bool(vals.get("display_type")))
            for vals in vals_list
        ])
        committed = lines.filtered(lambda line: line.order_id.state in ("purchase", "done"))
        committed._supplier_lock_deadlines()
        committed._supplier_ensure_history()
        return lines

    def write(self, vals):
        if _ORIGINAL_FIELDS.intersection(vals):
            raise AccessError(_("El compromís original i l'historial estan protegits."))
        if {"order_id", "company_id"}.intersection(vals):
            for line in self:
                if line.sudo().supplier_deadline_revision_ids and any(
                    vals[field] != line[field].id
                    for field in ("order_id", "company_id") if field in vals
                ):
                    raise AccessError(_("No es pot traslladar una línia amb historial de terminis."))
        if "date_planned" not in vals:
            return super().write(vals)
        # new()/onchange records (including virtual records with _origin) must
        # never acquire SQL locks, initialize history, or emit audit events.
        if not all(isinstance(record.id, int) for record in self):
            return super().write(vals)
        self.check_access("write")
        self._supplier_lock_deadlines()
        result = super().write(vals)
        # Preserve individual explicit writes even when several occur before
        # the request's final flush. Only _write_multi emits change revisions.
        self.flush_recordset(["date_planned"])
        return result

    def _write_multi(self, vals_list):
        """Audit actual SQL date transitions, including stored recomputations.

        Odoo 18's _flush() uses _write_multi() with an empty context. Therefore
        neither context flags nor a direct edit prove a supplier renegotiation.
        Every non-baseline event here is technical/unverified. This method
        must not flush or invalidate date_planned: it is already being flushed.
        """
        date_ids = [
            record.id for record, vals in zip(self, vals_list)
            if isinstance(record.id, int) and "date_planned" in vals
        ]
        if not date_ids:
            return super()._write_multi(vals_list)
        # Read only persisted data here, never cached/onchange dates. Acquire
        # parent locks first, consistently with approval and receipt capture.
        self.env.cr.execute(
            "SELECT DISTINCT order_id FROM purchase_order_line WHERE id IN %s",
            [tuple(date_ids)],
        )
        order_ids = tuple(sorted(row[0] for row in self.env.cr.fetchall()))
        if order_ids:
            self.env.cr.execute(
                "SELECT id FROM purchase_order WHERE id IN %s ORDER BY id FOR UPDATE",
                [order_ids],
            )
        self.env.cr.execute(
            """SELECT line.id, line.date_planned, line.supplier_original_date_pending,
                      line.display_type, orders.state
                 FROM purchase_order_line AS line
                 JOIN purchase_order AS orders ON orders.id = line.order_id
                WHERE line.id IN %s ORDER BY line.id FOR UPDATE OF line""",
            [tuple(date_ids)],
        )
        before = {row[0]: row[1:] for row in self.env.cr.fetchall()}
        result = super()._write_multi(vals_list)
        self.env.cr.execute(
            "SELECT id, date_planned FROM purchase_order_line WHERE id IN %s ORDER BY id",
            [tuple(date_ids)],
        )
        after = dict(self.env.cr.fetchall())
        Revision = self.env["supplier.evaluation.deadline.revision"]
        for line_id, (old_date, pending, display_type, state) in before.items():
            new_date = after[line_id]
            if old_date == new_date or display_type:
                continue
            line = self.browse(line_id)
            latest = Revision.sudo().search([("purchase_line_id", "=", line_id)], limit=1)
            if not latest:
                # New lines are initialized by approval/create; pre-approval
                # computations must not manufacture an original commitment.
                if pending or state not in ("purchase", "done"):
                    continue
                # Legacy confirmed line: retain the observed old date as an
                # unknown baseline, never pretend it was the original promise.
                latest = Revision._append_revision(line, False, old_date, "unknown_initial")
            if latest.new_date != (new_date or False):
                Revision._append_revision(line, old_date, new_date, "technical")
        return result
