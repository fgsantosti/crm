import os
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_application = get_asgi_application()

# WebSocket routes remain closed until ticket authentication is implemented.
application = ProtocolTypeRouter({
    "http": django_application,
    "websocket": URLRouter([]),
})
