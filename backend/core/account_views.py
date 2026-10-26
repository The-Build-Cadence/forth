import re

from django.conf import settings
from django.views.decorators.debug import sensitive_post_parameters
from django.utils.decorators import method_decorator
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .account_ai import cipher
from .models import AccountSettings, CandidateProfile


class DocumentDesignInput(serializers.Serializer):
    template = serializers.ChoiceField(choices=['modern', 'classic', 'minimal'])
    layout = serializers.ChoiceField(choices=['single', 'two_column'])
    font = serializers.ChoiceField(choices=['sans', 'humanist', 'serif'])
    density = serializers.ChoiceField(choices=['compact', 'balanced', 'spacious'])
    accent = serializers.RegexField(r'^#[0-9a-fA-F]{6}$')
    page_size = serializers.ChoiceField(choices=['Letter', 'A4'])
    max_pages = serializers.IntegerField(min_value=0, max_value=3)


class SettingsInput(serializers.Serializer):
    openai_api_key = serializers.CharField(required=False, allow_blank=False, max_length=512, write_only=True, trim_whitespace=True)
    remove_key = serializers.BooleanField(required=False, default=False)
    use_personal_ai = serializers.BooleanField(required=False)
    text_model = serializers.RegexField(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$', required=False, allow_blank=True)
    reasoning_effort = serializers.ChoiceField(choices=['', 'low', 'medium', 'high'], required=False)
    document_design = DocumentDesignInput(required=False)
    generation_instructions = serializers.CharField(required=False, allow_blank=True, max_length=6000)

    def validate(self, data):
        if data.get('remove_key') and data.get('openai_api_key'):
            raise serializers.ValidationError('Choose either replacing or removing the key.')
        if data.get('openai_api_key') and not data['openai_api_key'].startswith('sk-'):
            raise serializers.ValidationError({'openai_api_key': 'Enter an OpenAI API key beginning with sk-.'})
        return data


def snapshot(owner):
    config, _ = AccountSettings.objects.get_or_create(owner=owner)
    profile, _ = CandidateProfile.objects.get_or_create(owner=owner)
    from .domain.material_preferences import document_design
    return {'has_openai_key': bool(config.openai_key_encrypted), 'use_personal_ai': config.use_personal_ai,
            'text_model': config.text_model or settings.OPENAI_TEXT_MODEL, 'reasoning_effort': config.reasoning_effort,
            'default_text_model': settings.OPENAI_TEXT_MODEL, 'embedding_model': settings.OPENAI_EMBEDDING_MODEL,
            'generation_instructions': profile.generation_instructions,
            'document_design': document_design(owner),
            'email': owner.email, 'name': owner.get_full_name() or owner.get_username()}


@method_decorator(sensitive_post_parameters('openai_api_key'), name='dispatch')
class AccountSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(snapshot(request.user))

    def patch(self, request):
        serializer = SettingsInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        from django.db import transaction
        with transaction.atomic():
            config, _ = AccountSettings.objects.get_or_create(owner=request.user)
            config = AccountSettings.objects.select_for_update().get(pk=config.pk)
            if data.get('remove_key'):
                config.openai_key_encrypted = ''
                config.use_personal_ai = False
            if data.get('openai_api_key'):
                config.openai_key_encrypted = cipher().encrypt(data['openai_api_key'].encode()).decode()
            for field in ['use_personal_ai', 'text_model', 'reasoning_effort', 'document_design']:
                if field in data:
                    setattr(config, field, data[field])
            if data.get('remove_key'):
                config.use_personal_ai = False
            if config.use_personal_ai and not config.openai_key_encrypted:
                raise serializers.ValidationError('Add an OpenAI API key before enabling personal AI.')
            config.save()
            if 'generation_instructions' in data:
                profile, _ = CandidateProfile.objects.get_or_create(owner=request.user)
                profile.generation_instructions = data['generation_instructions']
                profile.save(update_fields=['generation_instructions', 'updated_at'])
        return Response(snapshot(request.user))


class AccountModelsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        config = AccountSettings.objects.filter(owner=request.user).first()
        if not config or not config.openai_key_encrypted:
            return Response({'detail': 'Save your API key first.'}, status=400)
        try:
            from openai import OpenAI
            key = cipher().decrypt(config.openai_key_encrypted.encode()).decode()
            with OpenAI(api_key=key, timeout=12, max_retries=0) as client:
                models = client.models.list()
            # The catalog does not guarantee Responses/structured-output support.
            names = sorted(m.id for m in models.data if re.match(r'^(gpt-|o[1-9])', m.id))
            return Response({'models': names})
        except Exception:
            return Response({'detail': 'Could not verify the saved key or list models. Check its permissions and try again.'}, status=400)


class DocumentDesignPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .domain.documents import document_html
        serializer = DocumentDesignInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample = '# Your name\nProfessional headline · City, Country\n\n## Profile\nA concise introduction to your experience and the value you bring.\n\n## Experience\n### Your most recent role\nCompany · 2022–Present\n- Led a team to deliver thoughtful, reliable products.\n- Improved processes and collaborated across teams.\n\n## Skills\nLeadership · Strategy · Communication\n\n## Education\nYour qualification · Institution'
        return Response({'html': document_html('Document style preview', sample, kind='resume', design=serializer.validated_data)})
