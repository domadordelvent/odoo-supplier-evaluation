from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


_INPUT_FIELDS = {"revision_id", "justification", "supplier_attributable"}


class SupplierDeadlineConfirmation(models.Model):
    _name = "supplier.evaluation.deadline.confirmation"
    _description = "Confirmed supplier deadline renegotiation"
    _order = "id desc"
    _rec_name = "revision_id"
    _check_company_auto = True

    revision_id = fields.Many2one(
        "supplier.evaluation.deadline.revision", required=True, readonly=True,
        ondelete="restrict", index=True, check_company=True, copy=False,
        string="Deadline revision",
    )
    purchase_line_id = fields.Many2one(
        "purchase.order.line", required=True, readonly=True,
        ondelete="restrict", index=True, check_company=True, copy=False,
        string="Purchase line",
    )
    order_id = fields.Many2one(
        "purchase.order", required=True, readonly=True,
        ondelete="restrict", check_company=True, copy=False,
        string="Purchase order",
    )
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, ondelete="restrict", copy=False,
        string="Company",
    )
    supplier_id = fields.Many2one(
        "res.partner", required=True, readonly=True, ondelete="restrict", copy=False,
        string="Supplier",
    )
    previous_confirmation_id = fields.Many2one(
        "supplier.evaluation.deadline.confirmation", readonly=True,
        ondelete="restrict", check_company=True, copy=False,
        string="Previous agreement",
    )
    previous_agreed_date = fields.Datetime(required=True, readonly=True, copy=False, string="Previous accepted date")
    new_agreed_date = fields.Datetime(required=True, readonly=True, copy=False, string="New accepted date")
    confirmed_by_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", copy=False,
        string="Confirmed by",
    )
    confirmed_at = fields.Datetime(required=True, readonly=True, copy=False, string="Confirmation time")
    justification = fields.Text(required=True, readonly=True, copy=False, string="Justification")
    supplier_attributable = fields.Boolean(readonly=True, copy=False, string="Attributable to supplier")
    change_direction = fields.Selection(
        [("postponed", "Later deadline"), ("advanced", "Earlier deadline")],
        required=True, readonly=True, copy=False,
        string="Direction",
    )

    _sql_constraints = [
        ("revision_unique", "unique(revision_id)", "This revision has already been confirmed."),
        ("different_dates", "check(previous_agreed_date <> new_agreed_date)",
         "A renegotiation must change the accepted date."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # Check the actual user's group even when called with sudo(). No
        # context flag or direct create() bypasses manager authorisation.
        if not self.env.user.has_group("purchase.group_purchase_manager"):
            raise AccessError(_("Only Purchase managers can confirm renegotiations."))
        self.check_access("create")
        if any(
            f"default_{name}" in self.env.context
            for name in set(self._fields) - _INPUT_FIELDS
        ):
            raise AccessError(_("The server sets the historical confirmation data."))

        revision_ids = []
        inputs = []
        for vals in vals_list:
            if set(vals) - _INPUT_FIELDS:
                raise AccessError(_("The server sets the historical confirmation data."))
            revision_id = vals.get("revision_id")
            if type(revision_id) is not int or revision_id <= 0:
                raise ValidationError(_("Select a saved revision."))
            reason = vals.get("justification")
            if not isinstance(reason, str) or not reason.strip():
                raise ValidationError(_("Provide a justification for the renegotiation agreement."))
            if type(vals.get("supplier_attributable")) is not bool:
                raise ValidationError(_("Explicitly indicate whether the change is attributable to the supplier."))
            revision_ids.append(revision_id)
            inputs.append((revision_id, reason.strip(), vals["supplier_attributable"]))
        if len(set(revision_ids)) != len(revision_ids):
            raise ValidationError(_("The same revision cannot be confirmed twice."))
        if not revision_ids:
            return super().create([])

        Revision = self.env["supplier.evaluation.deadline.revision"]
        revisions = Revision.browse(revision_ids).exists()
        if len(revisions) != len(revision_ids):
            raise ValidationError(_("The selected revision does not exist."))
        revisions.check_access("read")
        for revision in revisions:
            company = revision.company_id
            if company not in self.env.user.company_ids or company not in self.env.companies:
                raise AccessError(_("You cannot confirm agreements for this company."))
        lines = revisions.purchase_line_id
        lines.check_access("write")
        # Flush pending computations and serialize with date edits/receipts.
        # A newly generated revision makes the selected old one stale.
        lines._supplier_lock_deadlines()

        prepared = []
        for revision_id, reason, attributable in inputs:
            revision = Revision.browse(revision_id)
            values = self._prepare_confirmation_values(revision)
            values.update({
                "confirmed_by_id": self.env.uid, "confirmed_at": fields.Datetime.now(),
                "justification": reason, "supplier_attributable": attributable,
            })
            prepared.append(values)
        # SQL uniqueness remains the final guard against concurrent duplicates.
        return super().create(prepared)

    @api.model
    def _get_confirmation_preview(self, revision):
        """Validate a preview without creating a confirmation or changing history."""
        if not self.env.user.has_group("purchase.group_purchase_manager"):
            raise AccessError(_("Only Purchase managers can confirm renegotiations."))
        self.check_access("create")
        revision.ensure_one()
        if not revision.exists():
            raise ValidationError(_("The selected revision does not exist."))
        revision.check_access("read")
        company = revision.company_id
        if company not in self.env.user.company_ids or company not in self.env.companies:
            raise AccessError(_("You cannot confirm agreements for this company."))
        revision.purchase_line_id.check_access("write")
        revision.purchase_line_id._supplier_lock_deadlines()
        return self._prepare_confirmation_values(revision)

    @api.model
    def _prepare_confirmation_values(self, revision):
        """Shared eligibility checks. Caller has checked access and locked the line."""
        Revision = self.env["supplier.evaluation.deadline.revision"]
        line = revision.purchase_line_id
        if self.sudo().search_count([("revision_id", "=", revision.id)]):
            raise ValidationError(_("This revision has already been confirmed."))
        if line.order_id.state not in ("purchase", "done") or line.display_type:
            raise ValidationError(_("Agreements can only be confirmed for approved purchase lines."))
        if (
            revision.revision_type != "technical"
            or revision.change_source != "unverified"
            or not revision.previous_date or not revision.new_date
            or revision.previous_date == revision.new_date
            or revision.change_direction not in ("postponed", "advanced")
        ):
            raise ValidationError(_("This revision does not represent a deadline change eligible for confirmation."))
        latest = Revision.search([("purchase_line_id", "=", line.id)], limit=1)
        if latest != revision or line.date_planned != revision.new_date:
            raise ValidationError(_("The deadline has changed; review the latest current revision."))
        if (
            revision.order_id != line.order_id
            or revision.company_id != line.company_id
            or revision.supplier_id != line.order_id.partner_id
        ):
            raise ValidationError(_("The revision no longer matches the current order and supplier."))

        previous = self.sudo().search([("purchase_line_id", "=", line.id)], limit=1)
        if previous:
            accepted_supplier = previous.supplier_id
        else:
            baseline = Revision.search([
                ("purchase_line_id", "=", line.id), ("revision_type", "=", "initial"),
            ], order="sequence, id", limit=1)
            accepted_supplier = baseline.supplier_id
        if accepted_supplier != revision.supplier_id:
            raise ValidationError(_("No verified previous agreement is recorded for this supplier."))
        previous_date = previous.new_agreed_date if previous else (
            line.supplier_original_date if line.supplier_original_date_known else False
        )
        if not previous_date:
            raise ValidationError(_("No previous accepted date is known; a historical agreement cannot be invented."))
        if previous and previous.revision_id.sequence >= revision.sequence:
            raise ValidationError(_("The revision predates the latest confirmed agreement."))
        if previous_date == revision.new_date:
            raise ValidationError(_("The new date matches the latest accepted date."))
        return {
            "revision_id": revision.id,
            "purchase_line_id": line.id, "order_id": line.order_id.id,
            "company_id": revision.company_id.id, "supplier_id": revision.supplier_id.id,
            "previous_confirmation_id": previous.id or False,
            "previous_agreed_date": previous_date, "new_agreed_date": revision.new_date,
            "change_direction": "postponed" if revision.new_date > previous_date else "advanced",
        }

    def write(self, vals):
        raise AccessError(_("Renegotiation confirmations are immutable."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_uninstall(self):
        raise UserError(_("Renegotiation confirmations cannot be deleted."))

    def copy(self, default=None):
        raise UserError(_("Renegotiation confirmations cannot be duplicated."))
