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
    )
    purchase_line_id = fields.Many2one(
        "purchase.order.line", required=True, readonly=True,
        ondelete="restrict", index=True, check_company=True, copy=False,
    )
    order_id = fields.Many2one(
        "purchase.order", required=True, readonly=True,
        ondelete="restrict", check_company=True, copy=False,
    )
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, ondelete="restrict", copy=False,
    )
    supplier_id = fields.Many2one(
        "res.partner", required=True, readonly=True, ondelete="restrict", copy=False,
    )
    previous_confirmation_id = fields.Many2one(
        "supplier.evaluation.deadline.confirmation", readonly=True,
        ondelete="restrict", check_company=True, copy=False,
    )
    previous_agreed_date = fields.Datetime(required=True, readonly=True, copy=False)
    new_agreed_date = fields.Datetime(required=True, readonly=True, copy=False)
    confirmed_by_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", copy=False,
    )
    confirmed_at = fields.Datetime(required=True, readonly=True, copy=False)
    justification = fields.Text(required=True, readonly=True, copy=False)
    supplier_attributable = fields.Boolean(readonly=True, copy=False)
    change_direction = fields.Selection(
        [("postponed", "Termini posterior"), ("advanced", "Termini anterior")],
        required=True, readonly=True, copy=False,
    )

    _sql_constraints = [
        ("revision_unique", "unique(revision_id)", "Aquesta revisió ja està confirmada."),
        ("different_dates", "check(previous_agreed_date <> new_agreed_date)",
         "Una renegociació ha de canviar la data acceptada."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # Check the actual user's group even when called with sudo(). No
        # context flag or direct create() bypasses manager authorisation.
        if not self.env.user.has_group("purchase.group_purchase_manager"):
            raise AccessError(_("Només els responsables de compres poden confirmar renegociacions."))
        self.check_access("create")
        if any(
            f"default_{name}" in self.env.context
            for name in set(self._fields) - _INPUT_FIELDS
        ):
            raise AccessError(_("Les dades històriques de la confirmació les fixa el servidor."))

        revision_ids = []
        inputs = []
        for vals in vals_list:
            if set(vals) - _INPUT_FIELDS:
                raise AccessError(_("Les dades històriques de la confirmació les fixa el servidor."))
            revision_id = vals.get("revision_id")
            if type(revision_id) is not int or revision_id <= 0:
                raise ValidationError(_("Cal seleccionar una revisió desada."))
            reason = vals.get("justification")
            if not isinstance(reason, str) or not reason.strip():
                raise ValidationError(_("Cal justificar l'acord de renegociació."))
            if type(vals.get("supplier_attributable")) is not bool:
                raise ValidationError(_("Cal indicar explícitament si el canvi és atribuïble al proveïdor."))
            revision_ids.append(revision_id)
            inputs.append((revision_id, reason.strip(), vals["supplier_attributable"]))
        if len(set(revision_ids)) != len(revision_ids):
            raise ValidationError(_("No es pot confirmar dues vegades la mateixa revisió."))
        if not revision_ids:
            return super().create([])

        Revision = self.env["supplier.evaluation.deadline.revision"]
        revisions = Revision.browse(revision_ids).exists()
        if len(revisions) != len(revision_ids):
            raise ValidationError(_("La revisió seleccionada no existeix."))
        revisions.check_access("read")
        for revision in revisions:
            company = revision.company_id
            if company not in self.env.user.company_ids or company not in self.env.companies:
                raise AccessError(_("No podeu confirmar acords d'aquesta empresa."))
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
            raise AccessError(_("Només els responsables de compres poden confirmar renegociacions."))
        self.check_access("create")
        revision.ensure_one()
        if not revision.exists():
            raise ValidationError(_("La revisió seleccionada no existeix."))
        revision.check_access("read")
        company = revision.company_id
        if company not in self.env.user.company_ids or company not in self.env.companies:
            raise AccessError(_("No podeu confirmar acords d'aquesta empresa."))
        revision.purchase_line_id.check_access("write")
        revision.purchase_line_id._supplier_lock_deadlines()
        return self._prepare_confirmation_values(revision)

    @api.model
    def _prepare_confirmation_values(self, revision):
        """Shared eligibility checks. Caller has checked access and locked the line."""
        Revision = self.env["supplier.evaluation.deadline.revision"]
        line = revision.purchase_line_id
        if self.sudo().search_count([("revision_id", "=", revision.id)]):
            raise ValidationError(_("Aquesta revisió ja està confirmada."))
        if line.order_id.state not in ("purchase", "done") or line.display_type:
            raise ValidationError(_("Només es poden confirmar acords de línies de compra aprovades."))
        if (
            revision.revision_type != "technical"
            or revision.change_source != "unverified"
            or not revision.previous_date or not revision.new_date
            or revision.previous_date == revision.new_date
            or revision.change_direction not in ("postponed", "advanced")
        ):
            raise ValidationError(_("La revisió no representa un canvi de termini confirmable."))
        latest = Revision.search([("purchase_line_id", "=", line.id)], limit=1)
        if latest != revision or line.date_planned != revision.new_date:
            raise ValidationError(_("El termini ha canviat; cal revisar l'última revisió vigent."))
        if (
            revision.order_id != line.order_id
            or revision.company_id != line.company_id
            or revision.supplier_id != line.order_id.partner_id
        ):
            raise ValidationError(_("La revisió ja no correspon a la comanda i al proveïdor actuals."))

        previous = self.sudo().search([("purchase_line_id", "=", line.id)], limit=1)
        if previous:
            accepted_supplier = previous.supplier_id
        else:
            baseline = Revision.search([
                ("purchase_line_id", "=", line.id), ("revision_type", "=", "initial"),
            ], order="sequence, id", limit=1)
            accepted_supplier = baseline.supplier_id
        if accepted_supplier != revision.supplier_id:
            raise ValidationError(_("No consta cap acord anterior acreditat per a aquest proveïdor."))
        previous_date = previous.new_agreed_date if previous else (
            line.supplier_original_date if line.supplier_original_date_known else False
        )
        if not previous_date:
            raise ValidationError(_("No es coneix cap data acceptada anterior; no es pot inventar un acord històric."))
        if previous and previous.revision_id.sequence >= revision.sequence:
            raise ValidationError(_("La revisió és anterior a l'últim acord confirmat."))
        if previous_date == revision.new_date:
            raise ValidationError(_("La nova data coincideix amb l'última data acceptada."))
        return {
            "revision_id": revision.id,
            "purchase_line_id": line.id, "order_id": line.order_id.id,
            "company_id": revision.company_id.id, "supplier_id": revision.supplier_id.id,
            "previous_confirmation_id": previous.id or False,
            "previous_agreed_date": previous_date, "new_agreed_date": revision.new_date,
            "change_direction": "postponed" if revision.new_date > previous_date else "advanced",
        }

    def write(self, vals):
        raise AccessError(_("Les confirmacions de renegociació són immutables."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_uninstall(self):
        raise UserError(_("No es poden eliminar les confirmacions de renegociació."))

    def copy(self, default=None):
        raise UserError(_("Les confirmacions de renegociació no es poden duplicar."))
