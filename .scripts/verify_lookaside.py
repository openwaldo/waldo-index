#!/usr/bin/env python3
"""Reject non-public shard URLs and verify every lookaside object by metadata."""

import argparse
import concurrent.futures
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml


SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_objects(root):
    objects = {}
    errors = []
    for path in sorted(root.rglob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"{path.relative_to(root)}: cannot parse YAML: {error}")
            continue
        if not isinstance(document, dict) or document.get("kind") != "manifest":
            continue
        for position, shard in enumerate(document.get("shards", []), 1):
            label = f"{path.relative_to(root)}: shard {position}"
            if not isinstance(shard, dict):
                errors.append(f"{label} is not an object")
                continue
            url = shard.get("url", "")
            digest = shard.get("sha256", "")
            size = shard.get("bytes")
            error = validate_reference(url, digest, size)
            if error:
                errors.append(f"{label}: {error}")
                continue
            previous = objects.get(url)
            value = (digest, size, label)
            if previous and previous[:2] != value[:2]:
                errors.append(f"{label}: URL conflicts with {previous[2]}")
                continue
            objects[url] = value
    if errors:
        raise ValueError("\n".join(errors))
    return objects


def validate_reference(url, digest, size):
    if not isinstance(url, str):
        return "url must be a string"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"s3", "https"}:
        return f"lookaside URL must be remote s3:// or https://, not {url!r}"
    if not parsed.netloc or parsed.query or parsed.fragment:
        return f"lookaside URL must have a host and no query or fragment: {url!r}"
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        return "sha256 must be 64 lowercase hexadecimal characters"
    expected_suffix = f"/{digest[:2]}/{digest[2:4]}/{digest}"
    if not parsed.path.endswith(expected_suffix):
        return f"URL path must end in the canonical content-addressed path {expected_suffix}"
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return "bytes must be a non-negative integer"
    return None


def request_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return url
    key = urllib.parse.quote(parsed.path.lstrip("/"), safe="/")
    return f"https://{parsed.netloc}.s3.amazonaws.com/{key}"


def probe(item, attempts=3):
    url, (_, expected_size, label) = item
    remote = request_url(url)
    last_error = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                remote, method="HEAD", headers={"Accept-Encoding": "identity"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                length = response.headers.get("Content-Length")
                if length is None:
                    raise RuntimeError("response omitted Content-Length")
                actual_size = int(length)
                if actual_size != expected_size:
                    raise RuntimeError(
                        f"declares {expected_size} bytes but remote object has {actual_size}"
                    )
                return url
        except (OSError, RuntimeError, urllib.error.HTTPError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"{label}: cannot reach {url}: {last_error}")


def verify(root, workers):
    objects = load_objects(root)
    total = len(objects)
    print(f"checking {total} remote lookaside objects (headers only)")
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(probe, item) for item in objects.items()]
        for future in concurrent.futures.as_completed(futures):
            future.result()
            completed += 1
            if completed == total or completed == 1 or completed % 25 == 0:
                print(f"  {completed}/{total} objects reachable", flush=True)
    print(f"verified {total} remote lookaside objects")


def main():
    parser = argparse.ArgumentParser(
        description="Reject local shard URLs and HEAD every remote lookaside object."
    )
    parser.add_argument("index", nargs="?", default=".")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 64:
        parser.error("--workers must be between 1 and 64")
    try:
        verify(pathlib.Path(args.index).resolve(), args.workers)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"lookaside verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
