import unittest
from pathlib import Path


ROOT = Path(__file__).parent


class DockerAssetTests(unittest.TestCase):
    def test_entrypoint_uses_unix_line_endings(self):
        entrypoint = (ROOT / "docker-entrypoint.sh").read_bytes()

        self.assertTrue(entrypoint.startswith(b"#!/bin/sh\n"))
        self.assertNotIn(b"\r", entrypoint)


if __name__ == "__main__":
    unittest.main()
