# Profiling & Query Tuning

Quick steps to find and mitigate DB and handler bottlenecks when scaling.

1. Enable SQLAlchemy query logging (temporary):

```bash
export SQLALCHEMY_ECHO=1
export SQLALCHEMY_ECHO_POOL=1
```

2. Profile handlers locally:

```bash
# cProfile
python -m cProfile -o profile.out run.py
python -m pstats profile.out

# or use pyinstrument
pyinstrument run.py
```

3. ORM optimizations:

- Use `selectinload()` / `joinedload()` for relationships iterated in templates:

```python
from sqlalchemy.orm import selectinload
reqs = db.session.query(Request).options(selectinload(Request.artifacts)).filter(...).all()
```

- Paginate large resultsets instead of `.all()`.
- Use raw SQL (`db.session.execute(text("..."))`) for heavy aggregates when ORM overhead is significant.

4. Postgres diagnostics (run on DB host):

```sql
-- show currently running queries
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY duration DESC;

-- if pg_stat_statements is enabled
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY total_time DESC
LIMIT 20;
```

5. Caching:

- Cache heavy endpoints (we've added short caches for `/dashboard`, `/search`, and `/metrics`).
- Tune `CACHE_DEFAULT_TIMEOUT` via env or add decorator-level timeouts.
- Invalidate caches on write operations where appropriate.

If you want, I can:
- Add `selectinload` and pagination to the B dashboard, or
- Add cache invalidation hooks on create/update/delete paths.
