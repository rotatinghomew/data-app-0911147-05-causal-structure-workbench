import os
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright

from app.service import create_server


class BrowserDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.server = create_server(state_dir=self.temporary.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def test_discovery_workflow_in_real_browser(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=['--no-sandbox'] if os.geteuid() == 0 else [])
            try:
                page = browser.new_page()
                page.set_default_timeout(15000)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.base, wait_until='networkidle')
                page.wait_for_function("document.querySelector('#summary').textContent !== '载入中'")
                page.locator('#run-discovery').click()
                page.wait_for_selector('#structure-graph')
                banner_all = page.locator('#population-banner').inner_text()
                self.assertIn('指纹', banner_all)
                self.assertIn('全部', banner_all)
                self.assertGreater(page.locator('#structure-graph .edge').count(), 0)
                page.locator('#structure-graph .edge .edge-hit').first.click()
                evidence = page.locator('#edge-evidence').inner_text()
                self.assertIn('检验证据', evidence)
                self.assertIn('关系详情', evidence)
                page.locator('#save-graph').click()
                page.wait_for_function(
                    "document.querySelector('#graphs').textContent.includes('指纹')")
                self.assertEqual(page.locator('#graphs li').count(), 1)
                page.select_option('#cohort', 'a')
                page.locator('#run-discovery').click()
                page.wait_for_function(
                    "document.querySelector('#population-banner') && "
                    "document.querySelector('#population-banner').textContent.includes('群体 a')")
                banner_a = page.locator('#population-banner').inner_text()
                self.assertNotEqual(banner_all, banner_a)
                page.reload(wait_until='networkidle')
                page.wait_for_function("document.querySelector('#summary').textContent !== '载入中'")
                self.assertEqual(page.locator('#graphs li').count(), 1)
                page.locator('#graphs button').click()
                page.wait_for_selector('#saved-view #structure-graph')
                self.assertIn('指纹', page.locator('#saved-view #population-banner').inner_text())
                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
