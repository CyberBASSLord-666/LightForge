"""Private assets and native results must use the exact navigation origin."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'android/src/com/cyberbasslord/lightforge'
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'


class AppOriginTest(unittest.TestCase):
    def test_all_interceptors_and_navigation_share_policy(self):
        resources = (SOURCE / 'AppResources.java').read_text()
        self.assertIn('AppOrigin.trusted(uri.getScheme(),uri.getEncodedAuthority())', resources)
        self.assertIn('if(!trustedOrigin(uri))return response(403', resources)
        service = (SOURCE / 'AnalysisService.java').read_text()
        self.assertEqual(service.count('if(AppResources.trustedOrigin(uri)&&nativePath'), 2)
        self.assertIn('if(AppResources.trustedOrigin(uri)) return false;',
                      (SOURCE / 'MainActivity.java').read_text())

    def test_active_browser_servers_keep_local_request_guard(self):
        import json
        files = ['qa/release-2.4.1/browser.cjs', 'qa/release-2.4.1/analysis-browser.cjs',
                 'qa/release-2.4.1/background-ui.cjs', 'qa/restore-preview/browser.cjs',
                 'qa/locked-benchmark/capture-app.cjs', 'tools/verify_preview_browser.cjs']
        for name in files:
            source = (ROOT / name).read_text()
            self.assertIn('local-http-security.cjs', source, name)
            self.assertRegex(source, r'if\s*\(\s*!allowLocalRequest\(', name)
        inventory = json.loads((ROOT / 'qa/release-2.4.1/browser-source-inventory.json').read_text())
        self.assertIn('qa/locked-benchmark/local-http-security.cjs', inventory['common'])

    @unittest.skipUnless((JAVA / 'javac').is_file(), 'Host JDK required')
    def test_private_origin_policy(self):
        with tempfile.TemporaryDirectory(prefix='lightforge-origin-') as classes:
            subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', classes,
                            str(SOURCE / 'AppOrigin.java'), str(ROOT / 'tests/AppOriginTest.java')],
                           check=True, capture_output=True, text=True, timeout=60)
            result = subprocess.run([str(JAVA / 'java'), '-cp', classes,
                                     'com.cyberbasslord.lightforge.AppOriginTest'],
                                    check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PASS: exact private WebView origin checks', result.stdout)


if __name__ == '__main__':
    unittest.main()
