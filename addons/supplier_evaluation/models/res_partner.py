from odoo import api, fields, models, _
from odoo.exceptions import AccessError


_PURCHASE_GROUP = "purchase.group_purchase_user"


class ResPartner(models.Model):
    _inherit = "res.partner"

    supplier_otd_line_ids = fields.One2many(
        "purchase.order.line", "supplier_otd_supplier_id", readonly=True, copy=False,
        groups=_PURCHASE_GROUP,
    )
    supplier_otd_has_data = fields.Boolean(
        compute="_compute_supplier_otd_summary", compute_sudo=False, groups=_PURCHASE_GROUP,
    )
    supplier_otd_percentage = fields.Float(
        string="Percentatge OTD", digits=(5, 2),
        compute="_compute_supplier_otd_summary", compute_sudo=False, groups=_PURCHASE_GROUP,
        help="Línies puntuals / línies avaluades × 100. Cada línia compta una vegada, sense ponderació per quantitat o preu.",
    )
    supplier_otd_evaluated_count = fields.Integer(
        string="Línies avaluades", compute="_compute_supplier_otd_summary",
        compute_sudo=False, groups=_PURCHASE_GROUP,
    )
    supplier_otd_on_time_count = fields.Integer(
        string="Línies puntuals", compute="_compute_supplier_otd_summary",
        compute_sudo=False, groups=_PURCHASE_GROUP,
    )
    supplier_otd_late_count = fields.Integer(
        string="Línies tardanes", compute="_compute_supplier_otd_summary",
        compute_sudo=False, groups=_PURCHASE_GROUP,
    )

    @api.depends_context("uid", "company", "allowed_company_ids")
    @api.depends(
        "supplier_otd_line_ids.supplier_otd_status",
        "supplier_otd_line_ids.supplier_otd_captured_at",
        "supplier_otd_line_ids.supplier_otd_completed_at",
        "supplier_otd_line_ids.supplier_otd_deadline",
        "supplier_otd_line_ids.order_id.state",
        "supplier_otd_line_ids.company_id",
    )
    def _compute_supplier_otd_summary(self):
        # Restrict the actual user even if a caller explicitly uses sudo().
        if not self.env.user.has_group(_PURCHASE_GROUP):
            raise AccessError(_("Només els usuaris de compres poden consultar l'OTD agregat."))
        companies = self.env.companies & self.env.user.company_ids
        partner_ids = [partner.id for partner in self if isinstance(partner.id, int) and partner.id > 0]
        counts = {}
        if partner_ids and companies:
            # Drop inherited sudo as well: native purchase ACLs and record
            # rules apply even if a caller elevated the partner recordset.
            # Attribute to the supplier captured at completion, not a mutable
            # order partner or a commercial-parent rollup. No live quantities,
            # prices, dates or confirmation recomputations enter the formula.
            lines = self.env["purchase.order.line"].sudo(False).with_context(allowed_company_ids=companies.ids)
            rows = lines._read_group([
                ("supplier_otd_supplier_id", "in", partner_ids),
                ("company_id", "in", companies.ids),
                ("order_id.state", "in", ["purchase", "done"]),
                ("display_type", "=", False),
                ("supplier_otd_captured_at", "!=", False),
                ("supplier_otd_completed_at", "!=", False),
                ("supplier_otd_deadline", "!=", False),
                ("supplier_otd_status", "in", ["on_time", "late"]),
            ], ["supplier_otd_supplier_id", "supplier_otd_status"], ["__count"])
            for partner, status, count in rows:
                counts.setdefault(partner.id, {})[status] = count
        for partner in self:
            on_time = counts.get(partner.id, {}).get("on_time", 0)
            late = counts.get(partner.id, {}).get("late", 0)
            total = on_time + late
            partner.supplier_otd_has_data = bool(total)
            partner.supplier_otd_percentage = 100.0 * on_time / total if total else 0.0
            partner.supplier_otd_evaluated_count = total
            partner.supplier_otd_on_time_count = on_time
            partner.supplier_otd_late_count = late
