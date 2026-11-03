"""Private, isolated collector for the five-minute CURRENT observation feed."""
from datetime import datetime,timezone
import logging
import threading
from flask import Flask,jsonify
from realtime import get_store
from current_analysis import collect
app=Flask(__name__)
lock=threading.Lock()


@app.get('/healthz')
def health():return jsonify(status='ok')


@app.post('/collect/current-analysis')
def prepare_current():
    if not lock.acquire(blocking=False):return jsonify(status='already collecting'),200
    try:
        store=get_store()
        if store is None:raise ValueError('WEATHER_DATA_BUCKET is required')
        data=collect(store,datetime.now(timezone.utc))
        return jsonify(status='prepared',stations=len(data['stations']),sourceErrors=data['errors'])
    except Exception:
        app.logger.exception('Current observation collection failed')
        return jsonify(error='Collection failed; previous snapshot retained'),502
    finally:lock.release()


logging.basicConfig(level=logging.INFO)
