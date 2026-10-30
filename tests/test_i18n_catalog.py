"""Translation packaging checks without Odoo, external packages or a database."""
import ast
from pathlib import Path
import unittest
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / 'addons/supplier_evaluation/i18n'


def read_catalog(path):
    result = {}
    for block in path.read_text().split('\n\n'):
        key = value = None
        section = None
        for line in block.splitlines():
            if line.startswith('msgid '):
                key, section = ast.literal_eval(line[6:]), 'key'
            elif line.startswith('msgstr '):
                value, section = ast.literal_eval(line[7:]), 'value'
            elif line.startswith('"'):
                if section == 'key':
                    key += ast.literal_eval(line)
                elif section == 'value':
                    value += ast.literal_eval(line)
        if key is not None:
            if key in result:
                raise ValueError('Duplicate translation: ' + key)
            result[key] = value
    return result


class TestI18nCatalog(unittest.TestCase):
    def test_catalan_catalog_covers_every_exported_source_term(self):
        source = read_catalog(I18N / 'supplier_evaluation.pot')
        catalan = read_catalog(I18N / 'ca.po')
        self.assertEqual(set(source), set(catalan))
        self.assertTrue(all(value for key, value in catalan.items() if key))
        self.assertNotIn('#, fuzzy', (I18N / 'ca.po').read_text())
        self.assertIn('Language: ca_ES', catalan[''])
        self.assertIn('nplurals=2', catalan[''])

    def test_translated_markup_preserves_technical_attributes(self):
        for source, target in read_catalog(I18N / 'ca.po').items():
            if source.startswith('<'):
                original, translated = ElementTree.fromstring(source), ElementTree.fromstring(target)
                self.assertEqual([(node.tag, node.attrib) for node in original.iter()], [(node.tag, node.attrib) for node in translated.iter()])

    def test_core_interface_terms_have_english_source_and_catalan_translation(self):
        catalog = read_catalog(I18N / 'ca.po')
        for source, target in [('Supplier evaluation', 'Avaluació de proveïdors'), ('No data', 'Sense dades'), ('OTD below 50%', 'OTD inferior al 50 %'), ('Confirm renegotiation', 'Confirmar renegociació')]:
            self.assertEqual(catalog[source], target)
