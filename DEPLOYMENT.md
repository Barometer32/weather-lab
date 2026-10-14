# WEATHER LAB deployment

## Restore or deploy

After restoring the Google project and linking an active billing account, run
in authenticated Google Cloud Shell from a fresh checkout:

```bash
(
  set -euo pipefail
  WEATHER_LAB_DIR="$(mktemp -d "$HOME/weather-lab-restore.XXXXXX")"
  git clone https://github.com/Barometer32/weather-lab.git "$WEATHER_LAB_DIR"
  cd "$WEATHER_LAB_DIR"
  bash deploy.sh weather-lab-511113
)
```

The script checks that the project is ACTIVE and billing is enabled before
creating resources or starting a build. It uses the Docker Artifact Registry
repository `weather-lab-images` in us-central1. Google documents that recovered
repositories may not support push/pull after project deletion. This fresh
repository is a recovery attempt; it cannot fix a project-wide restoration
failure. The old `weather-lab` repository is retained and is not modified.

To choose another fresh repository after a future deletion/restore, use
`WEATHER_ARTIFACT_REPOSITORY=weather-lab-images-v2 bash deploy.sh PROJECT_ID`.
If the new repository also reports "Project has been deleted" despite ACTIVE
state and enabled billing, stop repeating builds and investigate the project
restoration with Google Cloud Support. Resource Manager notes that restored
services may take up to 36 hours to recover. Reconnecting billing alone does
not prove that Artifact Registry has recovered.

## Page and data

The four tabs are METAR (default), Radar, Satellite, and Forecast. There is no
Observations or Surface tab and no active MADIS, RWIS, MnDOT, Wisconet, AI,
HRRR, or RRFS collector.

METAR has an airport weather plot and cloud ceiling dropdown. KFCM, KMIC and
KMSP remain separate airports; the metro average is removed. KCFE/KFCE and
KSGS are excluded. One NOAA Aviation Weather Center bulk download at :00
selects routine reports closest to :53 within :50–:59, excludes SPECI/rapid
reports, and labels the following hour. Both modes share twelve hourly
snapshots. Temperature and dew point use available T-remark precision before
Fahrenheit display. Short wind arrows point toward where wind is going, with
speed in mph. Cloud mode labels only the lowest reported BKN/OVC base, rounded
to thousands of feet with a minimum displayed value of 1.

Radar keeps native KMPX lowest 0.5-degree completed scans, including available
supplemental scans, across the previous two hours with no frame-count cap or
smoothing. Below 10 dBZ stays transparent. Five solid display bands start at
10 (green/light), 25 (dark green/light–moderate), 30 (yellow/moderate),
40 (orange/moderate–heavy), and 45 (red/heavy) dBZ. Rain labels are approximate;
snow, hail, and non-rain targets differ. Native data and retained history are
unchanged by the display palette.

Satellite keeps the original COD Central Minnesota True Color, Day Cloud
Phase and Nighttime Microphysics products and manual timeline. Forecast keeps
the compact NWS MapClick JSON forecast for 44.9244, -93.4140.

## Managed resources and schedules

All resources use us-central1 unless noted. Both Cloud Run services have
minimum 0 / maximum 1 instance and request-based billing.

| Resource | Settings |
| --- | --- |
| weather-lab | Public web service, 1 CPU / 1 GiB |
| weather-collector | Private collector, 1 CPU / 1 GiB |
| <project>-weather-data | Private regional data bucket |
| weather-lab-images | Docker images for both services |
| weather-live-radar | Every minute, /collect/radar-KMPX |
| weather-live-satellite | Every five minutes |
| weather-live-forecast | Every five minutes |
| weather-live-metar-clouds | Once hourly at :00, no scheduled retries |

Scheduler uses OIDC with the weather-scheduler identity, which may invoke the
private collector. The script creates missing managed resources, resumes its
paused jobs and triggers initial collection. It removes specifically named
retired model, Eglin radar, observations and Surface jobs, preserving unrelated
resources. Prepared imagery expires after one day; current manifests and map
overlays remain. The data bucket has no versioning or soft-delete retention.

## Verify and refresh

```bash
gcloud scheduler jobs list --project=weather-lab-511113 --location=us-central1
gcloud run services list --project=weather-lab-511113 --region=us-central1
gcloud storage ls gs://weather-lab-511113-weather-data/live/
```

There should be four active Weather Lab Scheduler jobs. Expected manifests
include radar-KMPX.json, radar-state-KMPX.json, metar-clouds.json, forecast.json
and three satellite product manifests. A legacy observations.json may remain
but is not used by the page.

The public service reads saved data; opening a page does not launch imagery
processing. First imagery backfill can take a few minutes. Deleted METAR
history accumulates hourly until twelve positions are available. Cold starts,
browser downloads and upstream delays can still occur. NWS controls forecast
issuance; checking it every five minutes does not create a new forecast.

A successful "Run now" request queues collection; inspect Scheduler execution
status and collector logs to verify the actual result. Failed collections keep
the previous successful saved data and show delayed data where applicable.

## Costs and stopping

Charges depend on collector runtime, storage operations, traffic, builds,
image storage and remaining account-wide free tiers. Four Scheduler jobs are
managed. Saving code to GitHub does not deploy Google Cloud.

Pause the four managed Scheduler jobs to stop unattended collection while
keeping the site and saved data. Storage and Artifact Registry costs can remain
while idle. Disabling billing and deleting the Google project is the complete
shutdown route when the site is no longer wanted.

## References

- https://docs.cloud.google.com/artifact-registry/docs/troubleshooting
- https://docs.cloud.google.com/resource-manager/docs/delete-restore-projects
