"""Prepare reviewable Scheduler changes and rollback commands, without mutations."""
import json
from pathlib import Path
import shlex
import sys

JOBS = {"weather-live-rapid-observations": "rapid-observations"}
RETIRED = ("weather-live-rtmetar", "weather-live-mesonet", "weather-live-observation-stations")


def plan(jobs, project, region, collector):
    by_name = {j["name"].split("/")[-1]: j for j in jobs}
    identity = by_name["weather-live-metar-clouds"]["httpTarget"]["oidcToken"]["serviceAccountEmail"]
    assert identity.endswith("@" + project + ".iam.gserviceaccount.com"), "Unexpected scheduler identity"
    configure, rollback = [], []
    common = ["--project="+project, "--location="+region]
    for name, kind in JOBS.items():
        old = by_name.get(name)
        action = "update" if old else "create"
        flags = ["--schedule=*/5 * * * *", "--time-zone=Etc/UTC", "--attempt-deadline=300s",
                 "--uri="+collector.rstrip("/")+"/collect/"+kind, "--http-method=POST",
                 "--oidc-service-account-email="+identity, "--oidc-token-audience="+collector.rstrip("/")]
        configure.append(["gcloud", "scheduler", "jobs", action, "http", name, *common, *flags])
        if old:
            assert old["state"] in ("ENABLED", "PAUSED"), "Unsupported scheduler state"
            target = old["httpTarget"]
            token = target["oidcToken"]
            restore = ["--schedule="+old["schedule"], "--time-zone="+old.get("timeZone", "Etc/UTC"),
                       "--attempt-deadline="+old.get("attemptDeadline", "180s"), "--uri="+target["uri"],
                       "--http-method="+target.get("httpMethod", "POST"),
                       "--oidc-service-account-email="+token["serviceAccountEmail"],
                       "--oidc-token-audience="+token.get("audience", target["uri"])]
            # Headers/body/retry settings are not changed by this release.
            rollback.append(["gcloud", "scheduler", "jobs", "update", "http", name, *common, *restore])
            rollback.append(["gcloud", "scheduler", "jobs", "pause" if old["state"] == "PAUSED" else "resume", name, *common])
            if old["state"] == "PAUSED":
                configure.append(["gcloud", "scheduler", "jobs", "resume", name, *common])
        else:
            rollback.append(["gcloud", "scheduler", "jobs", "delete", name, *common, "--quiet"])
        configure.append(["gcloud", "scheduler", "jobs", "run", name, *common])
    for name in RETIRED:
        old = by_name.get(name)
        if not old:
            continue
        assert old["state"] in ("ENABLED", "PAUSED"), "Unsupported retired-job state"
        if old["state"] == "ENABLED":
            configure.insert(0, ["gcloud", "scheduler", "jobs", "pause", name, *common])
            rollback.append(["gcloud", "scheduler", "jobs", "resume", name, *common])
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
