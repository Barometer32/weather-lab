FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py collector.py realtime.py ./
COPY metar_clouds.py metar_history.py cloud_conditions.py ./
COPY native_radar.py satellite.py nws_forecast.py lamp_hourly.py air_quality.py THIRD_PARTY.md ./
COPY static/ static/
ENV PORT=8080 PYTHONUNBUFFERED=1
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 90 app:app"]

