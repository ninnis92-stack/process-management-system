import multiprocessing

workers = (multiprocessing.cpu_count() * 2) + 1
worker_class = "gthread"
threads = 4
timeout = 30
keepalive = 2
preload_app = True
max_requests = 1000
max_requests_jitter = 50

# Recommended to set environment variables for logging and binding in deployment
# Example usage: `gunicorn -c gunicorn_conf.py run:app` (or via your process manager)
