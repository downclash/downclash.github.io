"""Protect the existing production hostname from accidental publishing changes."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('site_audit', ROOT / 'scripts/audit_seo.py')
audit = importlib.util.module_from_spec(SPEC)
# dataclasses resolves module annotations through sys.modules.
import sys
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


class SiteDomainTests(unittest.TestCase):
    def test_preserves_the_existing_production_hostname(self):
        self.assertEqual((ROOT / 'CNAME').read_text().strip(), 'v2raydown.com')
        sitemap = ET.parse(ROOT / 'sitemap.xml')
        locations = sitemap.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
        self.assertTrue(locations)
        self.assertEqual({urlsplit(node.text).hostname for node in locations}, {'v2raydown.com'})

    def test_audit_rejects_an_accidental_cname_change(self):
        read_text = Path.read_text

        def changed_domain(path, *args, **kwargs):
            if path == ROOT / 'CNAME':
                return 'example.invalid\n'
            return read_text(path, *args, **kwargs)

        with patch.object(Path, 'read_text', changed_domain):
            result = audit.audit()
        self.assertTrue(any('CNAME must preserve the production domain' in error for error in result['errors']))


if __name__ == '__main__':
    unittest.main()
