#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate
# Add this to the end of your build.sh
python manage.py shell <<EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='adhil_admin').exists():
    User.objects.create_superuser('adhil_admin', 'admin@example.com', 'Adhil@2026')
    print("Superuser created successfully!")
else:
    print("Superuser already exists.")
EOF