FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PLUMB_DB=/data/plumb.db
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt
COPY app ./app
COPY src ./src
COPY data ./data
COPY results/results_v2.json ./results/results_v2.json
RUN mkdir -p /data
VOLUME /data
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
