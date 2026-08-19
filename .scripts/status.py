#!/usr/bin/env python3
"""Generate status.json — the index's public rollup.

Walks the committed index.yaml/index.json files from the repo root (the same
walk `waldo index summary` performs), aggregates every manifest's shards —
totals plus the per-license partition — and writes the JSON the website
consumes. Emits both the tree-wide rollup and a `corpora` table: one row
per manifest with its provenance (where it came from) and its stats. The
numbers derive only from committed metadata, so the output is exactly as
trustworthy as the tree it was run in.

Usage: scripts/status.py [output-path]   (default: ./status.json)
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    sys.exit("status.py requires PyYAML (python3 -m pip install PyYAML==6.0.2)")


INDEX_FILENAMES = ("index.yaml", "index.yml", "index.json")


def load_metadata(path):
    """Read schema metadata in its YAML or legacy JSON representation."""
    with open(path, encoding="utf-8") as f:
        if path.endswith(".json"):
            value = json.load(f)
        elif path.endswith((".yaml", ".yml")):
            value = yaml.safe_load(f)
        else:
            raise ValueError(f"unsupported metadata extension: {path}")
    if not isinstance(value, dict):
        raise ValueError(f"metadata document must be an object: {path}")
    return value


def find_index(dirpath):
    """Prefer canonical YAML while retaining compatibility with old trees."""
    for filename in INDEX_FILENAMES:
        path = os.path.join(dirpath, filename)
        if os.path.isfile(path):
            return path
    expected = ", ".join(INDEX_FILENAMES)
    raise FileNotFoundError(f"no index metadata in {dirpath} ({expected})")


def add(agg, license_id, shards, docs, tokens, nbytes):
    agg["shards"] += shards
    agg["docs"] += docs
    agg["tokens"] += tokens
    agg["bytes"] += nbytes
    add_license(agg, license_id, shards, docs, tokens, nbytes)


def add_license(agg, license_id, shards, docs, tokens, nbytes):
    lic = agg["licenses"].setdefault(
        license_id, {"shards": 0, "docs": 0, "tokens": 0, "bytes": 0})
    lic["shards"] += shards
    lic["docs"] += docs
    lic["tokens"] += tokens
    lic["bytes"] += nbytes


def license_list(value):
    """Return a manifest/shard's singular or plural license declaration."""
    singular = value.get("license")
    if singular:
        return [singular]
    return list(value.get("licenses") or [])


def declared_content_values(manifest, field):
    """Return sorted corpus and source declarations without inferring rows."""
    values = set((manifest.get("content") or {}).get(field) or [])
    for source in manifest.get("sources", []):
        values.update((source.get("content") or {}).get(field) or [])
    return sorted(value for value in values if value)


def add_declarations(agg, field, values):
    counts = agg.setdefault(field, {})
    for value in values:
        counts[value] = counts.get(value, 0) + 1


def walk(root, dirpath, agg, corpora):
    ix = load_metadata(find_index(dirpath))
    for e in ix.get("entries", []):
        name, etype = e["name"], e["type"]
        if etype == "dir":
            walk(root, os.path.join(dirpath, name), agg, corpora)
        elif etype == "manifest":
            m = load_metadata(os.path.join(dirpath, name))
            agg["manifests"] += 1
            defaults = license_list(m) or ["(none declared)"]
            languages = declared_content_values(m, "languages")
            programming_languages = declared_content_values(
                m, "programming_languages")
            add_declarations(agg, "languages", languages)
            add_declarations(agg, "programming_languages",
                             programming_languages)
            # One table row per manifest: provenance + its own stats.
            row = {
                "path": os.path.relpath(dirpath, root),
                "name": m.get("name") or os.path.splitext(name)[0],
                "title": m.get("title", ""),
                "description": m.get("description", ""),
                # Empty format resolves to the parquet default, matching the tool.
                "format": m.get("format") or "parquet",
                "sources": [
                    {"name": s.get("name"), "origin": s.get("source"),
                     "version": s.get("version"), "url": s.get("url")}
                    for s in m.get("sources", [])
                ],
                "converted_by": (m.get("converted_by") or {}).get("tool"),
                "languages": languages,
                "programming_languages": programming_languages,
                "shards": 0, "docs": 0, "tokens": 0, "bytes": 0,
                "licenses": {},
            }
            # A rollup replaces the shard list; otherwise walk each shard.
            # Shard entries inherit the manifest license unless they carry
            # their own — the partition must match the tree's.
            rollup = m.get("rollup")
            objects = [(rollup, int(rollup.get("count", 0)))] if rollup else [
                (shard, 1) for shard in m.get("shards", [])]
            for obj, shards in objects:
                docs = obj.get("docs", 0)
                tokens = obj.get("tokens", 0)
                nbytes = obj.get("bytes", 0)
                licenses = license_list(obj) or defaults
                if len(licenses) == 1:
                    add(agg, licenses[0], shards, docs, tokens, nbytes)
                else:
                    agg["shards"] += shards
                    agg["docs"] += docs
                    agg["tokens"] += tokens
                    agg["bytes"] += nbytes
                    usage = obj.get("license_usage") or {}
                    for lic in licenses:
                        measure = usage.get(lic) or {}
                        add_license(agg, lic, shards,
                                    measure.get("docs", 0),
                                    measure.get("tokens", 0),
                                    measure.get("bytes", 0))
                row["shards"] += shards
                row["docs"] += docs
                row["tokens"] += tokens
                row["bytes"] += nbytes
                usage = obj.get("license_usage") or {}
                for lic in licenses:
                    measure = usage.get(lic) or {}
                    rl = row["licenses"].setdefault(
                        lic, {"shards": 0, "tokens": 0})
                    rl["shards"] += shards
                    rl["tokens"] += (tokens if len(licenses) == 1 else
                                     measure.get("tokens", 0))
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
           "bytes": 0, "licenses": {}, "languages": {},
           "programming_languages": {}}
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
        "languages": dict(sorted(agg["languages"].items())),
        "programming_languages": dict(
            sorted(agg["programming_languages"].items())),
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
