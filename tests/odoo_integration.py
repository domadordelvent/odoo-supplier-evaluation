"""Run the addon suite in an isolated, updated Odoo test database.

No module installation or commit; test cursors are closed with rollback.
"""
import unittest

# Refuse the original database even if this script is launched by mistake.
if not env.cr.dbname.startswith("supplier_evaluation_otd_"):
    raise RuntimeError("Integration tests require a supplier_evaluation_otd_* database.")

from odoo.addons.supplier_evaluation.tests.test_deadline_history import TestDeadlineHistory
from odoo.addons.supplier_evaluation.tests.test_deadline_confirmation import TestDeadlineConfirmation
from odoo.addons.supplier_evaluation.tests.test_deadline_wizard import TestDeadlineWizard
from odoo.addons.supplier_evaluation.tests.test_line_otd import TestLineOTD
from odoo.addons.supplier_evaluation.tests.test_supplier_otd import TestSupplierOTD
from odoo.addons.supplier_evaluation.tests.test_supplier_otd_ui import TestSupplierOTDUI

try:
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(TestDeadlineHistory),
        unittest.defaultTestLoader.loadTestsFromTestCase(TestDeadlineConfirmation),
        unittest.defaultTestLoader.loadTestsFromTestCase(TestDeadlineWizard),
        unittest.defaultTestLoader.loadTestsFromTestCase(TestLineOTD),
        unittest.defaultTestLoader.loadTestsFromTestCase(TestSupplierOTD),
        unittest.defaultTestLoader.loadTestsFromTestCase(TestSupplierOTDUI),
    ])
    result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
finally:
    env.cr.rollback()
    env.invalidate_all()
    print("ROLLBACK: integration shell transaction reverted", flush=True)
