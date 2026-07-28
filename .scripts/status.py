#!/usr/bin/env python3
"""Generate status.json — the index's public rollup.

Walks the committed index.json files from the repo root (the same walk
`waldo index summary` performs), aggregates every manifest's shards —
totals plus the per-license partition — and writes the JSON the website
consumes. Emits both the tree-wide rollup and a `corpora` table: one row
per manifest with its provenance (where it came from) and its stats. Pure
stdlib; the numbers derive only from committed metadata, so the output is
exactly as trustworthy as the tree it was run in.

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


def walk(root, dirpath, agg, corpora):
    with open(os.path.join(dirpath, "index.json")) as f:
        ix = json.load(f)
    for e in ix.get("entries", []):
        name, etype = e["name"], e["type"]
        if etype == "dir":
            walk(root, os.path.join(dirpath, name), agg, corpora)
        elif etype == "manifest":
            with open(os.path.join(dirpath, name)) as f:
                m = json.load(f)
            agg["manifests"] += 1
            default = m.get("license", "") or "(none declared)"
            # One table row per manifest: provenance + its own stats.
            row = {
                "path": os.path.relpath(dirpath, root),
                "name": m.get("name") or os.path.splitext(name)[0],
                "description": m.get("description", ""),
                # Empty format resolves to the parquet default, matching the tool.
                "format": m.get("format") or "parquet",
                "sources": [
                    {"name": s.get("name"), "origin": s.get("source"),
                     "version": s.get("version"), "url": s.get("url")}
                    for s in m.get("sources", [])
                ],
                "converted_by": (m.get("converted_by") or {}).get("tool"),
                "shards": 0, "docs": 0, "tokens": 0, "bytes": 0,
                "licenses": {},
            }
            # A rollup replaces the shard list; otherwise walk each shard.
            # Shard entries inherit the manifest license unless they carry
            # their own — the partition must match the tree's.
            rollup = m.get("rollup")
            if rollup:
                units = [(default, int(rollup.get("count", 0)),
                          rollup.get("docs", 0), rollup.get("tokens", 0),
                          rollup.get("bytes", 0))]
            else:
                units = [(sh.get("license") or default, 1, sh.get("docs", 0),
                          sh.get("tokens", 0), sh.get("bytes", 0))
                         for sh in m.get("shards", [])]
            for lic, shards, docs, tokens, nbytes in units:
                add(agg, lic, shards, docs, tokens, nbytes)
                row["shards"] += shards
                row["docs"] += docs
                row["tokens"] += tokens
                row["bytes"] += nbytes
                rl = row["licenses"].setdefault(lic, {"shards": 0, "tokens": 0})
                rl["shards"] += shards
                rl["tokens"] += tokens
            row["licenses"] = dict(sorted(row["licenses"].items()))
            corpora.append(row)


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
    corpora = []
    walk(root, root, agg, corpora)
    # Biggest corpora first — the natural reading order for the table.
    corpora.sort(key=lambda r: r["tokens"], reverse=True)
    status = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "index_commit": head_commit(root),
        "manifests": agg["manifests"],
        "shards": agg["shards"],
        "docs": agg["docs"],
        "tokens": agg["tokens"],
        "bytes": agg["bytes"],
        "licenses": dict(sorted(agg["licenses"].items())),
        "corpora": corpora,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        json.dump(status, f, indent=2)
        f.write("\n")
    print(f"wrote {out}: {agg['manifests']} manifest(s), "
          f"{agg['tokens']:,} tokens, {len(agg['licenses'])} license(s)")


if __name__ == "__main__":
    main()
