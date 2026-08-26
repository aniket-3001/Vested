FROM python:3.11-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY core/ ./core/

# Unprivileged: the process only ever holds documents in memory and has no
# reason to be able to write anywhere.
RUN useradd --create-home --shell /usr/sbin/nologin app
USER app

EXPOSE 8080

# ONE worker, deliberately. Sessions are process-local by design (nothing a
# member uploads should outlive their visit), so a second worker would strand
# users on the wrong process. Scale is bounded by --max-instances=1 on Cloud
# Run for the same reason. See DEPLOY.md "Session model".
CMD exec gunicorn "app.server:create_app()" \
      --bind "0.0.0.0:${PORT}" \
      --workers 1 \
      --threads 8 \
      --timeout 60 \
      --access-logfile - \
      --error-logfile -
