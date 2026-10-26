from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Application, ApplicationEvent, JobPosting


class ApplicationAgeTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='age')
        self.job = JobPosting.objects.create(owner=self.owner, title='Engineer', content_hash='age')
        self.app = Application.objects.create(owner=self.owner, job=self.job)

    def test_only_actual_persisted_status_changes_reset_age(self):
        original = self.app.status_entered_at
        later = original + timedelta(days=5)
        with patch('core.models.timezone.now', return_value=later):
            self.app.notes = 'A note'
            self.app.save()
            self.assertEqual(self.app.status_entered_at, original)
            self.app.status = 'review'
            self.app.save(update_fields=['notes'])
            self.app.refresh_from_db()
            self.assertEqual(self.app.status, 'saved')
            self.assertEqual(self.app.status_entered_at, original)
            self.app.status = 'review'
            self.app.save(update_fields=['status'])
            self.app.refresh_from_db()
            self.assertEqual(self.app.status_entered_at, later)
            self.app.status = 'saved'
            self.app.save(update_fields=['status'])
            self.assertEqual(self.app.status_entered_at, later)

    def test_api_exposes_but_cannot_override_age(self):
        api = APIClient()
        api.force_authenticate(self.owner)
        original = self.app.status_entered_at
        response = api.patch(f'/api/applications/{self.app.pk}/', {'notes': 'Updated', 'status_entered_at': '2000-01-01T00:00:00Z', 'status_age_estimated': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status_entered_at, original)
        self.assertFalse(self.app.status_age_estimated)
        response = api.get('/api/applications/')
        self.assertIn('status_entered_at', response.data['results'][0])

    def test_backfill_uses_matching_event_and_labels_fallback(self):
        migration = import_module('core.migrations.0022_application_status_age')
        migration.backfill(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        self.app.refresh_from_db()
        self.assertTrue(self.app.status_age_estimated)
        entered = timezone.now() - timedelta(days=3)
        ApplicationEvent.objects.create(owner=self.owner, application=self.app, event_type='status_changed', happened_at=entered, notes='Status changed from review to saved.')
        migration.backfill(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        self.app.refresh_from_db()
        self.assertEqual(self.app.status_entered_at, entered)
        self.assertFalse(self.app.status_age_estimated)
        self.app.status = 'applied'
        self.app.save(update_fields=['status'])
        self.app.refresh_from_db()
        self.assertFalse(self.app.status_age_estimated)
        self.assertGreater(self.app.status_entered_at, entered)
