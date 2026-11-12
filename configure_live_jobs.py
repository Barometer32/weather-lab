"""Prepare reversible retirement of unused station Scheduler jobs."""
import json
from pathlib import Path
import shlex
import sys

RETIRED = ("weather-live-rtmetar", "weather-live-mesonet", "weather-live-observation-stations")


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
            configure.append(["gcloud", "scheduler", "jobs", "pause", name, *common])
            rollback.append(["gcloud", "scheduler", "jobs", "resume", name, *common])
    return configure, rollback


if __name__ == "__main__":
    _, action, source, directory, project, region, collector = sys.argv
    assert action == "plan"
    jobs = json.loads(Path(source).read_text())
    configure, rollback = plan(jobs, project, region, collector)
    existing = {j["name"].split("/")[-1] for j in jobs}
    retire = [["gcloud", "scheduler", "jobs", "delete", name, "--project="+project, "--location="+region, "--quiet"]
              for name in RETIRED if name in existing]
    # Deletion is separate and runs only after live verification succeeds.
    for name, commands in [("configure", configure), ("rollback", rollback), ("retire", retire)]:
        Path(directory, "live-"+name+".sh").write_text("#!/usr/bin/env bash\n"+("set -e\n" if name != "rollback" else "")+"\n".join(shlex.join(c) for c in commands)+"\n")
