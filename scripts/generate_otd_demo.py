"""Deterministic Odoo 18 demo for isolated test or explicitly enabled demo DBs.

Business records are created through ORM and actual purchase/stock workflows.
No commits occur inside generate_demo(); the shell entry point commits once.
"""
import hashlib
import json
import os
import random
from datetime import datetime, timedelta
from unittest.mock import patch

SEED = 180120
VERSION = 1
XML_MODULE = 'supplier_otd_demo'
LABEL = '[OTD DEMO v1]'
SUMMARY_FIELDS = [
    'supplier_otd_has_data', 'supplier_otd_percentage', 'supplier_otd_evaluated_count',
    'supplier_otd_on_time_count', 'supplier_otd_late_count',
]
# ORM side effects (supplier catalog entries, procurement and chatter) are
# identified too, rather than being left as unlabelled records.
RELATED_MODELS = ['procurement.group', 'product.supplierinfo', 'mail.message',
                  'mail.followers', 'mail.notification', 'ir.attachment']


def build_plan(seed=SEED):
    """Business dates/amounts/outcomes are independent of wall clock and DB IDs."""
    rng = random.Random(seed)
    vendors = []
    anchor = datetime(2026, 1, 1, 9)
    for vendor_index in range(1, 11):
        outcomes = ['on_time'] * (vendor_index * 2) + ['late'] * (20 - vendor_index * 2)
        rng.shuffle(outcomes)
        orders = []
        for order_index in range(1, 11):
            number = (vendor_index - 1) * 10 + order_index
            final = anchor + timedelta(days=number + 14, hours=rng.randrange(3))
            partial = number % 4 in (1, 3)
            renegotiated = number % 4 in (2, 3)
            lines = []
            for line_index in range(1, 3):
                status = outcomes[(order_index - 1) * 2 + line_index - 1]
                # Exercise both the inclusive 24h boundary and 1s beyond it.
                delta = rng.choice([timedelta(hours=0), timedelta(hours=12), timedelta(hours=24)]) if status == 'on_time' else rng.choice([timedelta(hours=24, seconds=1), timedelta(hours=48), timedelta(hours=72)])
                deadline = final - delta
                lines.append({
                    'index': line_index, 'status': status, 'deadline': deadline,
                    'original': deadline - timedelta(days=4) if renegotiated else deadline,
                    'qty': rng.choice([2, 4, 10, 20]), 'price': rng.randint(5, 200),
                    'supplier_attributable': bool(rng.randrange(2)),
                })
            orders.append({
                'number': number, 'index': order_index, 'approved_at': final - timedelta(days=12),
                'received_at': final, 'partial_at': final - timedelta(days=7) if partial else None,
                'confirmed_at': final - timedelta(days=3) if renegotiated else None,
                'lines': lines,
            })
        vendors.append({'index': vendor_index, 'on_time': vendor_index * 2,
                        'late': 20 - vendor_index * 2, 'percentage': vendor_index * 10,
                        'orders': orders})
    return vendors


def plan_hash(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, default=str).encode()).hexdigest()


def namespace_pattern(prefix):
    """Literal prefix for PostgreSQL LIKE; c1_ must not match c10_ ids."""
    return prefix.replace('\\', '\\\\').replace('_', '\\_').replace('%', '\\%') + '%'


def check_target(env, expected_database, allow_permanent=False):
    name = env.cr.dbname
    permitted = name.startswith('supplier_evaluation_otd_') or (
        name == 'supplier_evaluation_demo' and allow_permanent is True
    )
    if name == 'supplier_evaluation' or not permitted:
        raise RuntimeError('Use a temporary OTD database or explicitly enable the independent supplier_evaluation_demo database; the original DB is forbidden.')
    if expected_database != name:
        raise RuntimeError('OTD_DEMO_TARGET_DB must exactly match the isolated target database.')


class _Demo:
    def __init__(self, env, seed):
        from odoo import Command
        self.Command = Command
        self.env = env['res.partner'].with_context(tracking_disable=True, mail_create_nolog=True,
                                    mail_create_nosubscribe=True).env
        self.company = self.env.company
        self.seed = seed
        self.plan = build_plan(seed)
        self.prefix = 'c%d_' % self.company.id
        self.ref = 'OTD-DEMO-v1-C%d' % self.company.id
        self.key = 'supplier_otd_demo.v1.company_%d' % self.company.id
        self.bindings = {}

    def bind(self, name, record):
        record.ensure_one()
        name = self.prefix + name
        existing = self.env['ir.model.data'].search([('module', '=', XML_MODULE), ('name', '=', name)])
        if existing:
            raise RuntimeError('Unexpected pre-existing demo external ID: ' + name)
        self.env['ir.model.data'].create({
            'module': XML_MODULE, 'name': name, 'model': record._name,
            'res_id': record.id, 'noupdate': True,
        })
        self.bindings[name] = [record._name, record.id]
        return record

    def record(self, name):
        return self.env.ref(XML_MODULE + '.' + self.prefix + name)

    def capture_generated_ids(self):
        for vp in self.plan:
            for op in vp['orders']:
                number = op['number']
                order = self.record('order_%03d' % number)
                for lp, line in zip(op['lines'], order.order_line.sorted('id')):
                    suffix = 'order_%03d_line_%d' % (number, lp['index'])
                    for revision in line.supplier_deadline_revision_ids.sorted('sequence'):
                        self.bind(suffix + '_revision_%d' % revision.sequence, revision)
                    for confirmation in line.supplier_deadline_confirmation_ids.sorted('id'):
                        self.bind(suffix + '_confirmation_%d' % confirmation.revision_id.sequence, confirmation)
                for pi, picking in enumerate(order.picking_ids.sorted('id'), 1):
                    suffix = 'order_%03d_receipt_%d' % (number, pi)
                    self.bind(suffix, picking)
                    for mi, move in enumerate(picking.move_ids.sorted('id'), 1):
                        self.bind(suffix + '_move_%d' % mi, move)
                        for mli, ml in enumerate(move.move_line_ids.sorted('id'), 1):
                            self.bind(suffix + '_move_%d_detail_%d' % (mi, mli), ml)
        # Quants, if created by the installed stock configuration, are confined
        # to the dedicated demo locations/products and explicitly identified.
        location = self.record('location')
        quants = self.env['stock.quant'].search([('location_id', 'child_of', location.id)])
        for i, quant in enumerate(quants.sorted('id'), 1):
            self.bind('quant_%d' % i, quant)

    def identify_related(self):
        for model, before in self.related_before.items():
            records = self.env[model].with_context(active_test=False).search([('id', 'not in', sorted(before))], order='id')
            for i, record in enumerate(records, 1):
                self.bind('related_%s_%d' % (model.replace('.', '_'), i), record)

    def receive(self, picking, moment, fraction):
        picking.ensure_one()
        for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            move.quantity = move.product_uom_qty * fraction
            move.picked = True
        with patch('odoo.fields.Datetime.now', return_value=moment):
            result = picking.button_validate()
        if result is not True or picking.state != 'done':
            raise RuntimeError('Stock validation did not complete normally: ' + picking.name)

    def create(self):
        # Namespace and visible identifiers must be unused; never adopt or edit
        # a real record that happens to collide with a demo name/reference.
        if self.env['ir.model.data'].search_count([('module', '=', XML_MODULE), ('name', '=like', namespace_pattern(self.prefix))]):
            raise RuntimeError('Partial demo namespace exists without its manifest. Inspect manually; no records were adopted.')
        if self.env['res.partner'].search_count([('ref', '=like', self.ref + '-%')]) or self.env['purchase.order'].search_count([('name', '=like', self.ref + '-%')]):
            raise RuntimeError('Demo references already exist outside the registered dataset.')
        self.related_before = {model: set(self.env[model].with_context(active_test=False).search([]).ids) for model in RELATED_MODELS}
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], order='id', limit=1)
        if not warehouse:
            raise RuntimeError('This company needs an existing warehouse; the generator never changes company/warehouse settings.')
        location = self.bind('location', self.env['stock.location'].create({
            'name': LABEL + ' Demo Receipts', 'usage': 'internal',
            'company_id': self.company.id, 'location_id': warehouse.view_location_id.id,
        }))
        sequence = self.bind('receipt_sequence', self.env['ir.sequence'].create({
            'name': LABEL + ' Receipt Sequence', 'prefix': self.ref + '/IN/',
            'padding': 5, 'company_id': self.company.id,
        }))
        receipt_type = self.bind('receipt_type', self.env['stock.picking.type'].create({
            'name': LABEL + ' Demo Receipts', 'code': 'incoming', 'warehouse_id': False,
            'company_id': self.company.id, 'sequence_id': sequence.id,
            'sequence_code': 'OTDD', 'create_backorder': 'always',
            'default_location_src_id': self.env.ref('stock.stock_location_suppliers').id,
            'default_location_dest_id': location.id,
        }))
        products = []
        for i in (1, 2):
            product = self.bind('product_%d' % i, self.env['product.product'].create({
                'name': LABEL + ' Product %d' % i, 'default_code': self.ref + '-PRODUCT%d' % i,
                'type': 'consu', 'is_storable': False, 'company_id': self.company.id,
                'purchase_ok': True, 'sale_ok': False,
                'supplier_taxes_id': [self.Command.clear()], 'taxes_id': [self.Command.clear()],
            }))
            self.bind('product_template_%d' % i, product.product_tmpl_id)
            products.append(product)
        for vp in self.plan:
            vi = vp['index']
            vendor = self.bind('vendor_%02d' % vi, self.env['res.partner'].create({
                'name': LABEL + ' Supplier %02d' % vi, 'ref': self.ref + '-SUPPLIER%02d' % vi,
                'is_company': True, 'supplier_rank': 1, 'company_id': self.company.id,
                'email': 'supplier%02d@otd-demo.invalid' % vi,
            }))
            for op in vp['orders']:
                number = op['number']
                values = []
                for lp, product in zip(op['lines'], products):
                    values.append(self.Command.create({
                        'product_id': product.id, 'name': LABEL + ' Line %d' % lp['index'],
                        'product_qty': lp['qty'], 'product_uom': product.uom_id.id,
                        'price_unit': lp['price'], 'date_planned': lp['original'],
                        'taxes_id': [self.Command.clear()],
                    }))
                with patch('odoo.fields.Datetime.now', return_value=op['approved_at']):
                    order = self.bind('order_%03d' % number, self.env['purchase.order'].create({
                        'name': self.ref + '-PO%03d' % number, 'origin': LABEL,
                        'partner_ref': self.ref + '-PO%03d' % number,
                        'partner_id': vendor.id, 'company_id': self.company.id,
                        'picking_type_id': receipt_type.id,
                        'date_order': op['approved_at'], 'order_line': values,
                    }))
                    order.button_confirm()
                if order.state != 'purchase':
                    raise RuntimeError('Order approval requires configuration not supported by this generator.')
                for lp, line in zip(op['lines'], order.order_line.sorted('id')):
                    self.bind('order_%03d_line_%d' % (number, lp['index']), line)
                if op['partial_at']:
                    self.receive(order.picking_ids, op['partial_at'], 0.5)
                    if any(order.order_line.mapped('supplier_otd_captured_at')):
                        raise RuntimeError('An incomplete line unexpectedly acquired an OTD result.')
                if op['confirmed_at']:
                    with patch('odoo.fields.Datetime.now', return_value=op['confirmed_at']):
                        for lp, line in zip(op['lines'], order.order_line.sorted('id')):
                            line.date_planned = lp['deadline']
                            revision = line.supplier_deadline_revision_ids.sorted('sequence')[-1]
                            revision.action_confirm_renegotiation(
                                LABEL + ' Explicit fictional agreement before completion.',
                                lp['supplier_attributable'],
                            )
                remaining = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
                self.receive(remaining, op['received_at'], 1.0)
            print('OTD_DEMO_PROGRESS supplier %02d/10 created' % vi, flush=True)
        self.capture_generated_ids()
        self.identify_related()
        manifest = {
            'version': VERSION, 'seed': self.seed, 'company_id': self.company.id,
            'plan_sha256': plan_hash(self.plan), 'bindings': dict(self.bindings),
        }
        parameter = self.env['ir.config_parameter'].create({'key': self.key, 'value': json.dumps(manifest, sort_keys=True)})
        self.bind('manifest', parameter)
        # The manifest entry itself is deterministic but is not recursively
        # included in its own bindings payload.
        return manifest

    def validate(self, manifest):
        if (manifest['version'], manifest['seed'], manifest['company_id'], manifest['plan_sha256']) != (VERSION, self.seed, self.company.id, plan_hash(self.plan)):
            raise RuntimeError('Existing demo manifest differs in version, seed, company or plan. No changes performed.')
        bindings = manifest['bindings']
        metadata = self.env['ir.model.data'].search([('module', '=', XML_MODULE), ('name', '=like', namespace_pattern(self.prefix))])
        expected = dict(bindings)
        marker = self.env['ir.config_parameter'].search([('key', '=', self.key)])
        expected[self.prefix + 'manifest'] = ['ir.config_parameter', marker.id]
        actual = {r.name: [r.model, r.res_id] for r in metadata}
        if actual != expected:
            raise RuntimeError('External IDs differ from the original demo manifest; no repair attempted.')
        for name, (model, record_id) in expected.items():
            if not self.env[model].browse(record_id).exists():
                raise RuntimeError('Missing demo record: ' + name)
        result = []
        for vp in self.plan:
            vendor = self.record('vendor_%02d' % vp['index'])
            if vendor.ref != self.ref + '-SUPPLIER%02d' % vp['index']:
                raise RuntimeError('Demo vendor reference changed.')
            for op in vp['orders']:
                order = self.record('order_%03d' % op['number'])
                if order.partner_id != vendor or order.company_id != self.company or order.state != 'purchase' or len(order.order_line) != 2:
                    raise RuntimeError('Demo order differs from its plan.')
                if order.date_order != op['approved_at'] or order.date_approve != op['approved_at']:
                    raise RuntimeError('Order dates differ from the planned chronology.')
                pickings = order.picking_ids.sorted('id')
                if len(pickings) != (2 if op['partial_at'] else 1) or any(p.state != 'done' for p in pickings):
                    raise RuntimeError('Demo receipt count or state is incorrect.')
                for lp, line in zip(op['lines'], order.order_line.sorted('id')):
                    if (line.supplier_otd_status != lp['status'] or line.supplier_otd_deadline != lp['deadline']
                        or line.supplier_otd_completed_at != op['received_at'] or not line.supplier_otd_captured_at
                        or line.supplier_original_date != lp['original'] or not line.supplier_original_date_known
                        or line.supplier_otd_supplier_id != vendor or line.product_qty != lp['qty']
                        or line.qty_received != lp['qty'] or line.price_unit != lp['price']
                        or line.supplier_otd_ordered_qty != lp['qty'] or line.supplier_otd_received_qty != lp['qty']):
                        raise RuntimeError('Line snapshot, result, quantities or chronology differs: ' + order.name)
                    confirmations = line.supplier_deadline_confirmation_ids
                    if len(confirmations) != bool(op['confirmed_at']):
                        raise RuntimeError('Unexpected confirmation count.')
                    if op['confirmed_at']:
                        if (confirmations.confirmed_at != op['confirmed_at']
                            or confirmations.new_agreed_date != lp['deadline']
                            or confirmations.previous_agreed_date != lp['original']
                            or line.supplier_otd_confirmation_id != confirmations):
                            raise RuntimeError('The final capture did not use the planned prior confirmation.')
                    elif line.supplier_otd_confirmation_id:
                        raise RuntimeError('An unplanned agreement was captured.')
                    for picking in pickings:
                        expected_date = op['partial_at'] if picking == pickings[0] and op['partial_at'] else op['received_at']
                        moves = picking.move_ids.filtered(lambda m: m.purchase_line_id == line)
                        if len(moves) != 1 or moves.supplier_receipt_date_snapshot != expected_date:
                            raise RuntimeError('Receipt timestamps do not match the planned event.')
                        expected_agreed = lp['original'] if op['partial_at'] and picking == pickings[0] else lp['deadline']
                        if moves.supplier_agreed_date_snapshot != expected_agreed or picking.date_done != expected_date:
                            raise RuntimeError('Historical receipt capture was not preserved.')
            vendor.invalidate_recordset(SUMMARY_FIELDS)
            summary = vendor.read(SUMMARY_FIELDS)[0]
            if (summary['supplier_otd_evaluated_count'] != 20
                or summary['supplier_otd_on_time_count'] != vp['on_time']
                or summary['supplier_otd_late_count'] != vp['late']
                or not summary['supplier_otd_has_data']
                or abs(summary['supplier_otd_percentage'] - vp['percentage']) > 0.001):
                raise RuntimeError('Aggregated OTD differs from the independent plan: ' + vendor.ref)
            result.append({'supplier': vendor.name, 'evaluated': 20, 'on_time': vp['on_time'],
                           'late': vp['late'], 'otd_percentage': summary['supplier_otd_percentage']})
        counts = {model: sum(value[0] == model for value in expected.values()) for model in ('res.partner', 'purchase.order', 'purchase.order.line', 'stock.picking', 'stock.move', 'supplier.evaluation.deadline.revision', 'supplier.evaluation.deadline.confirmation')}
        required = {'res.partner': 10, 'purchase.order': 100, 'purchase.order.line': 200,
                    'stock.picking': 150, 'stock.move': 300,
                    'supplier.evaluation.deadline.revision': 300,
                    'supplier.evaluation.deadline.confirmation': 100}
        if counts != required:
            raise RuntimeError('Demo record counts differ: ' + repr(counts))
        return {'seed': self.seed, 'plan_sha256': plan_hash(self.plan), 'counts': counts,
                'suppliers': result, 'external_ids': len(expected), 'company_id': self.company.id}


def generate_demo(env, expected_database, seed=SEED, allow_permanent=False):
    check_target(env, expected_database, allow_permanent)  # Guard BEFORE any ORM read or write.
    if not all(env.user.has_group(group) for group in ('base.group_system', 'purchase.group_purchase_manager', 'stock.group_stock_user')):
        raise RuntimeError('Use an administrator with purchase manager and stock user permissions.')
    module = env['ir.module.module'].search([('name', '=', 'supplier_evaluation')], limit=1)
    if module.state != 'installed' or module.latest_version != '18.0.1.2.0':
        raise RuntimeError('The target demo database must already have supplier_evaluation 18.0.1.2.0 installed.')
    demo = _Demo(env, seed)
    # Refuse simultaneous runs rather than creating duplicate documents.
    lock = int.from_bytes(hashlib.sha256(demo.key.encode()).digest()[:8], 'big', signed=True)
    env.cr.execute('SELECT pg_try_advisory_xact_lock(%s)', [lock])
    if not env.cr.fetchone()[0]:
        raise RuntimeError('Another generator is already running for this company.')
    with env.cr.savepoint():
        parameter = demo.env['ir.config_parameter'].search([('key', '=', demo.key)])
        reused = bool(parameter)
        manifest = json.loads(parameter.value) if reused else demo.create()
        report = demo.validate(manifest)
        report['reused_existing_dataset'] = reused
        return report


if 'env' in globals():
    try:
        report = generate_demo(
            env, os.environ.get('OTD_DEMO_TARGET_DB'),
            allow_permanent=os.environ.get('OTD_DEMO_ALLOW_PERMANENT') == '1',
        )
        if report['reused_existing_dataset']:
            env.cr.rollback()
        else:
            env.cr.commit()
        print('OTD_DEMO_RESULT=' + json.dumps(report, sort_keys=True, ensure_ascii=False), flush=True)
    except BaseException:
        env.cr.rollback()
        raise
