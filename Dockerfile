FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ICLOUD_HME_CONFIG=/data/hme-config.json
ENV HME_STATE_DIR=/data/state

WORKDIR /app

COPY api_service.py auto_refresh.py hme.py icloud_mail.py icloud_web_session.py session_import.py web_app.py ./
COPY static/ ./static/

RUN mkdir -p /data/state

EXPOSE 8000

# Binds $PORT when the platform sets it (e.g. Render), else 8000.
CMD ["python", "web_app.py", "--host", "0.0.0.0"]
