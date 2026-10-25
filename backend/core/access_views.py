"""Account recovery and explicit account deletion."""
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Artifact, ProfileDocument


class RecoveryView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'recovery'

    def post(self, request):
        form = PasswordResetForm(request.data)
        if not form.is_valid():
            return Response({'detail': 'Enter a valid email address.'}, status=400)
        if not settings.EMAIL_HOST and settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend':
            return Response({'detail': 'Email recovery is not configured. Contact the workspace operator for help.'}, status=503)
        public = urlsplit(settings.FORTH_PUBLIC_URL)
        try:
            form.save(domain_override=public.netloc, use_https=public.scheme == 'https',
                      from_email=settings.DEFAULT_FROM_EMAIL, email_template_name='core/reset_email.txt',
                      subject_template_name='core/reset_subject.txt')
        except Exception:
            return Response({'detail': 'Recovery email is temporarily unavailable. Please try again later.'}, status=503)
        return Response({'detail': 'If an account uses that email, a password reset link has been sent.'})


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'recovery'

    def post(self, request):
        try:
            user = get_user_model().objects.get(pk=force_str(urlsafe_base64_decode(request.data.get('uid', ''))), is_active=True)
        except (ValueError, TypeError, OverflowError, UnicodeDecodeError, get_user_model().DoesNotExist):
            user = None
        if not user or not default_token_generator.check_token(user, request.data.get('token', '')):
            return Response({'detail': 'This reset link has expired or has already been used. Request a new one.'}, status=400)
        form = SetPasswordForm(user, data={'new_password1': request.data.get('password', ''), 'new_password2': request.data.get('confirmation', '')})
        if not form.is_valid():
            return Response({'detail': ' '.join(message for messages in form.errors.values() for message in messages)}, status=400)
        form.save()
        return Response({'detail': 'Password updated. Sign in with your new password.'})


class DeleteAccountView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'recovery'

    def post(self, request):
        if request.data.get('confirmation') != 'DELETE' or not request.user.check_password(request.data.get('password', '')):
            return Response({'detail': 'Enter your current password and type DELETE to confirm.'}, status=400)
        files = [(item.upload.storage, item.upload.name) for item in ProfileDocument.objects.filter(owner=request.user) if item.upload]
        files += [(item.file.storage, item.file.name) for item in Artifact.objects.filter(owner=request.user) if item.file]
        with transaction.atomic():
            request.user.delete()
            for storage, name in files:
                transaction.on_commit(lambda storage=storage, name=name: storage.delete(name))
        return Response(status=204)


class PublicAccessView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        return Response({'invitation_required': bool(settings.FORTH_BETA_INVITE_CODE)})


from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.utils import get_md5_hash_password
from rest_framework_simplejwt.views import TokenRefreshView


class AccountTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = self.token_class(attrs['refresh'])
        try:
            user = get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: token.get(api_settings.USER_ID_CLAIM)}).first()
        except (TypeError, ValueError, OverflowError):
            user = None
        if not user or not user.is_active or (api_settings.CHECK_REVOKE_TOKEN and token.get(api_settings.REVOKE_TOKEN_CLAIM) != get_md5_hash_password(user.password)):
            raise AuthenticationFailed('Your session has ended. Please sign in again.')
        return super().validate(attrs)


class AccountTokenRefreshView(TokenRefreshView):
    serializer_class = AccountTokenRefreshSerializer
