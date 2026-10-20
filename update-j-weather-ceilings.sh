#!/usr/bin/env bash
set -euo pipefail
WEATHER_UPDATE_SCRIPT="$(mktemp /tmp/j-weather-ceilings-update.XXXXXX.sh)"
trap 'rm -f "$WEATHER_UPDATE_SCRIPT"' EXIT
curl -fsSL https://raw.githubusercontent.com/Barometer32/weather-lab/metar-cloud-history-20261019/update-j-weather-current.sh -o "$WEATHER_UPDATE_SCRIPT"
bash "$WEATHER_UPDATE_SCRIPT"
