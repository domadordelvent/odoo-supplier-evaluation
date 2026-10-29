"""Optional Playwright checks against the ten demo vendors in a temporary DB.

Only a new no-data partner is created and removed in finally. No browser
libraries or assets are installed into the Odoo addon.
"""
import argparse
import json
import os
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8075')
    parser.add_argument('--database', required=True)
    parser.add_argument('--login', default='demo_admin')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--browser-executable')
    args = parser.parse_args()
    if not args.database.startswith('supplier_evaluation_otd_'):
        parser.error('Use a temporary supplier_evaluation_otd_* DB; permanent bases are forbidden.')
    password = os.environ.get('OTD_UI_PASSWORD')
    if not password:
        parser.error('Set OTD_UI_PASSWORD in the environment.')
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip('/')
    launch_options = {'headless': True, 'args': ['--no-sandbox']}
    if args.browser_executable:
        launch_options['executable_path'] = args.browser_executable

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='en-US')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        # Authenticate an explicit DB, so an Odoo fallback cannot select a
        # permanent database before the test creates its temporary fixture.
        authenticated = context.request.post(base + '/web/session/authenticate', data={
            'jsonrpc': '2.0', 'method': 'call', 'id': 0,
            'params': {'db': args.database, 'login': args.login, 'password': password},
        }).json()
        if authenticated.get('error'):
            raise RuntimeError('Authentication failed; no UI fixture was created.')
        assert authenticated['result']['db'] == args.database

        def rpc(model, method, arguments=None, keywords=None):
            response = context.request.post(base + '/web/dataset/call_kw/' + model + '/' + method, data={
                'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                'params': {'model': model, 'method': method, 'args': arguments or [], 'kwargs': keywords or {}},
            }).json()
            if response.get('error'):
                raise RuntimeError(response['error'].get('data', {}).get('message', 'RPC failed'))
            return response['result']

        def settle_form(response):
            response.json()
            # Long polling prevents networkidle; wait for the form's RPC and
            # Owl rendering instead of sleeping or disabling native animations.
            page.evaluate('async () => {await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);}')

        def open_otd_tab():
            tab = page.get_by_role('tab', name='Avaluació OTD', exact=True)
            tab.click(timeout=30000)
            expect(tab).to_have_class(re.compile(r'.*\bactive\b.*'))
            expect(page.locator('.o_notebook_content > .tab-pane.active')).to_have_css('opacity', '1')

        page.goto(base + '/odoo', wait_until='domcontentloaded')
        page.locator('.o_main_navbar').wait_for(timeout=60000)
        records = rpc('ir.model.data', 'search_read', [[
            ('module', '=', 'supplier_evaluation'), ('name', '=', 'action_supplier_otd_overview'),
        ]], {'fields': ['res_id']})
        action_id = records[0]['res_id']
        overview = base + '/odoo/action-' + str(action_id)
        page.goto(overview, wait_until='domcontentloaded')
        rows = page.locator('.o_list_view tbody tr.o_data_row')
        expect(rows).to_have_count(10, timeout=60000)
        expect(rows.first.locator('td[name="supplier_otd_display"]')).to_have_text('100.00 %')
        heading = page.locator('th[data-name="supplier_otd_display"]')
        expect(heading).to_have_class(re.compile('.*o_column_sortable.*'))
        heading.click()
        expect(rows.first.locator('td[name="supplier_otd_display"]')).to_have_text('10.00 %')
        heading.click()
        expect(rows.first.locator('td[name="supplier_otd_display"]')).to_have_text('100.00 %')
        page.screenshot(path=str(output / 'supplier-otd-list.png'), full_page=True)

        vendors = rpc('res.partner', 'search_read', [[('supplier_rank', '>', 0)]], {
            'fields': ['id', 'name', 'supplier_otd_percentage'], 'order': 'name',
        })
        assert len(vendors) == 10
        checked = []
        progress_widths = []
        for vendor in vendors:
            with page.expect_response(lambda response: '/res.partner/web_read' in response.url) as pending:
                page.goto(overview + '/' + str(vendor['id']), wait_until='domcontentloaded')
            settle_form(pending.value)
            open_otd_tab()
            expect(page.locator('.o_field_widget[name="supplier_otd_evaluated_count"]')).to_have_text('20')
            expect(page.locator('.o_field_widget[name="supplier_otd_percentage"]').first).to_have_text(
                str(int(vendor['supplier_otd_percentage'])) + '.00')
            expect(page.locator('.o_field_progressbar[name="supplier_otd_percentage"]')).to_be_visible()
            expect(page.locator('.oe_stat_button:has(.o_field_widget[name="on_time_rate"])')).to_be_hidden()
            track = page.locator('.o_supplier_otd_progress .o_progress')
            width = track.bounding_box()['width']
            assert width >= 200, width
            progress_widths.append(width)
            checked.append(vendor['supplier_otd_percentage'])
            if vendor['name'].endswith('04'):
                page.screenshot(path=str(output / 'supplier-otd-form.png'), full_page=True)
        assert checked == list(range(10, 101, 10))

        supplier05 = next(vendor for vendor in vendors if vendor['name'].endswith('05'))
        with page.expect_response(lambda response: '/res.partner/web_read' in response.url) as pending:
            page.goto(overview + '/' + str(supplier05['id']), wait_until='domcontentloaded')
        settle_form(pending.value)
        open_otd_tab()
        for field, count in [('supplier_otd_evaluated_count', 20), ('supplier_otd_on_time_count', 10), ('supplier_otd_late_count', 10)]:
            expect(page.locator('.o_field_widget[name="' + field + '"]')).to_have_text(str(count))
        page.screenshot(path=str(output / 'supplier-05-form.png'), full_page=True)
        page.locator('button[name="action_open_supplier_otd_lines"]').click()
        detail_rows = page.locator('.o_list_view tbody tr.o_data_row')
        expect(detail_rows).to_have_count(20)
        states05 = detail_rows.locator('td[name="supplier_otd_status"]').all_text_contents()
        assert sum(value.strip() == 'Puntual' for value in states05) == 10
        assert sum(value.strip() == 'Amb retard' for value in states05) == 10
        for field in ('order_id', 'product_id', 'supplier_otd_deadline', 'supplier_otd_completed_at'):
            values = detail_rows.locator('td[name="' + field + '"]').all_text_contents()
            assert len(values) == 20 and all(value.strip() for value in values), field
        page.screenshot(path=str(output / 'supplier-05-lines.png'), full_page=True)
        standard_action = rpc('ir.model.data', 'search_read', [[('module', '=', 'account'), ('name', '=', 'res_partner_action_supplier')]], {'fields': ['res_id']})[0]['res_id']
        with page.expect_response(lambda response: '/res.partner/web_read' in response.url) as pending:
            page.goto(base + '/odoo/action-' + str(standard_action) + '/' + str(supplier05['id']), wait_until='domcontentloaded')
        settle_form(pending.value)
        expect(page.locator('.oe_stat_button:has(.o_field_widget[name="on_time_rate"])')).to_be_visible()
        page.screenshot(path=str(output / 'supplier-05-standard-form.png'), full_page=True)

        page.goto(overview, wait_until='domcontentloaded')
        expect(rows).to_have_count(10)
        page.locator('.o_searchview_dropdown_toggler').click()
        page.get_by_text('OTD inferior al 50 %', exact=True).click()
        page.keyboard.press('Escape')
        expect(rows).to_have_count(4)
        filtered = rows.locator('td[name="supplier_otd_display"]').all_text_contents()
        assert [value.strip() for value in filtered] == ['40.00 %', '30.00 %', '20.00 %', '10.00 %']
        page.screenshot(path=str(output / 'supplier-otd-filter.png'), full_page=True)
        with page.expect_response(lambda response: '/res.partner/web_read' in response.url) as pending:
            rows.first.locator('td[name="name"]').click()
        settle_form(pending.value)
        open_otd_tab()
        page.locator('button[name="action_open_supplier_otd_lines"]').click()
        audit_rows = page.locator('.o_list_view tbody tr.o_data_row')
        expect(audit_rows).to_have_count(20)
        states = audit_rows.locator('td[name="supplier_otd_status"]').all_text_contents()
        assert sum(value.strip() == 'Puntual' for value in states) == 8
        assert sum(value.strip() == 'Amb retard' for value in states) == 12
        page.screenshot(path=str(output / 'supplier-otd-lines.png'), full_page=True)

        empty_id = rpc('res.partner', 'create', [{'name': '[UI TEST] Sense dades', 'supplier_rank': 1}])
        try:
            page.goto(overview, wait_until='domcontentloaded')
            expect(rows).to_have_count(11)
            expect(rows.last.locator('td[name="supplier_otd_display"]')).to_have_text('Sense dades')
        finally:
            rpc('res.partner', 'unlink', [[empty_id]])
        assert not errors, errors
        result = {
            'action_id': action_id, 'native_heading_sort_asc_desc': True,
            'vendor_forms_verified': 10, 'percentages': checked, 'under_50_filter_rows': 4,
            'drilldown_rows': 20, 'drilldown_on_time': 8, 'drilldown_late': 12,
            'native_progressbar_visible': True, 'progress_track_min_width': min(progress_widths),
            'standard_indicator_visible_only_outside_evaluation': True,
            'supplier05': {'evaluated': 20, 'on_time': 10, 'late': 10, 'detail_columns_verified': True}, 'no_data_badge_verified': True, 'page_errors': errors,
        }
        (output / 'browser-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)
        browser.close()


if __name__ == '__main__':
    main()
