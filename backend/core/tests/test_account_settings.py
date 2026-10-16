from types import SimpleNamespace as NS
from unittest.mock import patch, Mock

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core import ai
from core.account_ai import ai_credentials, cipher, text_model
from core.models import AccountSettings, ProviderUsage
from core.usage import usage_context


@override_settings(ACCOUNT_ENCRYPTION_KEY=Fernet.generate_key().decode(), OPENAI_API_KEY='sk-shared-test')
class AccountSettingsTests(TestCase):
    def setUp(self):
        self.alice = get_user_model().objects.create_user(username='alice-settings', email='alice@example.com')
        self.bob = get_user_model().objects.create_user(username='bob-settings')
        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    def save_key(self):
        return self.client.patch('/api/account/settings/', {'openai_api_key': 'sk-personal-secret-test', 'use_personal_ai': True,
                                'text_model': 'gpt-test-powerful', 'reasoning_effort': 'high'}, format='json')

    def test_encrypted_write_only_credential_and_account_isolation(self):
        response = self.save_key()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['has_openai_key'])
        self.assertNotIn('sk-personal', str(response.data))
        stored = AccountSettings.objects.get(owner=self.alice).openai_key_encrypted
        self.assertNotIn('sk-personal', stored)
        self.assertEqual(cipher().decrypt(stored.encode()), b'sk-personal-secret-test')
        self.client.force_authenticate(self.bob)
        self.assertFalse(self.client.get('/api/account/settings/?owner=' + str(self.alice.id)).data['has_openai_key'])
        with usage_context(self.alice):
            self.assertEqual(ai_credentials()[0], 'sk-personal-secret-test')
            self.assertEqual(text_model(), 'gpt-test-powerful')
        with usage_context(self.bob):
            self.assertEqual(ai_credentials()[0], 'sk-shared-test')

    def test_removal_returns_to_shared_ai_and_disabled_does_not_use_key(self):
        self.save_key()
        self.client.patch('/api/account/settings/', {'use_personal_ai': False}, format='json')
        with usage_context(self.alice):
            self.assertEqual(ai_credentials()[0], 'sk-shared-test')
        response = self.client.patch('/api/account/settings/', {'remove_key': True}, format='json')
        self.assertFalse(response.data['has_openai_key'])
        self.assertEqual(AccountSettings.objects.get(owner=self.alice).openai_key_encrypted, '')

    def test_no_key_no_personal_mode_and_auth_required(self):
        self.assertEqual(self.client.patch('/api/account/settings/', {'use_personal_ai': True}, format='json').status_code, 400)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/account/settings/').status_code, 401)

    @patch('core.ai._openai_available', return_value=True)
    @patch('openai.OpenAI')
    def test_personal_model_and_reasoning_are_used_and_metered(self, sdk, _):
        self.save_key()
        sdk.return_value.responses.create.return_value = NS(output_text='{}', model='gpt-test-powerful', usage=NS(input_tokens=10, output_tokens=2))
        with usage_context(self.alice, 'scheduled'):
            result = ai.generate_json('system', 'user')
        self.assertEqual(result.source, 'openai')
        self.assertEqual(sdk.call_args.kwargs['api_key'], 'sk-personal-secret-test')
        self.assertEqual(sdk.return_value.responses.create.call_args.kwargs['model'], 'gpt-test-powerful')
        self.assertEqual(sdk.return_value.responses.create.call_args.kwargs['reasoning'], {'effort': 'high'})
        self.assertEqual(ProviderUsage.objects.get().credential_source, 'personal')
        self.assertEqual(ProviderUsage.objects.get().owner, self.alice)

    def test_provider_backoff_does_not_affect_another_account(self):
        with usage_context(self.alice):
            ai._back_off_openai()
            self.assertFalse(ai._openai_available())
        with usage_context(self.bob):
            self.assertTrue(ai._openai_available())
        ai._OPENAI_BACKOFF_UNTIL.clear()

    @patch('openai.OpenAI')
    def test_key_verification_errors_never_echo_credentials(self, sdk):
        self.save_key()
        sdk.side_effect = RuntimeError('secret sk-personal-secret-test')
        response = self.client.get('/api/account/models/')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('sk-personal', str(response.data))


from django.test import SimpleTestCase
from tempfile import TemporaryDirectory
from pathlib import Path


class CredentialKeyStorageTests(SimpleTestCase):
    def test_generated_key_is_private_persistent_and_reused(self):
        with TemporaryDirectory() as directory, override_settings(ACCOUNT_ENCRYPTION_KEY='', DATA_DIR=Path(directory)):
            encrypted = cipher().encrypt(b'sk-test-only')
            self.assertEqual(cipher().decrypt(encrypted), b'sk-test-only')
            key_file = Path(directory) / '.account-credentials.key'
            self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
