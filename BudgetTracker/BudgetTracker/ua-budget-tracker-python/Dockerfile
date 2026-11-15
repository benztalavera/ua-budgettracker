FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production DATA_DIR=/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && groupadd --gid 10001 tracker && useradd --uid 10001 --gid tracker --no-create-home tracker && mkdir /data && chown tracker:tracker /data
COPY . .
USER tracker
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4)"
CMD ["gunicorn","--bind","0.0.0.0:8000","--workers","2","--threads","4","--timeout","120","--access-logfile","-","--error-logfile","-","wsgi:app"]
