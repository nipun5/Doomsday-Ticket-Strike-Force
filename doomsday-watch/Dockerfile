FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY watch.py .
RUN useradd --system --uid 10001 watcher && mkdir /data && chown watcher:watcher /data
USER watcher
ENV PYTHONUNBUFFERED=1 STATE_FILE=/data/state.json
CMD ["python", "watch.py"]
