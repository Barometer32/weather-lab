# Deploy Weather Lab to Google Cloud

## 1. Create the accounts/resources

1. GitHub: https://github.com/new -> name `weather-lab`, Public, Add a README -> Create repository. Upload the project files into its root (or let the connected GitHub app commit them after repository creation). This is a Python application hosted on Cloud Run, not a GitHub Pages static site.
2. Google Cloud: https://console.cloud.google.com/projectcreate -> name **Weather Lab**. Use a NEW unique project ID: deleted IDs cannot be reused. Reopen or create your Cloud Billing account if you previously closed it and link the new project. No deployment has happened until you run the following steps.
3. Billing -> Budgets & alerts -> Create budget -> scope only this project -> monthly amount $30 -> alerts at 50%, 80%, 100%. Budgets send alerts and do not cap charges.

## 2. Deploy from Cloud Shell

Open Cloud Shell in the new project. Substitute your real NEW_PROJECT_ID in the final command.

```bash
git clone https://github.com/Barometer32/weather-lab.git
cd weather-lab
bash deploy.sh NEW_PROJECT_ID
```

The script enables APIs, creates a private forecast bucket and separate web, collector, scheduler and builder service accounts, builds the container, deploys the public website, creates a scheduled collector and runs the first collection. It prints the public HTTPS URL. Open that URL from your phone or laptop. Public means anyone with the URL can visit; traffic can affect costs.

The website uses 1 CPU/1 GiB, minimum zero and maximum one instance. Collector: 2 CPU/4 GiB, one task, no automatic task retries, 15-minute timeout. One Scheduler job checks at :45 and :55 UTC hourly. An already-published preferred cycle exits early. :55 retries availability of the same preferred cycle. If that cycle is late, the job looks back up to three cycles for the newest complete pair newer than the stored forecast. No large download occurs for stored/older cycles, and original forecast times remain visible. If no newer pair is complete, the page keeps the previous blend. We cannot guarantee NCEP publication at :45.

The first collection can fail simply because the current target cycle is late; the deployed observations/radar page remains available. Wait for the next scheduled check or retry with:

```bash
gcloud run jobs execute weather-forecast --region=us-central1 --wait
```

The script assigns its dedicated builder `roles/cloudbuild.builds.builder` and uses regional build buckets, so it does not rely on the permissions of Google’s default builder account. For an IAM or organization-policy error, retain the exact error and resolve that specific policy rather than granting broad roles.

## 3. Verify

1. Open the public URL. Check the observation QA dot, timestamps, manual radar slider on both devices.
2. Forecast: verify model cycle and publication time, future hourly rows (up to 16 rows at model hours +2 through +17), wind direction FROM true north, and precipitation for the hour starting at each row. Clouds with only HRRR must have an asterisk. The +18 endpoint supplies the last row’s precipitation. Elapsed rows are hidden.
3. Cloud Run -> Jobs -> weather-forecast -> Executions: confirm Success and review the logged processing seconds. Compare job duration and data transfer after a few days before relying on a monthly estimate.

```bash
gcloud run jobs executions list --job=weather-forecast --region=us-central1
gcloud scheduler jobs describe weather-hourly --location=us-central1
gcloud run services describe weather-lab --region=us-central1 --format='value(status.url)'
```

## Cost assumptions

Planning range: roughly $10–$30/month for personal traffic, efficient downloads and the free allowances otherwise unused; this is not a cap or a guaranteed quote. 720 five-minute updates/month at 2 CPUs/4 GiB are about $9.50 gross compute before free allowances, plus the short duplicate checks, frontend, storage, builds and bandwidth. A 15-minute collection every hour would substantially increase that estimate. Set alerts and check real runtimes. No GPU, database server, AI API or retraining service is deployed. Radar is requested only while its tab is viewed; shared cached processing avoids repeated work when possible.

## Update code

```bash
git pull
bash deploy.sh NEW_PROJECT_ID
```

## Pause hourly collection

```bash
gcloud scheduler jobs pause weather-hourly --location=us-central1
```

Remaining future forecast rows stay visible with stale labeling; once all timestamps have passed, the table shows an unavailable message. Website/radar can still incur charges when viewed.

## Remove the experiment

Save the code first. Disable billing and delete this dedicated project:

```bash
gcloud billing projects unlink NEW_PROJECT_ID
gcloud projects delete NEW_PROJECT_ID
```

Prior usage charges remain due. Deleting only the Cloud Run service can leave storage/build artifacts behind.
