"""Run the addon TransactionCase suite through an installed Odoo shell.

No module installation or commit; test cursors are closed with rollback.
"""
import unittest

from odoo.addons.supplier_evaluation.tests.test_deadline_history import TestDeadlineHistory
from odoo.addons.supplier_evaluation.tests.test_deadline_confirmation import TestDeadlineConfirmation
from odoo.addons.supplier_evaluation.tests.test_deadline_wizard import TestDeadlineWizard

try:
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(TestDeadlineHistory),
        unittest.defaultTestLoader.loadTestsFromTestCase(TestDeadlineConfirmation),
        unittest.defaultTestLoader.loadTestsFromTestCase(TestDeadlineWizard),
    ])
    result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
finally:
    env.cr.rollback()
    env.invalidate_all()
    print("ROLLBACK: integration shell transaction reverted", flush=True)
