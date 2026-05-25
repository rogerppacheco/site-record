release: playwright install && python manage.py migrate
web: gunicorn gestao_equipes.wsgi --timeout 1200 --graceful-timeout 1200 --keep-alive 5
scheduler: python manage.py run_scheduler