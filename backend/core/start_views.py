"""Small, resumable setup and one-click discovery. No claims are verified here."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .domain.profiles import candidate_profile
from .models import CandidateProfile, JobSource, ProfileDocument, SourceRun
from .serializers import CandidateProfileSerializer, SourceRunSerializer
from .tasks import execute_source_run_task


class SearchSetupSerializer(serializers.Serializer):
    intent = serializers.ChoiceField(choices=['discover', 'apply'])
    target_roles = serializers.ListField(child=serializers.CharField(max_length=100), min_length=1, max_length=5)
    location = serializers.CharField(max_length=220)
    work_modes = serializers.ListField(child=serializers.ChoiceField(choices=['remote', 'hybrid', 'onsite']), min_length=1, max_length=3)
    authorized_countries = serializers.ListField(child=serializers.CharField(max_length=100), max_length=10, default=list)
    daily = serializers.BooleanField(default=False)


class SetupDraftSerializer(serializers.Serializer):
    intent = serializers.ChoiceField(choices=['discover', 'apply'])
    step = serializers.IntegerField(min_value=1, max_value=3)
    roles = serializers.CharField(max_length=500, allow_blank=True)
    location = serializers.CharField(max_length=220, allow_blank=True)
    countries = serializers.CharField(max_length=500, allow_blank=True)
    work_modes = serializers.ListField(child=serializers.ChoiceField(choices=['remote', 'hybrid', 'onsite']), max_length=3)
    daily = serializers.BooleanField()


def start_snapshot(owner):
    profile = candidate_profile(owner)
    document = ProfileDocument.objects.filter(owner=owner, kind='resume').order_by('-created_at', '-id').first()
    run = SourceRun.objects.filter(owner=owner, source__kind='brave').first()
    return {
        'profile': CandidateProfileSerializer(profile).data,
        'document': {'id': document.id, 'status': document.status, 'name': document.title, 'message': document.status_message} if document else None,
        'discovery_available': bool(settings.BRAVE_SEARCH_API_KEY),
        'run': SourceRunSerializer(run).data if run else None,
    }


class SearchSetupView(APIView):
    def get(self, request):
        return Response(start_snapshot(request.user))

    def patch(self, request):
        serializer = SetupDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate_profile(request.user)
        with transaction.atomic():
            profile = CandidateProfile.objects.select_for_update().get(owner=request.user)
            profile.onboarding_state = {**(profile.onboarding_state or {}), 'setup_draft': serializer.validated_data}
            profile.save(update_fields=['onboarding_state', 'updated_at'])
        return Response({'saved': True})

    def post(self, request):
        serializer = SearchSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        candidate_profile(request.user)
        with transaction.atomic():
            profile = CandidateProfile.objects.select_for_update().get(owner=request.user)
            for field in ['target_roles', 'location', 'work_modes', 'authorized_countries']:
                setattr(profile, field, data[field])
            profile.onboarding_state = {**(profile.onboarding_state or {}), 'quick_start': True, 'intent': data['intent'], 'daily': data['daily']}
            profile.onboarding_state.pop('setup_draft', None)
            profile.onboarding_completed_at = profile.onboarding_completed_at or timezone.now()
            profile.last_reviewed_at = timezone.now()
            profile.save()
            for source in JobSource.objects.filter(owner=request.user, kind='brave') if data['intent'] == 'discover' else []:
                source.enabled = data['daily']
                if data['daily']:
                    source.config = {**source.config, 'schedule_minutes': 1440}
                source.save(update_fields=['enabled', 'config', 'updated_at'])
        return Response(start_snapshot(request.user))


class StartDiscoveryView(APIView):
    def post(self, request):
        if not settings.BRAVE_SEARCH_API_KEY:
            return Response({'detail': 'Job search is temporarily unavailable. You can still add a job description.'}, status=503)
        profile = candidate_profile(request.user)
        if not profile.target_roles or not profile.location or not profile.work_modes:
            return Response({'detail': 'Confirm your role, location and work preferences first.'}, status=400)
        with transaction.atomic():
            # Serialize first-source creation and repeated clicks for this account.
            CandidateProfile.objects.select_for_update().get(pk=profile.pk)
            SourceRun.objects.filter(owner=request.user, source__kind='brave', status__in=['queued', 'running'], created_at__lt=timezone.now() - timedelta(minutes=20)).update(status='failed', completed_at=timezone.now())
            active = SourceRun.objects.filter(owner=request.user, source__kind='brave', status__in=['queued', 'running']).first()
            if active:
                return Response(SourceRunSerializer(active).data, status=202)
            recent = SourceRun.objects.filter(owner=request.user, source__kind='brave', created_at__gte=timezone.now() - timedelta(minutes=1)).exclude(status='failed').first()
            if recent:
                return Response(SourceRunSerializer(recent).data, status=200)
            source = JobSource.objects.filter(owner=request.user, kind='brave').first()
            if source is None:
                from .domain.search_criteria import static_search_criteria

                source = JobSource.objects.create(owner=request.user, kind='brave', name='My job search', enabled=bool(profile.onboarding_state.get('daily')), config={'country': 'ALL', 'schedule_minutes': 1440, 'max_candidates': 10, 'min_triage_score': 50, 'adaptive_search': False, 'static_criteria': static_search_criteria(request.user)})
            run = SourceRun.objects.create(owner=request.user, source=source)
            source.last_status = 'queued'
            source.last_message = 'Finding jobs using your saved preferences.'
            source.save(update_fields=['last_status', 'last_message', 'updated_at'])
        try:
            execute_source_run_task.delay(run.id)
        except Exception:
            run.status = 'failed'
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'completed_at'])
            source.last_status = 'failed'
            source.save(update_fields=['last_status'])
            return Response({'detail': 'Search could not start. Your preferences are saved; please try again.'}, status=503)
        return Response(SourceRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)
