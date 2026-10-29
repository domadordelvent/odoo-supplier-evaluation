"""Pure plan/guard checks; no Odoo import and no database access."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from datetime import timedelta

path = Path(__file__).resolve().parents[1] / 'scripts/generate_otd_demo.py'
spec = importlib.util.spec_from_file_location('demo_plan_under_test', path)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class TestDemoPlan(unittest.TestCase):
    def setUp(self):
        self.plan = demo.build_plan()

    def test_exact_record_and_outcome_counts(self):
        self.assertEqual(len(self.plan), 10)
        orders = [order for vendor in self.plan for order in vendor['orders']]
        self.assertEqual(len(orders), 100)
        self.assertEqual(sum(len(order['lines']) for order in orders), 200)
        self.assertEqual(sum(bool(order['partial_at']) for order in orders), 50)
        self.assertEqual(sum(bool(order['confirmed_at']) for order in orders), 50)
        for vendor in self.plan:
            statuses = [line['status'] for order in vendor['orders'] for line in order['lines']]
            self.assertEqual(statuses.count('on_time'), vendor['on_time'])
            self.assertEqual(statuses.count('late'), vendor['late'])
            self.assertEqual(100 * vendor['on_time'] / len(statuses), vendor['percentage'])

    def test_fixed_seed_is_reproducible_but_changes_distribution_with_other_seed(self):
        self.assertEqual(demo.plan_hash(self.plan), demo.plan_hash(demo.build_plan(demo.SEED)))
        self.assertNotEqual(demo.plan_hash(self.plan), demo.plan_hash(demo.build_plan(demo.SEED + 1)))
        self.assertEqual([v['percentage'] for v in self.plan], list(range(10, 101, 10)))

    def test_chronology_and_realistic_partial_quantities(self):
        for vendor in self.plan:
            for order in vendor['orders']:
                self.assertLess(order['approved_at'], order['received_at'])
                if order['partial_at']:
                    self.assertLess(order['approved_at'], order['partial_at'])
                    self.assertLess(order['partial_at'], order['received_at'])
                if order['confirmed_at']:
                    self.assertLess(order['approved_at'], order['confirmed_at'])
                    self.assertLess(order['confirmed_at'], order['received_at'])
                    if order['partial_at']:
                        self.assertLess(order['partial_at'], order['confirmed_at'])
                for line in order['lines']:
                    self.assertGreater(line['original'], order['approved_at'])
                    self.assertEqual(line['qty'] % 2, 0)
                    self.assertGreater(line['qty'], 0)
                    if order['confirmed_at']:
                        self.assertLess(line['original'], line['deadline'])
                    else:
                        self.assertEqual(line['original'], line['deadline'])

    def test_every_expected_result_matches_24_hour_rule(self):
        for vendor in self.plan:
            for order in vendor['orders']:
                for line in order['lines']:
                    status = 'on_time' if order['received_at'] <= line['deadline'] + timedelta(hours=24) else 'late'
                    self.assertEqual(status, line['status'])

    def test_partial_receipts_are_on_time_against_the_original(self):
        for vendor in self.plan:
            for order in vendor['orders']:
                if order['partial_at']:
                    for line in order['lines']:
                        self.assertLessEqual(order['partial_at'], line['original'] + timedelta(hours=24))

    def test_original_and_unrelated_database_are_rejected_before_orm(self):
        for name in ('supplier_evaluation', 'postgres', 'another_db'):
            with self.subTest(database=name), self.assertRaises(RuntimeError):
                demo.generate_demo(SimpleNamespace(cr=SimpleNamespace(dbname=name)), name)

    def test_target_name_must_match_explicitly(self):
        name = 'supplier_evaluation_otd_demo_test'
        for target in (None, 'different_database', 'supplier_evaluation'):
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                demo.check_target(SimpleNamespace(cr=SimpleNamespace(dbname=name)), target)
        demo.check_target(SimpleNamespace(cr=SimpleNamespace(dbname=name)), name)

    def test_company_namespace_escapes_like_wildcards(self):
        self.assertEqual(demo.namespace_pattern('c1_'), 'c1\\_%')
        self.assertNotEqual(demo.namespace_pattern('c1_'), demo.namespace_pattern('c10_'))

    def test_permanent_demo_requires_explicit_opt_in_and_matching_target(self):
        name = 'supplier_evaluation_demo'
        env = SimpleNamespace(cr=SimpleNamespace(dbname=name))
        with self.assertRaises(RuntimeError):
            demo.check_target(env, name)
        with self.assertRaises(RuntimeError):
            demo.check_target(env, 'supplier_evaluation', allow_permanent=True)
        demo.check_target(env, name, allow_permanent=True)

    def test_permanent_opt_in_never_allows_the_original_database(self):
        env = SimpleNamespace(cr=SimpleNamespace(dbname='supplier_evaluation'))
        with self.assertRaises(RuntimeError):
            demo.generate_demo(env, 'supplier_evaluation', allow_permanent=True)
