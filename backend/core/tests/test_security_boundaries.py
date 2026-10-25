import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from core.public_http import PublicAddressAdapter, public_addresses
from core.services import extract_text_from_upload


class PublicHTTPBoundaryTests(SimpleTestCase):
    def test_private_shared_and_metadata_destinations_are_rejected(self):
        for address in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '100.64.0.1', '::1', 'fc00::1', '0.0.0.0']:
            with self.subTest(address=address), patch('core.public_http.socket.getaddrinfo', return_value=[(None,None,None,None,(address,443))]):
                with self.assertRaises(ValueError):
                    public_addresses('https://example.com/')

    def test_credentials_protocols_and_custom_ports_are_rejected(self):
        for url in ['file:///etc/passwd', 'http://user:secret@example.com/', 'http://example.com:8000/']:
            with self.assertRaises(ValueError):
                public_addresses(url)

    def test_mixed_public_private_dns_is_rejected(self):
        with patch('core.public_http.socket.getaddrinfo', return_value=[(None,None,None,None,('8.8.8.8',443)),(None,None,None,None,('10.0.0.1',443))]):
            with self.assertRaises(ValueError):
                public_addresses('https://example.com/')

    def test_connection_uses_validated_ip_with_original_tls_hostname(self):
        adapter = PublicAddressAdapter()
        request = requests.Request('GET', 'https://example.com/jobs').prepare()
        with patch('core.public_http.socket.getaddrinfo', return_value=[(None,None,None,None,('8.8.8.8',443))]), patch.object(adapter.poolmanager, 'connection_from_host') as connect:
            adapter.get_connection_with_tls_context(request, True)
        self.assertEqual(connect.call_args.kwargs['host'], '8.8.8.8')
        self.assertEqual(connect.call_args.kwargs['pool_kwargs']['server_hostname'], 'example.com')
        self.assertEqual(connect.call_args.kwargs['pool_kwargs']['assert_hostname'], 'example.com')
        self.assertEqual(request.headers['Host'], 'example.com')


class UploadBoundaryTests(SimpleTestCase):
    def test_compressed_document_bomb_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'resume.docx'
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('word/document.xml', b'x' * (51 * 1024 * 1024))
            self.assertLess(path.stat().st_size, 1024 * 1024)
            with self.assertRaisesRegex(ValueError, 'safe processing limit'):
                extract_text_from_upload(str(path))

    def test_low_disk_space_refuses_persistent_writes(self):
        from types import SimpleNamespace
        from django.test import override_settings
        from core.storage_limits import require_storage_space
        with tempfile.TemporaryDirectory() as folder, override_settings(DATA_DIR=Path(folder)), patch('core.storage_limits.shutil.disk_usage', return_value=SimpleNamespace(free=100)):
            with self.assertRaisesRegex(ValueError, 'storage is temporarily full'):
                require_storage_space(200)
