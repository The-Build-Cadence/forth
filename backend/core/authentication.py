"""One identity lookup for browser and MCP credential authentication."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class AccountBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        identity = username.strip()
        User = get_user_model()
        # Refuse ambiguous legacy emails instead of choosing an arbitrary account.
        users = list(User.objects.filter(
            Q(username__iexact=identity) | Q(email__iexact=identity)
        )[:2])
        if len(users) != 1:
            User().set_password(password)
            return None
        user = users[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
