import math

from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import SQL, formatLang


_PURCHASE_GROUP = "purchase.group_purchase_user"


class ResPartner(models.Model):
    _inherit = "res.partner"

    supplier_otd_line_ids = fields.One2many(
        "purchase.order.line", "supplier_otd_supplier_id", readonly=True, copy=False,
        groups=_PURCHASE_GROUP,
    )
    supplier_otd_has_data = fields.Boolean(
        compute="_compute_supplier_otd_summary", compute_sudo=False, groups=_PURCHASE_GROUP,
        search="_search_supplier_otd_has_data",
    )
    supplier_otd_percentage = fields.Float(
        string="Percentatge OTD", digits=(5, 2), search="_search_supplier_otd_percentage",
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

    supplier_otd_display = fields.Char(
        string="OTD", compute="_compute_supplier_otd_display", compute_sudo=False,
        groups=_PURCHASE_GROUP,
    )

    @api.depends_context("uid", "company", "allowed_company_ids", "lang")
    @api.depends("supplier_otd_has_data", "supplier_otd_percentage")
    def _compute_supplier_otd_display(self):
        for partner in self:
            partner.supplier_otd_display = (
                formatLang(self.env, partner.supplier_otd_percentage, digits=2) + " %"
                if partner.supplier_otd_has_data else _("Sense dades")
            )

    @api.model
    def _supplier_otd_source(self, partner_ids=None):
        """One shared eligibility/security scope for counters, order, search and drilldown."""
        if not self.env.user.has_group(_PURCHASE_GROUP):
            raise AccessError(_("Només els usuaris de compres poden consultar l'OTD agregat."))
        companies = self.env.companies & self.env.user.company_ids
        lines = self.env["purchase.order.line"].sudo(False).with_context(allowed_company_ids=companies.ids)
        domain = [
            ("supplier_otd_supplier_id", "!=", False),
            ("company_id", "in", companies.ids),
            ("order_id.state", "in", ["purchase", "done"]),
            ("display_type", "=", False),
            ("supplier_otd_captured_at", "!=", False),
            ("supplier_otd_completed_at", "!=", False),
            ("supplier_otd_deadline", "!=", False),
            ("supplier_otd_status", "in", ["on_time", "late"]),
        ]
        if partner_ids is not None:
            domain.append(("supplier_otd_supplier_id", "in", partner_ids))
        return lines, domain

    @api.model
    def _supplier_otd_totals_sql(self):
        """Read-only derived aggregate; the ORM subquery enforces purchase record rules.

        SQL ordering precedes LIMIT/OFFSET. No persistent totals or Python-wide
        partner sorting, and no change to standard Contact actions.
        """
        lines, domain = self._supplier_otd_source()
        visible = lines._search(domain)
        lines.flush_model(["supplier_otd_supplier_id", "supplier_otd_status"])
        return SQL("""
            SELECT line.supplier_otd_supplier_id AS partner_id,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE line.supplier_otd_status = 'on_time')
                         / COUNT(*), 2) AS percentage
              FROM purchase_order_line AS line
             WHERE line.id IN %s
             GROUP BY line.supplier_otd_supplier_id
        """, visible.subselect())

    def _order_field_to_sql(self, alias, field_name, direction, nulls, query):
        # Native get_views metadata cannot depend on an action context flag.
        # Only these custom fields gain ordering; Contact views/default order
        # and actions remain unchanged.
        if field_name in ("supplier_otd_percentage", "supplier_otd_display"):
            totals_alias = query.make_alias(alias, "supplier_otd_totals")
            query.add_join("LEFT JOIN", totals_alias, SQL("(%s)", self._supplier_otd_totals_sql()), SQL(
                "%s = %s", SQL.identifier(alias, "id"), SQL.identifier(totals_alias, "partner_id"),
            ))
            return SQL("%s %s %s", SQL.identifier(totals_alias, "percentage"), direction, nulls or SQL("NULLS LAST"))
        return super()._order_field_to_sql(alias, field_name, direction, nulls, query)

    @api.model
    def _search_supplier_otd_percentage(self, operator, value):
        # No-data rows have no percentage and never match numeric filters.
        if operator not in ("=", "!=", "<", "<=", ">", ">=") or type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Use a finite numeric OTD comparison.")
        rows = self.env.execute_query(SQL(
            "SELECT partner_id FROM (%s) AS totals WHERE percentage %s %s",
            self._supplier_otd_totals_sql(), SQL(operator), value,
        ))
        return [("id", "in", [row[0] for row in rows])]

    @api.model
    def _search_supplier_otd_has_data(self, operator, value):
        if operator not in ("=", "!=") or type(value) is not bool:
            raise ValueError("Use a boolean data-availability comparison.")
        rows = self.env.execute_query(self._supplier_otd_totals_sql())
        positive = value if operator == "=" else not value
        return [("id", "in" if positive else "not in", [row[0] for row in rows])]

    def action_open_supplier_otd_lines(self):
        self.ensure_one()
        lines, domain = self._supplier_otd_source(self.ids)
        self.sudo(False).with_context(allowed_company_ids=lines.env.companies.ids).check_access("read")
        action = self.env["ir.actions.actions"]._for_xml_id("supplier_evaluation.action_supplier_otd_lines")
        action["domain"] = domain
        action["context"] = {
            key: value for key, value in lines.env.context.items()
            if not key.startswith(("default_", "search_default_")) and key != "supplier_otd_overview"
        }
        return action

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
        partner_ids = [partner.id for partner in self if isinstance(partner.id, int) and partner.id > 0]
        lines, domain = self._supplier_otd_source(partner_ids)
        counts = {}
        if partner_ids:
            rows = lines._read_group(domain, ["supplier_otd_supplier_id", "supplier_otd_status"], ["__count"])
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
