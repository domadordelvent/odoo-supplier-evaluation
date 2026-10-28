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
    )
    order_id = fields.Many2one(
        "purchase.order", required=True, readonly=True,
        ondelete="restrict", check_company=True,
    )
    company_id = fields.Many2one("res.company", required=True, readonly=True, ondelete="restrict")
    supplier_id = fields.Many2one("res.partner", required=True, readonly=True, ondelete="restrict")
    sequence = fields.Integer(required=True, readonly=True)
    previous_date = fields.Datetime(readonly=True)
    new_date = fields.Datetime(readonly=True)
    changed_at = fields.Datetime(required=True, readonly=True)
    changed_by_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    revision_type = fields.Selection([
        ("initial", "Compromís inicial"), ("postponement", "Ajornament"),
        ("advance", "Avançament"), ("unknown_initial", "Inicialització sense historial"),
        ("date_set", "Data informada"), ("date_removed", "Data retirada"),
        ("technical", "Canvi tècnic, sense renegociació acreditada"),
    ], required=True, readonly=True)
    change_source = fields.Selection([
        ("baseline", "Inicialització del seguiment"),
        ("unverified", "Persistència ORM; origen no verificat"),
    ], required=True, readonly=True)
    change_direction = fields.Selection([
        ("set", "Data informada"), ("removed", "Data retirada"),
        ("postponed", "Termini posterior"), ("advanced", "Termini anterior"),
        ("unchanged", "Sense canvi"),
    ], required=True, readonly=True)
    order_reference = fields.Char(required=True, readonly=True)
    line_description = fields.Text(readonly=True)
    supplier_name = fields.Char(readonly=True)
    confirmation_ids = fields.One2many(
        "supplier.evaluation.deadline.confirmation", "revision_id",
        readonly=True, copy=False,
    )

    _sql_constraints = [
        ("line_sequence_unique", "unique(purchase_line_id, sequence)",
         "La revisió ha de ser única per línia de compra."),
        ("positive_sequence", "check(sequence > 0)", "La revisió ha de ser positiva."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_("Les revisions només es poden crear des del seguiment de terminis."))

    def write(self, vals):
        raise AccessError(_("Les revisions de termini són immutables."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_uninstall(self):
        raise UserError(_("No es pot eliminar l'historial de terminis."))

    def action_open_renegotiation_wizard(self):
        if not self.env.user.has_group("purchase.group_purchase_manager"):
            raise AccessError(_("Només els responsables de compres poden confirmar renegociacions."))
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
            "name": _("Confirmar renegociació de termini"),
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
            raise AccessError(_("Només els responsables de compres poden confirmar renegociacions."))
        self.ensure_one()
        self.check_access("read")
        confirmation = self.env["supplier.evaluation.deadline.confirmation"].create({
            "revision_id": self.id,
            "justification": justification,
            "supplier_attributable": supplier_attributable,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Renegociació confirmada"),
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
