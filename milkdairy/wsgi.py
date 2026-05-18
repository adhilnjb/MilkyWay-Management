import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'milkdairy.settings')

# Get the standard WSGI handler
application = get_wsgi_application()

# ALIAS FOR VERCEL RUNTIME (Do not remove)
app = application