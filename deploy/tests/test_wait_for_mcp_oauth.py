import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wait_for_mcp_oauth', Path(__file__).parents[1] / 'wait-for-mcp-oauth.py')
wait = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wait)


class OAuthReadinessTests(unittest.TestCase):
    def test_both_metadata_endpoints_must_be_ready(self):
        with patch.object(wait, 'urlopen', side_effect=[
            io.StringIO('{"resource":"https://forth/mcp/","authorization_servers":["https://forth"]}'),
            io.StringIO('{"issuer":"https://forth","authorization_endpoint":"https://forth/authorize","token_endpoint":"https://forth/token"}'),
        ]) as fetch:
            self.assertTrue(wait.ready('https://forth/'))
            self.assertEqual(fetch.call_count, 2)

    def test_incomplete_metadata_is_not_ready(self):
        with patch.object(wait, 'urlopen', return_value=io.StringIO('{}')):
            self.assertFalse(wait.ready('https://forth'))

    def test_boot_outage_retries_until_available(self):
        with patch.object(wait.sys, 'argv', ['wait', 'https://forth']), patch.object(wait, 'ready', side_effect=[OSError('not listening'), False, True]) as probe, patch.object(wait.time, 'sleep') as sleep:
            self.assertEqual(wait.main(), 0)
            self.assertEqual(probe.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_timeout_fails_for_systemd_restart(self):
        with patch.object(wait.time, 'monotonic', side_effect=[0, 121]):
            self.assertEqual(wait.main(), 1)


if __name__ == '__main__':
    unittest.main()
