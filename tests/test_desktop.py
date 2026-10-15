"""laptop/desktop.sh: the Mac app's connection file, and that the app is pinned to the release the server runs. Run: python3 -m unittest discover -s tests"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "laptop" / "desktop.sh"


def config(home: Path, *args: str) -> dict:
    out = subprocess.run(["bash", str(SCRIPT), "--print-config", *args], capture_output=True, text=True, env={**os.environ, "HOME": str(home)}, check=True).stdout
    return json.loads(out)


class DesktopTest(unittest.TestCase):
    def test_the_app_is_built_from_the_release_the_server_runs(self):
        lib = (ROOT / "vm" / "lib.sh").read_text()
        script = SCRIPT.read_text()
        for name in ("HERMES_TAG", "HERMES_COMMIT"):
            self.assertEqual(re.search(rf"^{name}=(\S+)", script, re.M).group(1), re.search(rf"^{name}=(\S+)", lib, re.M).group(1), name)

    def test_a_fresh_mac_gets_one_ssh_connection_as_the_main_one(self):
        home = Path(tempfile.mkdtemp())
        reg = config(home, "--host", "100.64.1.2", "--label", "Sam's server")
        self.assertEqual((reg["version"], reg["primary"], reg["lastUsed"], reg["launchMode"]), (2, "sam-s-server", "sam-s-server", "primary"))
        self.assertEqual([c["id"] for c in reg["connections"]], ["local", "sam-s-server"])
        ssh = reg["connections"][1]
        self.assertEqual((ssh["kind"], ssh["host"], ssh["user"], ssh["label"]), ("ssh", "100.64.1.2", "hermes", "Sam's server"))
        self.assertEqual(ssh["keyPath"], str(home / ".ssh" / "id_ed25519_hermes_desktop"))
        self.assertNotIn("password", json.dumps(reg).lower())

    def test_an_existing_connections_file_keeps_its_other_connections_and_never_doubles_ours(self):
        home = Path(tempfile.mkdtemp())
        d = home / "Library" / "Application Support" / "Hermes"
        d.mkdir(parents=True)
        (d / "connections.json").write_text(json.dumps({"version": 2, "primary": "local", "launchMode": "primary", "lastUsed": "local", "connections": [
            {"id": "local", "kind": "local", "label": "This device"}, {"id": "old", "kind": "ssh", "label": "Old box", "host": "10.0.0.5", "user": "bob"},
            {"id": "my-hermes-server", "kind": "ssh", "label": "My Hermes server", "host": "100.64.1.2", "user": "hermes"}]}))
        reg = config(home, "--host", "100.64.1.2")
        self.assertEqual([c["id"] for c in reg["connections"]], ["local", "old", "my-hermes-server"])
        self.assertEqual(reg["primary"], "my-hermes-server")
        self.assertIn("keyPath", reg["connections"][2])

    def test_no_key_is_written_into_the_script(self):
        self.assertIsNone(re.search(r"AKIA|sk-[A-Za-z0-9]{20}|BEGIN (OPENSSH|RSA) PRIVATE", SCRIPT.read_text()))


if __name__ == "__main__":
    unittest.main()
