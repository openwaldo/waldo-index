#!/usr/bin/env python3
"""Generate status.json — the index's public rollup.

Walks the committed index.json files from the repo root (the same walk
`waldo index summary` performs), aggregates every manifest's shards —
totals plus the per-license partition — and writes the JSON the website
consumes. Pure stdlib; the numbers derive only from committed metadata,
so the output is exactly as trustworthy as the tree it was run in.

Usage: scripts/status.py [output-path]   (default: ./status.json)
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def add(agg, license_id, shards, docs, tokens, nbytes):
    agg["shards"] += shards
    agg["docs"] += docs
    agg["tokens"] += tokens
    agg["bytes"] += nbytes
    lic = agg["licenses"].setdefault(
        license_id, {"shards": 0, "docs": 0, "tokens": 0, "bytes": 0})
    lic["shards"] += shards
    lic["docs"] += docs
    lic["tokens"] += tokens
    lic["bytes"] += nbytes


def walk(root, dirpath, agg):
    with open(os.path.join(dirpath, "index.json")) as f:
        ix = json.load(f)
    for e in ix.get("entries", []):
        name, etype = e["name"], e["type"]
        if etype == "dir":
            walk(root, os.path.join(dirpath, name), agg)
        elif etype == "manifest":
            with open(os.path.join(dirpath, name)) as f:
                m = json.load(f)
            agg["manifests"] += 1
            default = m.get("license", "") or "(none declared)"
            rollup = m.get("rollup")
            if rollup:
                add(agg, default, int(rollup.get("count", 0)),
                    rollup.get("docs", 0), rollup.get("tokens", 0),
                    rollup.get("bytes", 0))
                continue
            for sh in m.get("shards", []):
                # Shard entries inherit the manifest license unless they
                # carry their own — the partition must match the tree's.
                lic = sh.get("license") or default
                add(agg, lic, 1, sh.get("docs", 0),
                    sh.get("tokens", 0), sh.get("bytes", 0))


def head_commit(root):
    try:
        return subprocess.run(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return os.environ.get("GITHUB_SHA", "unknown")[:7]


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "status.json")
    agg = {"manifests": 0, "shards": 0, "docs": 0, "tokens": 0,
           "bytes": 0, "licenses": {}}
    walk(root, root, agg)
    status = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "index_commit": head_commit(root),
        "manifests": agg["manifests"],
        "shards": agg["shards"],
        "docs": agg["docs"],
        "tokens": agg["tokens"],
        "bytes": agg["bytes"],
        "licenses": dict(sorted(agg["licenses"].items())),
    }
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        json.dump(status, f, indent=2)
        f.write("\n")
    print(f"wrote {out}: {agg['manifests']} manifest(s), "
          f"{agg['tokens']:,} tokens, {len(agg['licenses'])} license(s)")


if __name__ == "__main__":
    main()
