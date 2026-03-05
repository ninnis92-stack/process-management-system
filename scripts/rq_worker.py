"""Simple RQ worker runner for development.

Start with:

REDIS_URL=redis://redis:6379 flask run or use docker-compose; then:
python3 scripts/rq_worker.py
"""
import os
from redis import Redis
from rq import Worker, Queue, Connection

listen = ["emails"]

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
conn = Redis.from_url(redis_url)

if __name__ == "__main__":
    with Connection(conn):
        worker = Worker(map(Queue, listen))
        worker.work()
