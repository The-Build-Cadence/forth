from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from core import ai
from core.models import JobSource, ProviderUsage, SourceRun
from core.tasks import execute_source_run_task, refresh_enabled_sources_task
from core.usage import brave_request, openai_request, usage_context, usage_summary


class UsageTests(TestCase):
    def setUp(self):
        self.alice = get_user_model().objects.create_user(username='usage-alice')
        self.bob = get_user_model().objects.create_user(username='usage-bob')
        self.response = NS(model='gpt-4.1-mini-2025-04-14', output_text='{}',
                           usage=NS(input_tokens=1000, output_tokens=200,
                                    input_tokens_details=NS(cached_tokens=400)))

    def generate(self):
        return openai_request(Mock(return_value=self.response), operation='text_generation', model='gpt-4.1-mini')

    def test_cached_input_is_not_double_billed_and_rate_is_snapshotted(self):
        with usage_context(self.alice):
            self.generate()
        entry = ProviderUsage.objects.get()
        self.assertEqual(entry.owner, self.alice)
        self.assertEqual(entry.cost_usd, Decimal('0.0006'))
        self.assertEqual(entry.cached_tokens, 400)
        self.assertEqual(entry.rates, ['0.40', '0.10', '1.60'])

    def test_unknown_model_and_missing_usage_are_not_zero_cost(self):
        with usage_context(self.alice):
            self.response.model = 'unknown-model'
            self.generate()
            self.response = NS(model='gpt-4.1-mini')
            self.generate()
        self.assertEqual(ProviderUsage.objects.filter(cost_usd__isnull=True).count(), 2)

    def test_failure_is_recorded_and_no_unowned_request_is_sent(self):
        create = Mock(side_effect=TimeoutError('sensitive request content'))
        with usage_context(self.alice), self.assertRaises(TimeoutError):
            openai_request(create, operation='embedding')
        entry = ProviderUsage.objects.get()
        self.assertEqual(entry.status, 'failed')
        self.assertEqual(entry.error_type, 'TimeoutError')
        self.assertIsNone(entry.cost_usd)
        create.reset_mock()
        with self.assertRaises(ValueError):
            openai_request(create, operation='embedding')
        create.assert_not_called()

    @patch('core.ai._openai_available', return_value=True)
    @patch('core.ai.openai_client')
    def test_invalid_output_still_counts_and_local_fallback_does_not(self, factory, _):
        self.response.output_text = 'not JSON'
        factory.return_value.responses.create.return_value = self.response
        with usage_context(self.alice):
            self.assertIsNone(ai.generate_json('system', 'user'))
            factory.return_value = None
            ai.embed_text_result('text')
        self.assertEqual(ProviderUsage.objects.count(), 1)
        self.assertEqual(ProviderUsage.objects.get().cost_usd, Decimal('0.0006'))

    @patch('core.ai._openai_available', return_value=True)
    @patch('core.ai.openai_client')
    def test_embedding_usage(self, factory, _):
        factory.return_value.embeddings.create.return_value = NS(
            data=[NS(embedding=[0.2] * 3072)], usage=NS(prompt_tokens=1000), model='text-embedding-3-large')
        with usage_context(self.alice):
            self.assertEqual(ai.embed_text_result('test').provider, 'openai')
        self.assertEqual(ProviderUsage.objects.get().cost_usd, Decimal('0.00013'))

    @override_settings(BRAVE_COST_PER_1000_REQUESTS='3')
    def test_search_counts_requests_not_number_of_results(self):
        brave_request(Mock(return_value=Mock()), owner=self.bob, url='https://example.com')
        entry = ProviderUsage.objects.get()
        self.assertEqual(entry.owner, self.bob)
        self.assertEqual(entry.cost_usd, Decimal('0.003'))

    def test_scheduled_worker_uses_source_owner_and_isolates_context(self):
        source = JobSource.objects.create(owner=self.bob, name='Brave', kind='brave')
        run = SourceRun.objects.create(owner=self.bob, source=source)
        with patch('core.domain.sourcing.execute_source_run', side_effect=lambda run: self.generate()), patch('core.tasks.publish_user_event'):
            with usage_context(self.alice):
                execute_source_run_task(run.pk, origin='scheduled')
                self.generate()
        self.assertEqual(list(ProviderUsage.objects.order_by('id').values_list('owner_id', 'origin')),
                         [(self.bob.pk, 'scheduled'), (self.alice.pk, 'web')])
        run.status = 'succeeded'
        run.save(update_fields=['status'])
        with patch('core.tasks.execute_source_run_task.delay') as delay:
            refresh_enabled_sources_task()
        self.assertEqual(delay.call_args.kwargs['origin'], 'scheduled')

    def test_summary_filters_account_and_month_and_requires_authentication(self):
        with usage_context(self.alice):
            self.generate()
        ProviderUsage.objects.update(created_at=timezone.now().replace(day=1) - timedelta(days=1))
        with usage_context(self.bob):
            self.generate()
            self.generate()
        api = APIClient()
        self.assertEqual(api.get('/api/usage/').status_code, 401)
        api.force_authenticate(self.alice)
        data = api.get('/api/usage/?owner=' + str(self.bob.pk)).data
        self.assertEqual(data['providers']['openai']['requests'], 1)
        self.assertEqual(data['providers']['openai']['month_requests'], 0)
        self.assertEqual(data['providers']['openai']['cost_usd'], '0.00060000')

    def test_jwt_authenticated_http_request_attributes_usage(self):
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION='Bearer ' + str(AccessToken.for_user(self.alice)))
        def read_summary(owner):
            self.generate()
            return usage_summary(owner)
        with patch('core.usage_views.usage_summary', side_effect=read_summary):
            self.assertEqual(api.get('/api/usage/').status_code, 200)
        self.assertEqual(ProviderUsage.objects.get().owner, self.alice)

    def test_mcp_uses_authenticated_account(self):
        from mcp_server import authenticated_owner, handle_request
        with authenticated_owner(self.bob), patch.dict('mcp_server.TOOLS', {'usage_test': ('test', {}, lambda args: (self.generate(), {})[1])}):
            result = handle_request({'id': 1, 'method': 'tools/call', 'params': {'name': 'usage_test'}})
        self.assertNotIn('error', result)
        self.assertEqual(ProviderUsage.objects.get().owner, self.bob)
        self.assertEqual(ProviderUsage.objects.get().origin, 'mcp')


from django.db import connection, transaction
from django.test import TransactionTestCase
from unittest import skipUnless


@skipUnless(connection.vendor == 'postgresql', 'Independent accounting commits require PostgreSQL')
@override_settings(USAGE_DATABASE_ALIAS='usage')
class PostgresUsageDurabilityTests(TransactionTestCase):
    databases = {'default', 'usage'}

    def test_usage_survives_workflow_rollback(self):
        owner = get_user_model().objects.create_user(username='durability-test')
        try:
            with usage_context(owner), transaction.atomic():
                JobSource.objects.create(owner=owner, name='Will roll back', kind='brave')
                brave_request(Mock(return_value=Mock()), owner=owner, url='https://example.com')
                raise RuntimeError('workflow failure after provider response')
        except RuntimeError:
            pass
        self.assertFalse(JobSource.objects.filter(owner=owner).exists())
        self.assertEqual(ProviderUsage.objects.get(owner=owner).cost_usd, Decimal('0.005'))
