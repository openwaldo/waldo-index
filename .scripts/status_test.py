#!/usr/bin/env python3
"""Tests for the mixed JSON/YAML public status rollup."""

import importlib.util
import json
import os
import tempfile
import unittest

import yaml


SCRIPT = os.path.join(os.path.dirname(__file__), "status.py")
SPEC = importlib.util.spec_from_file_location("waldo_index_status", SCRIPT)
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)


class StatusTest(unittest.TestCase):
    def write_json(self, path, value):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f)

    def write_yaml(self, path, value):
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(value, f, sort_keys=False)

    def test_walks_mixed_tree_and_prefers_yaml_index(self):
        with tempfile.TemporaryDirectory() as root:
            legacy = os.path.join(root, "legacy")
            os.mkdir(legacy)
            self.write_yaml(os.path.join(root, "index.yaml"), {
                "kind": "index", "schema": 1, "entries": [
                    {"name": "current.yaml", "type": "manifest"},
                    {"name": "legacy", "type": "dir"},
                ],
            })
            # A stale JSON sibling must not cause duplicate traversal.
            self.write_json(os.path.join(root, "index.json"), {
                "kind": "index", "schema": 1, "entries": [],
            })
            self.write_yaml(os.path.join(root, "current.yaml"), {
                "kind": "manifest", "schema": 1, "name": "current",
                "license": "CC0-1.0", "shards": [
                    {"docs": 2, "tokens": 20, "bytes": 200},
                ],
            })
            self.write_json(os.path.join(legacy, "index.json"), {
                "kind": "index", "schema": 1, "entries": [
                    {"name": "legacy.json", "type": "manifest"},
                ],
            })
            self.write_json(os.path.join(legacy, "legacy.json"), {
                "kind": "manifest", "schema": 1, "name": "legacy",
                "license": "MIT", "shards": [
                    {"docs": 3, "tokens": 30, "bytes": 300},
                ],
            })

            agg = {"manifests": 0, "shards": 0, "docs": 0, "tokens": 0,
                   "bytes": 0, "licenses": {}}
            corpora = []
            status.walk(root, root, agg, corpora)

            self.assertEqual(agg["manifests"], 2)
            self.assertEqual(agg["shards"], 2)
            self.assertEqual(agg["docs"], 5)
            self.assertEqual(agg["tokens"], 50)
            self.assertEqual({row["name"] for row in corpora},
                             {"current", "legacy"})


if __name__ == "__main__":
    unittest.main()
