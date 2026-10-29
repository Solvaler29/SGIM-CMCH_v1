"""
WSGI config for sgim_cmch project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sgim_cmch.settings')
application = get_wsgi_application()