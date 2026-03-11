FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	PORT=8080 \
	UPLOAD_FOLDER=/data/uploads

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
	&& python -m pip install -r requirements.txt

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
	&& mkdir -p /data/uploads /app/instance \
	&& chown -R appuser:appuser /data /app

COPY --chown=appuser:appuser . .
COPY --chown=appuser:appuser scripts/ /app/scripts/
RUN chmod +x /app/scripts/entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
	CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/ready', timeout=3)" || exit 1

USER appuser

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["gunicorn", "-w", "3", "--threads", "4", "-k", "gthread", "-b", "0.0.0.0:8080", "run:app"]
