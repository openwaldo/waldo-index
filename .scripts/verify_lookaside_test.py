#!/usr/bin/env python3
"""Unit tests for PR lookaside verification."""

import importlib.util
import pathlib
import tempfile
import unittest

import yaml


SCRIPT = pathlib.Path(__file__).with_name("verify_lookaside.py")
SPEC = importlib.util.spec_from_file_location("verify_lookaside", SCRIPT)
verify_lookaside = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_lookaside)


class VerifyLookasideTest(unittest.TestCase):
    def write_manifest(self, root, url, digest="a" * 64, size=12):
        path = pathlib.Path(root, "corpus.yaml")
        path.write_text(yaml.safe_dump({
            "kind": "manifest",
            "schema": 2,
            "shards": [{"url": url, "sha256": digest, "bytes": size}],
        }), encoding="utf-8")

    def test_accepts_canonical_remote_object(self):
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as root:
            self.write_manifest(root, f"s3://bucket/lookaside/aa/aa/{digest}")
            objects = verify_lookaside.load_objects(pathlib.Path(root))
            self.assertEqual(len(objects), 1)

    def test_rejects_local_object(self):
        digest = "a" * 64
        for url in [
            f"file:///tmp/aa/aa/{digest}",
            f"/tmp/aa/aa/{digest}",
            f"http://example.test/aa/aa/{digest}",
        ]:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as root:
                self.write_manifest(root, url)
                with self.assertRaisesRegex(ValueError, "must be remote"):
                    verify_lookaside.load_objects(pathlib.Path(root))

    def test_rejects_noncanonical_remote_path(self):
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as root:
            self.write_manifest(root, f"https://example.test/{digest}")
            with self.assertRaisesRegex(ValueError, "canonical content-addressed"):
                verify_lookaside.load_objects(pathlib.Path(root))


if __name__ == "__main__":
    unittest.main()
