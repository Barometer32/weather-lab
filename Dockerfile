FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import eccodes; h=eccodes.codes_grib_new_from_samples('regular_ll_sfc_grib2'); eccodes.codes_release(h)"
COPY . .
ENV PORT=8080 PYTHONUNBUFFERED=1
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 90 app:app"]

