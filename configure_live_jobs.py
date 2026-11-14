"""Prepare reviewable Scheduler changes and rollback commands, without mutations."""
import json
from pathlib import Path
import shlex
import sys

RETIRED = ("weather-live-rapid-observations", "weather-live-hourly-observations",
           "weather-live-rtmetar", "weather-live-mesonet", "weather-live-observation-stations")
RTMA_JOB = "weather-live-rtma-observations"


def plan(jobs, project, region, collector):
    by_name = {j["name"].split("/")[-1]: j for j in jobs}
    configure, rollback = [], []
    common = ["--project="+project, "--location="+region]
    for name in RETIRED:
        old = by_name.get(name)
        if not old:
            continue
        assert old["state"] in ("ENABLED", "PAUSED"), "Unsupported retired-job state"
        if old["state"] == "ENABLED":
            configure.insert(0, ["gcloud", "scheduler", "jobs", "pause", name, *common])
            rollback.append(["gcloud", "scheduler", "jobs", "resume", name, *common])
    old = by_name.get(RTMA_JOB)
    if old:
        assert old["state"] in ("ENABLED", "PAUSED"), "Unsupported RTMA job state"
        target = old["httpTarget"]
        oidc = target["oidcToken"]
        rollback.extend([
            ["gcloud", "scheduler", "jobs", "update", "http", RTMA_JOB, *common,
             "--schedule="+old["schedule"], "--time-zone="+old.get("timeZone", "Etc/UTC"),
             "--uri="+target["uri"], "--http-method="+target.get("httpMethod", "POST"),
             "--oidc-service-account-email="+oidc["serviceAccountEmail"],
             "--oidc-token-audience="+oidc.get("audience", target["uri"]),
             "--attempt-deadline="+old.get("attemptDeadline", "300s"),
             "--max-retry-attempts="+str(old.get("retryConfig", {}).get("retryCount", 0))],
            ["gcloud", "scheduler", "jobs", "resume" if old["state"] == "ENABLED" else "pause", RTMA_JOB, *common]])
    else:
        rollback.append(["gcloud", "scheduler", "jobs", "delete", RTMA_JOB, *common, "--quiet"])
    configure.append(["gcloud", "scheduler", "jobs", "update" if old else "create", "http", RTMA_JOB, *common,
                      "--schedule=* * * * *", "--time-zone=Etc/UTC",
                      "--uri="+collector+"/collect/rtma-observations", "--http-method=POST",
                      "--oidc-service-account-email=weather-scheduler@"+project+".iam.gserviceaccount.com",
                      "--oidc-token-audience="+collector, "--attempt-deadline=300s", "--max-retry-attempts=0"])
    if old and old["state"] == "PAUSED":
        configure.append(["gcloud", "scheduler", "jobs", "resume", RTMA_JOB, *common])
    configure.append(["gcloud", "scheduler", "jobs", "run", RTMA_JOB, *common])
    return configure, rollback


if __name__ == "__main__":
    _, action, source, directory, project, region, collector = sys.argv
    assert action == "plan"
    configure, rollback = plan(json.loads(Path(source).read_text()), project, region, collector)
    for name, commands in [("configure", configure), ("rollback", rollback)]:
        Path(directory, "live-"+name+".sh").write_text("#!/usr/bin/env bash\n"+("set -e\n" if name == "configure" else "")+"\n".join(shlex.join(c) for c in commands)+"\n")
    # Retirement runs only after the replacement passes live verification.
    existing = {j["name"].split("/")[-1] for j in json.loads(Path(source).read_text())}
    commands = [["gcloud", "scheduler", "jobs", "delete", name, "--project="+project, "--location="+region, "--quiet"]
                for name in RETIRED if name in existing]
    Path(directory, "live-retire.sh").write_text("#!/usr/bin/env bash\nset -e\n"+"\n".join(shlex.join(c) for c in commands)+"\n")
