"""Stateless MCP Streamable HTTP using per-request OAuth authentication."""
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.views import LoginView
from django.http import HttpResponse
from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView



class LoginThrottle(AnonRateThrottle):
    rate = '10/min'


class OAuthLoginView(LoginView):
    template_name = 'core/oauth_login.html'

    def post(self, request, *args, **kwargs):
        if not LoginThrottle().allow_request(request, self):
            return HttpResponse('Too many sign-in attempts. Please try again later.', status=429)
        return super().post(request, *args, **kwargs)


class MCPAuthentication(OAuth2Authentication):
    def authenticate_header(self, request):
        return f'Bearer resource_metadata="{settings.FORTH_PUBLIC_URL}/.well-known/oauth-protected-resource", scope="forth:access"'


class MCPView(APIView):
    authentication_classes = [MCPAuthentication]
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        origin = request.headers.get('Origin')
        public = urlsplit(settings.FORTH_PUBLIC_URL)
        if origin and origin != f'{public.scheme}://{public.netloc}':
            raise PermissionDenied('Origin is not allowed.')
        super().initial(request, *args, **kwargs)

    def post(self, request):
        from mcp_server import authenticated_owner, handle_request

        body = request.data
        if (not isinstance(body, dict) or body.get('jsonrpc') != '2.0'
                or not isinstance(body.get('method'), str)
                or not isinstance(body.get('params', {}), dict)):
            return Response({'jsonrpc': '2.0', 'id': None, 'error': {
                'code': -32600, 'message': 'Invalid Request',
            }}, status=400)
        with authenticated_owner(request.user):
            response = handle_request(body)
        if response is None:
            return Response(status=202)
        result = Response(response)
        result['Cache-Control'] = 'no-store'
        return result

    # No persistent streams or session IDs: every POST authenticates independently.
    def get(self, request):
        return Response(status=405)
