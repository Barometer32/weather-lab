#!/usr/bin/env bash
# Compatibility entry point for the current live-observation update.
set -euo pipefail
WEATHER_HELPER="$(mktemp /tmp/j-weather-live.XXXXXX)"
curl -fsSL https://raw.githubusercontent.com/Barometer32/weather-lab/metar-cloud-history-20261019/update-j-weather-live.sh -o "$WEATHER_HELPER"
bash "$WEATHER_HELPER"
