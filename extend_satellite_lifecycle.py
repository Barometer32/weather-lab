"""Extend the actual bucket policy only for the new visible satellite images."""
from copy import deepcopy
import json
import sys


def extend(metadata, bucket):
    if metadata.get("name") != bucket:
        raise ValueError("Unexpected data bucket metadata")
    lifecycle = deepcopy(metadata.get("lifecycle") or {"rule": []})
    if not isinstance(lifecycle, dict) or not isinstance(lifecycle.get("rule"), list):
        raise ValueError("Unexpected bucket lifecycle format")
    rule = {"action": {"type": "Delete"},
            "condition": {"age": 1, "matchesPrefix": ["satellite/02/"]}}
    if rule not in lifecycle["rule"]:
        lifecycle["rule"].append(rule)
    return lifecycle


if __name__ == "__main__":
    json.dump(extend(json.load(sys.stdin), sys.argv[1]), sys.stdout)
