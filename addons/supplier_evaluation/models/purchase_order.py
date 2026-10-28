from odoo import models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _supplier_lock_orders(self):
        self.flush_recordset(["state"])
        if self:
            self.env.cr.execute(
                "SELECT id FROM purchase_order WHERE id IN %s ORDER BY id FOR UPDATE",
                [tuple(sorted(self.ids))],
            )
            self.invalidate_recordset(["state", "order_line"])

    def write(self, vals):
        if vals.get("state") != "purchase":
            return super().write(vals)
        self.check_access("write")
        # Lock even empty orders; lines acquire these locks in the same order.
        self._supplier_lock_orders()
        lines = self.order_line
        lines._supplier_lock_deadlines()
        result = super().write(vals)
        lines._supplier_ensure_history()
        return result
