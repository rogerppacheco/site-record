release: playwright install && python manage.py migrate && python manage.py createcachetable
web: sh scripts/start_web.sh
scheduler: python manage.py run_scheduler