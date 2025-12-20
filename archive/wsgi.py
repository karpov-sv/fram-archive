"""
WSGI config for archive project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os, sys

path = os.path.abspath(__file__)
path = os.path.split(path)[0]
path = os.path.split(path)[0]

sys.path.append(path)

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archive.settings')

application = get_wsgi_application()
