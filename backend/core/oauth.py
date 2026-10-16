"""OAuth policies for Forth's single protected MCP resource."""
from django.conf import settings
from oauthlib.oauth2.rfc6749.errors import CustomOAuth2Error
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.cimd import CIMDError, SafeMetadataFetcher


class ForthCIMDMetadataFetcher(SafeMetadataFetcher):
    """Adapt plural CIMD auth methods to DOT's public-client-only resolver.

    ChatGPT publishes the singular field as a legacy preference (SEP-3149).
    Keep DOT's hardened fetch and metadata validation; only select `none`
    when the document explicitly advertises it in the supported-method list.
    """

    def fetch(self, client_id):
        metadata, max_age = super().fetch(client_id)
        if 'token_endpoint_auth_methods_supported' in metadata:
            methods = metadata['token_endpoint_auth_methods_supported']
            if (not isinstance(methods, list) or not methods
                    or not all(isinstance(method, str) for method in methods)):
                raise CIMDError('CIMD supported auth methods must be a non-empty array of strings')
            if 'none' not in methods:
                raise CIMDError('CIMD client does not support public-client authentication')
            metadata = {**metadata, 'token_endpoint_auth_method': 'none'}
        return metadata, max_age


def mcp_resource():
    return f'{settings.FORTH_PUBLIC_URL}/mcp/'


class ForthOAuth2Validator(OAuth2Validator):
    def validate_grant_type(self, client_id, grant_type, client, request, *args, **kwargs):
        return grant_type in {'authorization_code', 'refresh_token'} and super().validate_grant_type(
            client_id, grant_type, client, request, *args, **kwargs,
        )

    def save_authorization_code(self, client_id, code, request, *args, **kwargs):
        if getattr(request, 'resource', None) != [mcp_resource()]:
            raise CustomOAuth2Error(error='invalid_target', description='Request the Forth MCP resource.', request=request)
        return super().save_authorization_code(client_id, code, request, *args, **kwargs)

    def validate_bearer_token(self, token, scopes, request):
        if not super().validate_bearer_token(token, ['forth:access'], request):
            return False
        return bool(request.user and request.user.is_active and
                    request.access_token.resource == [mcp_resource()])

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        if not super().validate_refresh_token(refresh_token, client, request, *args, **kwargs):
            return False
        return bool(request.user and request.user.is_active)
