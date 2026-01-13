release: playwright install && python manage.py migrate
web: gunicorn gestao_equipes.wsgi --timeout 1200 --graceful-timeout 1200 --keep-alive 5 --max-requests 50 --max-requests-jitter 10