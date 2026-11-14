"""Prepare reviewable Scheduler changes and rollback commands, without mutations."""
import json
from pathlib import Path
import shlex
import sys

RETIRED = ("weather-live-rapid-observations", "weather-live-hourly-observations",
           "weather-live-rtmetar", "weather-live-mesonet", "weather-live-observation-stations",
           "weather-live-rtma-observations")


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
    name = "weather-live-public-conditions"
    old = by_name.get(name)
    if old:
        assert old["state"] in ("ENABLED", "PAUSED"), "Unsupported conditions-job state"
        target = old.get("httpTarget", {})
        assert target.get("uri") == collector+"/collect/public-conditions" and target.get("oidcToken", {}).get("serviceAccountEmail"), "Inspect unexpected conditions target before updating"
        configure.append(["gcloud", "scheduler", "jobs", "update", "http", name, *common, "--schedule=*/2 * * * *", "--attempt-deadline=300s"])
        rollback.append(["gcloud", "scheduler", "jobs", "update", "http", name, *common,
                         "--schedule="+old["schedule"], "--attempt-deadline="+old.get("attemptDeadline", "180s")])
        if old["state"] == "PAUSED":
            configure.append(["gcloud", "scheduler", "jobs", "resume", name, *common])
            rollback.append(["gcloud", "scheduler", "jobs", "pause", name, *common])
    else:
        target = by_name["weather-live-metar-clouds"]["httpTarget"]
        email = target["oidcToken"]["serviceAccountEmail"]
        configure.append(["gcloud", "scheduler", "jobs", "create", "http", name, *common,
                          "--schedule=*/2 * * * *", "--time-zone=Etc/UTC", "--attempt-deadline=300s",
                          "--uri="+collector+"/collect/public-conditions", "--http-method=POST",
                          "--oidc-service-account-email="+email, "--oidc-token-audience="+collector])
        rollback.append(["gcloud", "scheduler", "jobs", "delete", name, *common, "--quiet"])
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
