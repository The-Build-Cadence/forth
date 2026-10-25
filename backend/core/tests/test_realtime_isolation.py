from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from core.consumers import RealtimeConsumer
from core.realtime_events import user_group_name


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class RealtimeIsolationTests(TransactionTestCase):
    def test_only_authenticated_accounts_receive_their_events(self):
        owner = get_user_model().objects.create_user(username='ws-owner')
        other = get_user_model().objects.create_user(username='ws-other')
        token = str(AccessToken.for_user(owner))

        async def scenario():
            anonymous = WebsocketCommunicator(RealtimeConsumer.as_asgi(), '/ws/realtime/')
            connected, code = await anonymous.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4401)
            await anonymous.disconnect()
            socket = WebsocketCommunicator(RealtimeConsumer.as_asgi(), f'/ws/realtime/?token={token}&owner={other.pk}')
            connected, _ = await socket.connect()
            self.assertTrue(connected)
            layer = get_channel_layer()
            await layer.group_send(user_group_name(other.pk), {'type': 'realtime.event', 'message': {'private': 'other'}})
            self.assertTrue(await socket.receive_nothing(timeout=0.02))
            await layer.group_send(user_group_name(owner.pk), {'type': 'realtime.event', 'message': {'private': 'owner'}})
            self.assertEqual(await socket.receive_json_from(), {'private': 'owner'})
            await socket.disconnect()
        async_to_sync(scenario)()

    @override_settings(ALLOWED_HOSTS=['forth.example'])
    def test_websocket_origin_boundary_rejects_foreign_sites(self):
        from channels.security.websocket import AllowedHostsOriginValidator
        owner = get_user_model().objects.create_user(username='ws-origin')
        token = str(AccessToken.for_user(owner))
        app = AllowedHostsOriginValidator(RealtimeConsumer.as_asgi())
        async def scenario():
            for origin, expected in [(b'https://evil.example', False), (b'https://forth.example', True)]:
                socket = WebsocketCommunicator(app, f'/ws/realtime/?token={token}', headers=[(b'origin', origin)])
                connected, _ = await socket.connect()
                self.assertEqual(connected, expected)
                await socket.disconnect()
        async_to_sync(scenario)()
