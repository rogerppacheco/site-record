release: playwright install && python manage.py migrate
web: gunicorn gestao_equipes.wsgi --timeout 600 --max-requests 50 --max-requests-jitter 10