import base64
import hashlib
import json
import os
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import Application as OAuthApplication, AccessToken
from rest_framework.test import APIClient

from core.models import CandidateProfile, JobPosting, JobMatch
from core.oauth import mcp_resource
from mcp_server import _owner, authenticated_owner, handle_request, ToolError


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class MCPAuthenticationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.alice = User.objects.create_user(username='alice', email='alice@example.com', password='test-password')
        self.bob = User.objects.create_user(username='bob', email='bob@example.com', password='other-password')
        self.job = JobPosting.objects.create(owner=self.bob, title='Private Bob job', content_hash='bob')
        CandidateProfile.objects.create(owner=self.alice, headline='Alice private profile')
        CandidateProfile.objects.create(owner=self.bob, headline='Bob private profile')
        self.app = OAuthApplication.objects.create(
            name='Test ChatGPT', client_id='test-client', client_type='public',
            authorization_grant_type='authorization-code',
            redirect_uris='https://chatgpt.com/connector_platform_oauth_redirect',
        )
        self.api = APIClient()

    def rpc(self, tool, args=None):
        return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': tool, 'arguments': args or {}}}

    def token(self, owner, **kwargs):
        value = f'token-{owner.pk}-{AccessToken.objects.count()}'
        data = dict(user=owner, application=self.app, token=value,
                    expires=timezone.now() + timedelta(hours=1),
                    scope='forth:access', resource=[mcp_resource()])
        data.update(kwargs)
        AccessToken.objects.create(**data)
        return value

    def call(self, token, body):
        return self.api.post('/mcp/', body, format='json',
                             HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_HOST='localhost:8021')

    def test_credentials_and_legacy_selectors(self):
        with patch.dict(os.environ, {'FORTH_MCP_OWNER_EMAIL': self.bob.email}, clear=True):
            with self.assertRaises(ToolError):
                _owner()
        for password, allowed in [('wrong', False), ('test-password', True)]:
            with patch.dict(os.environ, {'FORTH_MCP_USERNAME': 'ALICE@example.com',
                                        'FORTH_MCP_PASSWORD': password}, clear=True):
                if allowed:
                    self.assertEqual(_owner(), self.alice)
                else:
                    with self.assertRaises(ToolError):
                        _owner()
        self.alice.is_active = False
        self.alice.save()
        self.assertIsNone(authenticate(username=self.alice.email, password='test-password'))

    def test_ambiguous_email_fails_closed(self):
        self.bob.email = self.alice.email
        self.bob.save()
        self.assertIsNone(authenticate(username=self.alice.email, password='test-password'))

    def test_local_context_is_reset_and_foreign_ids_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with authenticated_owner(self.alice):
                result = handle_request(self.rpc('get_application_materials', {'job_id': self.job.pk}))
                self.assertTrue(result['result']['isError'])
            with self.assertRaises(ToolError):
                _owner()

    def test_remote_requests_cannot_choose_or_retain_another_account(self):
        for owner in [self.alice, self.bob, self.alice]:
            response = self.call(self.token(owner), self.rpc('get_candidate_context', {'owner_id': self.bob.pk}))
            self.assertEqual(response.status_code, 200, response.content)
            content = json.loads(response.json()['result']['content'][0]['text'])
            self.assertEqual(content['profile']['headline'], f'{owner.username.title()} private profile')
        response = self.call(self.token(self.alice), self.rpc('search_jobs'))
        self.assertEqual(json.loads(response.json()['result']['content'][0]['text'])['jobs'], [])

    def test_reject_missing_expired_wrong_audience_scope_and_inactive_tokens(self):
        response = self.api.post('/mcp/', self.rpc('search_jobs'), format='json')
        self.assertEqual(response.status_code, 401)
        self.assertIn('resource_metadata=', response['WWW-Authenticate'])
        for kwargs in [{'expires': timezone.now() - timedelta(seconds=1)},
                       {'scope': 'unrelated'}, {'resource': []},
                       {'resource': ['https://another.example/mcp/']}]:
            response = self.call(self.token(self.alice, **kwargs), self.rpc('search_jobs'))
            self.assertEqual(response.status_code, 401, response.content)
        token = self.token(self.alice)
        self.alice.is_active = False
        self.alice.save()
        self.assertEqual(self.call(token, self.rpc('search_jobs')).status_code, 401)

    def test_mcp_fit_thresholds_are_account_scoped_and_use_raw_scores(self):
        for owner, minimum in [(self.alice, 60), (self.bob, 80)]:
            CandidateProfile.objects.filter(owner=owner).update(minimum_match_score=minimum)
            token = self.token(owner)
            context = self.call(token, self.rpc('get_candidate_context')).json()
            self.assertEqual(json.loads(context['result']['content'][0]['text'])['profile']['minimum_match_score'], minimum)
            for score in [minimum - 1, minimum, minimum + 1]:
                job = JobPosting.objects.create(owner=owner, title=f'Fit {score}', content_hash=f'{owner.pk}-{score}')
                JobMatch.objects.create(owner=owner, job=job, score=score)
            response = self.call(token, self.rpc('search_jobs', {'min_score': minimum - 1})).json()
            jobs = json.loads(response['result']['content'][0]['text'])['jobs']
            self.assertEqual(len(jobs), 3)
            self.assertEqual([job['match']['meets_profile_threshold'] for job in jobs], [True, True, False])
            self.assertTrue(all(job['match']['profile_minimum_score'] == minimum for job in jobs))
            self.assertEqual(jobs[1]['match']['normalized_score'], 80)
            filtered = self.call(token, self.rpc('search_jobs', {'min_score': minimum})).json()
            self.assertEqual(len(json.loads(filtered['result']['content'][0]['text'])['jobs']), 2)

    def test_origin_and_discovery(self):
        response = self.api.post('/mcp/', self.rpc('search_jobs'), format='json', HTTP_ORIGIN='https://evil.example')
        self.assertEqual(response.status_code, 403)
        metadata = self.api.get('/.well-known/oauth-protected-resource').json()
        self.assertEqual(metadata['resource'], mcp_resource())
        server = self.api.get('/.well-known/oauth-authorization-server').json()
        self.assertEqual(server['code_challenge_methods_supported'], ['S256'])
        self.assertTrue(server['client_id_metadata_document_supported'])

    def authorize(self, **overrides):
        verifier = 'v' * 64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        params = dict(client_id=self.app.client_id, redirect_uri=self.app.redirect_uris,
                      response_type='code', scope='forth:access', state='test-state',
                      code_challenge=challenge, code_challenge_method='S256', resource=mcp_resource())
        params.update(overrides)
        self.client.force_login(self.alice)
        response = self.client.get('/oauth/authorize/', params)
        self.assertEqual(response.status_code, 200, response.content)
        return self.client.post('/oauth/authorize/', {**params, 'allow': 'Authorize'}), verifier

    def test_oauth_pkce_end_to_end_refresh_and_revocation(self):
        response, verifier = self.authorize()
        self.assertEqual(response.status_code, 302, response.content)
        query = parse_qs(urlsplit(response.url).query)
        self.assertEqual(query['state'], ['test-state'])
        self.assertEqual(query['iss'], ['http://localhost:8021'])
        payload = dict(grant_type='authorization_code', code=query['code'][0],
                       client_id=self.app.client_id, redirect_uri=self.app.redirect_uris,
                       code_verifier=verifier, resource=mcp_resource())
        wrong = self.client.post('/oauth/token/', {**payload, 'code_verifier': 'x' * 64})
        self.assertEqual(wrong.status_code, 400)
        response = self.client.post('/oauth/token/', payload)
        self.assertEqual(response.status_code, 200, response.content)
        token = response.json()
        self.assertEqual(self.call(token['access_token'], self.rpc('get_candidate_context')).status_code, 200)
        self.assertEqual(self.client.post('/oauth/token/', payload).status_code, 400)
        refreshed = self.client.post('/oauth/token/', dict(grant_type='refresh_token',
            refresh_token=token['refresh_token'], client_id=self.app.client_id, resource=mcp_resource()))
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        access = refreshed.json()['access_token']
        self.client.post('/oauth/revoke_token/', {'token': access, 'client_id': self.app.client_id})
        self.assertEqual(self.call(access, self.rpc('search_jobs')).status_code, 401)

    def test_wrong_resource_cannot_be_authorized(self):
        response, _ = self.authorize(resource='https://other.example/mcp/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(response.url).query)['error'], ['invalid_target'])

    def test_chatgpt_plural_cimd_pkce_refresh_and_revocation(self):
        self.app.client_id = 'https://chatgpt.com/oauth/test-client/client.json'
        metadata = {
            'client_id': self.app.client_id,
            'redirect_uris': [self.app.redirect_uris],
            'token_endpoint_auth_method': 'private_key_jwt',
            'token_endpoint_auth_methods_supported': ['none', 'private_key_jwt'],
            'grant_types': ['authorization_code', 'refresh_token'],
        }
        with patch('oauth2_provider.cimd.SafeMetadataFetcher.fetch', return_value=(metadata, 300)):
            self.test_oauth_pkce_end_to_end_refresh_and_revocation()
        registered = OAuthApplication.objects.get(client_id=self.app.client_id)
        self.assertEqual(registered.client_type, 'public')

    def test_cimd_rejects_unsupported_or_malformed_auth_methods(self):
        from core.oauth import ForthCIMDMetadataFetcher
        from oauth2_provider.cimd import CIMDError
        for methods in [['private_key_jwt'], [], 'none', None, ['none', 1]]:
            with self.subTest(methods=methods):
                metadata = {'token_endpoint_auth_methods_supported': methods}
                with patch('oauth2_provider.cimd.SafeMetadataFetcher.fetch', return_value=(metadata, 300)):
                    with self.assertRaises(CIMDError):
                        ForthCIMDMetadataFetcher().fetch('https://chatgpt.com/oauth/test/client.json')

    def test_oauth_cookie_cannot_authenticate_web_api_or_mcp(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get('/api/profile/').status_code, 401)
        self.assertEqual(self.client.post('/mcp/', self.rpc('search_jobs'), content_type='application/json').status_code, 401)

    def test_oauth_login_uses_email_and_preserves_redirect(self):
        response = self.client.post('/oauth/login/', {
            'username': 'ALICE@example.com', 'password': 'test-password', 'next': '/oauth/authorize/',
        })
        self.assertRedirects(response, '/oauth/authorize/', fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.alice.pk)
        self.assertEqual(response['Cache-Control'], 'no-store')
