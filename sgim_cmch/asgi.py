"""
ASGI config for sgim_cmch project.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sgim_cmch.settings')
application = get_asgi_application()