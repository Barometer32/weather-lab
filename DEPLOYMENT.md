# Google Cloud deployment

Weather Lab now needs only its Cloud Run **web service**, an Artifact Registry image repository and Cloud Build for deployments. It uses public NWS and COD data with small per-instance caches. No HRRR/RRFS model job, hourly scheduler, GRIB decoder or forecast storage bucket is required.

## Update your existing project

Open Google Cloud Shell with project `weather-lab-511113` selected, then run:

```bash
cd ~/weather-lab
git pull --ff-only
bash deploy.sh weather-lab-511113
```

The script performs these steps:

1. Deletes the old `weather-hourly` Cloud Scheduler job in `us-central1`.
2. Deletes the old `weather-forecast` Cloud Run job. Google Cloud terminates its running executions when the job is deleted.
3. Builds the lighter container and deploys `weather-lab` with zero minimum instances, one maximum instance, one CPU and 1 GiB memory.
4. Clears the obsolete forecast environment variable.
5. Removes the old `forecast/latest.json` object from `<project>-forecast` and deletes the bucket if empty. Unrelated remaining objects are retained.
6. Prints the public service URL.

Only the named Weather Lab resources are retired. These cloud steps have **not** happened merely because the source was updated on GitHub; run the deployment script to apply them.

After it succeeds, refresh the page. The Forecast tab should say **National Weather Service · Hopkins**, and the Satellite tab should offer the three products. Observations and radar retain their existing behavior.

## New project

The same script can deploy into a billing-enabled project you own. Pass that project's actual ID. If no retired jobs or bucket exist, their cleanup steps are skipped.

The deployment identity needs permission to enable APIs, use Cloud Build, manage the named Cloud Run service/jobs, manage the named scheduler job, and remove the obsolete forecast object/bucket. The web runtime uses `weather-web`; the build uses `weather-builder`. No runtime storage permissions or API secrets are needed.

## Verify the old recurring work is gone

In the selected project's GUI, check **Cloud Scheduler** for absence of `weather-hourly`, and **Cloud Run → Jobs** for absence of `weather-forecast`.

Read-only checks in Cloud Shell:

```bash
gcloud scheduler jobs list --project=weather-lab-511113 --location=us-central1
gcloud run jobs list --project=weather-lab-511113 --region=us-central1
```

## Data refresh and costs

NWS forecasts and satellite frame lists are fetched on demand and cached briefly. There is no unattended hourly forecast computation. Radar and satellite images are requested when their tabs are used; the browser fetches satellite images directly from COD, which avoids routing those image bytes through Cloud Run.

Cloud Run remains configured to scale to zero. Actual charges depend on usage, free-tier eligibility, build/image storage and network traffic. Old Artifact Registry image revisions can continue to use storage; the script preserves them so previous deployments remain recoverable.

## Troubleshooting

- **NWS feed unavailable:** refresh later. The last displayed forecast remains with a warning; no model blend is substituted.
- **Satellite unavailable:** ensure your browser/network allows `weather.cod.edu`. The upstream HTML/image feed can change; check the linked COD viewer.
- **Build or deployment fails:** the old scheduler/job may already have been retired, but the previous web revision can remain live. Fix the shown error and rerun the script.
- **Old forecast bucket not empty:** the script retains remaining objects and reports that fact; the collector/scheduler still remain deleted.
