"""Host-side checks (no FreeCAD needed): python3 -m unittest discover -s tests"""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'config' / 'assembly.json').read_text())


class DesignFolder(unittest.TestCase):
    def test_config_has_no_dimensions(self):
        numbers = []

        def walk(v):
            if isinstance(v, bool):
                return
            if isinstance(v, (int, float)):
                numbers.append(v)
            elif isinstance(v, dict):
                [walk(x) for x in v.values()]
            elif isinstance(v, list):
                [walk(x) for x in v]
        walk(CFG)
        self.assertEqual(numbers, [], 'dimensions belong in the FreeCAD VarSet, not assembly.json')

    def test_validation_report_matches_saved_file(self):
        report = (ROOT / 'reports' / 'validation.md').read_text()
        digest = hashlib.sha256((ROOT / CFG['document']).read_bytes()).hexdigest()
        self.assertIn(digest, report, 'rerun scripts/verify.py: report is for a different .FCStd')

    def test_negative_controls_all_failed(self):
        report = (ROOT / 'reports' / 'validation.md').read_text()
        m = re.search(r'(\d+)/(\d+) negative controls fail as expected', report)
        self.assertTrue(m and m.group(1) == m.group(2), 'a check was never shown to fail')

    def test_exports_exist_for_every_part(self):
        for p in CFG['parts']:
            for ext in ('step', 'brep'):
                self.assertTrue((ROOT / 'exports' / f'equip-1-V0.1.0-{p["name"]}.{ext}').exists())

    def test_renders_and_mockup_exist(self):
        for v in ('hero', 'rear', 'ports', 'exploded', 'internals', 'mechanism', 'contact-sheet'):
            self.assertTrue((ROOT / 'renders' / f'{v}.png').exists(), v)
        self.assertTrue((ROOT / 'print-mockup' / 'equip-1-V0.1.0-feel.3mf').exists())


if __name__ == '__main__':
    unittest.main()
