from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class SupplierDeadlineRevision(models.Model):
    _name = "supplier.evaluation.deadline.revision"
    _description = "Supplier deadline revision"
    _order = "sequence desc, id desc"
    _rec_name = "order_reference"
    _check_company_auto = True

    purchase_line_id = fields.Many2one(
        "purchase.order.line", required=True, readonly=True,
        ondelete="restrict", index=True, check_company=True,
        string="Purchase line",
    )
    order_id = fields.Many2one(
        "purchase.order", required=True, readonly=True,
        ondelete="restrict", check_company=True,
        string="Purchase order",
    )
    company_id = fields.Many2one("res.company", required=True, readonly=True, ondelete="restrict", string="Company")
    supplier_id = fields.Many2one("res.partner", required=True, readonly=True, ondelete="restrict", string="Supplier")
    sequence = fields.Integer(required=True, readonly=True, string="Revision number")
    previous_date = fields.Datetime(readonly=True, string="Previous planned date")
    new_date = fields.Datetime(readonly=True, string="New planned date")
    changed_at = fields.Datetime(required=True, readonly=True, string="Change time")
    changed_by_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict", string="Changed by")
    revision_type = fields.Selection([
        ("initial", "Original commitment"), ("postponement", "Postponement"),
        ("advance", "Advance"), ("unknown_initial", "Initialization without history"),
        ("date_set", "Date set"), ("date_removed", "Date removed"),
        ("technical", "Technical change without a verified renegotiation"),
    ], required=True, readonly=True, string="Revision type")
    change_source = fields.Selection([
        ("baseline", "Tracking initialization"),
        ("unverified", "ORM persistence; unverified origin"),
    ], required=True, readonly=True, string="Change source")
    change_direction = fields.Selection([
        ("set", "Date set"), ("removed", "Date removed"),
        ("postponed", "Later deadline"), ("advanced", "Earlier deadline"),
        ("unchanged", "Unchanged"),
    ], required=True, readonly=True, string="Direction")
    order_reference = fields.Char(required=True, readonly=True, string="Order reference")
    line_description = fields.Text(readonly=True, string="Line description")
    supplier_name = fields.Char(readonly=True, string="Supplier name")
    confirmation_ids = fields.One2many(
        "supplier.evaluation.deadline.confirmation", "revision_id",
        readonly=True, copy=False,
        string="Recorded confirmations",
    )

    _sql_constraints = [
        ("line_sequence_unique", "unique(purchase_line_id, sequence)",
         "The revision must be unique per purchase line."),
        ("positive_sequence", "check(sequence > 0)", "The revision must be positive."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_("Revisions can only be created by deadline tracking."))

    def write(self, vals):
        raise AccessError(_("Deadline revisions are immutable."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_uninstall(self):
        raise UserError(_("Deadline history cannot be deleted."))

    def action_open_renegotiation_wizard(self):
        if not self.env.user.has_group("purchase.group_purchase_manager"):
            raise AccessError(_("Only Purchase managers can confirm renegotiations."))
        self.ensure_one()
        self.env["supplier.evaluation.deadline.confirmation"]._get_confirmation_preview(self)
        # Parent purchase views may carry defaults for other models. They must
        # not populate audit or preview fields in the transient form.
        context = {key: value for key, value in self.env.context.items() if not key.startswith("default_")}
        wizard = self.env["supplier.evaluation.deadline.renegotiation.wizard"].with_context(context).create({
            "revision_id": self.id,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Confirm deadline renegotiation"),
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(self.env.ref("supplier_evaluation.view_deadline_renegotiation_wizard_form").id, "form")],
            "target": "new",
            "context": context,
        }

    def action_confirm_renegotiation(self, justification, supplier_attributable):
        """Explicit manager action; never called by automatic date tracking."""
        if not self.env.user.has_group("purchase.group_purchase_manager"):
            raise AccessError(_("Only Purchase managers can confirm renegotiations."))
        self.ensure_one()
        self.check_access("read")
        confirmation = self.env["supplier.evaluation.deadline.confirmation"].create({
            "revision_id": self.id,
            "justification": justification,
            "supplier_attributable": supplier_attributable,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Confirmed renegotiation"),
            "res_model": confirmation._name,
            "res_id": confirmation.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def _append_revision(self, line, previous_date, new_date, revision_type):
        """Private entry point; caller holds order/line row locks.

        sudo records events for warehouse users without granting audit CRUD.
        The actor remains the calling user. No context bypass is exposed.
        """
        line.ensure_one()
        latest = self.sudo().search([("purchase_line_id", "=", line.id)], limit=1)
        direction = (
            "unchanged" if previous_date == new_date
            else "set" if not previous_date
            else "removed" if not new_date
            else "postponed" if new_date > previous_date else "advanced"
        )
        return super(SupplierDeadlineRevision, self.sudo()).create({
            "purchase_line_id": line.id, "order_id": line.order_id.id,
            "company_id": line.company_id.id, "supplier_id": line.order_id.partner_id.id,
            "sequence": (latest.sequence or 0) + 1,
            "previous_date": previous_date, "new_date": new_date,
            "changed_at": fields.Datetime.now(), "changed_by_id": self.env.uid,
            "revision_type": revision_type, "order_reference": line.order_id.name,
            "change_source": "baseline" if revision_type in ("initial", "unknown_initial") else "unverified",
            "change_direction": direction,
            "line_description": line.name, "supplier_name": line.order_id.partner_id.display_name,
        })
