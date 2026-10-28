from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


_WIZARD_INPUTS = {"revision_id", "justification", "supplier_attributable"}


class SupplierDeadlineRenegotiationWizard(models.TransientModel):
    _name = "supplier.evaluation.deadline.renegotiation.wizard"
    _description = "Confirm supplier deadline renegotiation"
    _check_company_auto = True

    revision_id = fields.Many2one(
        "supplier.evaluation.deadline.revision", required=True, readonly=True,
        ondelete="cascade", check_company=True,
    )
    company_id = fields.Many2one(related="revision_id.company_id", store=True, readonly=True)
    order_id = fields.Many2one(related="revision_id.order_id", readonly=True)
    purchase_line_id = fields.Many2one(related="revision_id.purchase_line_id", readonly=True)
    previous_agreed_date = fields.Datetime(compute="_compute_dates", compute_sudo=False)
    new_agreed_date = fields.Datetime(compute="_compute_dates", compute_sudo=False)
    original_date = fields.Datetime(compute="_compute_dates", compute_sudo=False)
    original_date_known = fields.Boolean(compute="_compute_dates", compute_sudo=False)
    justification = fields.Text(string="Justificació de l'acord")
    # No default: require a deliberate yes/no choice instead of silently
    # treating an untouched checkbox as an explicit attribution decision.
    supplier_attributable = fields.Selection(
        [("yes", "Sí, atribuïble al proveïdor"), ("no", "No, no atribuïble al proveïdor")],
        string="Atribució del canvi",
    )

    def _check_manager(self):
        if not self.env.user.has_group("purchase.group_purchase_manager"):
            raise AccessError(_("Només els responsables de compres poden confirmar renegociacions."))

    @api.depends("revision_id")
    def _compute_dates(self):
        self._check_manager()
        for wizard in self:
            wizard.previous_agreed_date = False
            wizard.new_agreed_date = False
            wizard.original_date = False
            wizard.original_date_known = False
            if wizard.revision_id:
                preview = self.env["supplier.evaluation.deadline.confirmation"]._get_confirmation_preview(wizard.revision_id)
                line = wizard.revision_id.purchase_line_id
                wizard.previous_agreed_date = preview["previous_agreed_date"]
                wizard.new_agreed_date = preview["new_agreed_date"]
                wizard.original_date_known = line.supplier_original_date_known
                wizard.original_date = line.supplier_original_date if line.supplier_original_date_known else False

    @api.model_create_multi
    def create(self, vals_list):
        self._check_manager()
        if any(set(vals) - _WIZARD_INPUTS for vals in vals_list) or any(
            f"default_{name}" in self.env.context for name in set(self._fields) - _WIZARD_INPUTS
        ):
            raise AccessError(_("Les dates i les relacions de l'assistent les fixa el servidor."))
        return super().create(vals_list)

    def write(self, vals):
        self._check_manager()
        if set(vals) - _WIZARD_INPUTS:
            raise AccessError(_("Les dates i les relacions de l'assistent les fixa el servidor."))
        if "revision_id" in vals and any(wizard.revision_id.id != vals["revision_id"] for wizard in self):
            raise UserError(_("Cal obrir un altre assistent per canviar la revisió seleccionada."))
        return super().write(vals)

    def action_confirm(self):
        self._check_manager()
        self.ensure_one()
        self.check_access("write")
        if self.supplier_attributable not in ("yes", "no"):
            raise ValidationError(_("Cal indicar explícitament si el canvi és atribuïble al proveïdor."))
        context = {key: value for key, value in self.env.context.items() if not key.startswith("default_")}
        # This action invokes the unchanged persistent model create path:
        # current agreement, company, permission and duplicate checks run again.
        return self.revision_id.with_context(context).action_confirm_renegotiation(
            self.justification, self.supplier_attributable == "yes",
        )
