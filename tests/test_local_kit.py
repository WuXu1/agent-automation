"""The laptop commands outlive the cloned folder: laptop/lib.sh sync_local_kit copies them into ~/.agent-automation, and the launcher runs them from there.
Run: python3 -m unittest discover -s tests"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bash(script: str, home: Path, **env) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env={**os.environ, "HOME": str(home), "SHELL": "/bin/zsh", "KIT_DIR": str(ROOT), **env})


# vm_ssh is replaced by running the command here, so "the server's kit" is this repository.
SYNC = f'. "{ROOT}/laptop/lib.sh"; vm_ssh() {{ bash -c "$1"; }}; REMOTE_KIT="{ROOT}"; sync_local_kit'


class LocalKitTest(unittest.TestCase):
    def test_every_file_the_laptop_commands_need_is_in_the_list(self):
        home = Path(tempfile.mkdtemp())
        r = bash(SYNC, home)
        self.assertEqual(r.returncode, 0, r.stderr)
        kit = home / ".agent-automation" / "kit"
        for f in ("hermes", "laptop/lib.sh", "laptop/desktop.sh", "vm/backup/laptop-authorize.sh"):
            self.assertTrue((kit / f).is_file(), f)
        # nothing else of the kit is read by those scripts at run time
        for name in ("hermes", "laptop/desktop.sh", "vm/backup/laptop-authorize.sh"):
            text = (kit / name).read_text()
            for other in ("laptop/azure.sh", "laptop/prereqs.sh", "vm/lib.sh", "vm/hermeslib.py", "dashboard/"):
                self.assertNotIn(f'"$KIT_DIR/{other}', text, f"{name} reads {other}")

    def test_the_launcher_runs_the_copy_without_the_cloned_folder(self):
        home = Path(tempfile.mkdtemp())
        self.assertEqual(bash(SYNC, home).returncode, 0)
        r = subprocess.run([str(home / ".agent-automation" / "bin" / "hermes"), "help"], capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hermes status", r.stdout)

    def test_a_second_sync_replaces_the_copy_and_a_failed_one_keeps_it(self):
        home = Path(tempfile.mkdtemp())
        self.assertEqual(bash(SYNC, home).returncode, 0)
        kit = home / ".agent-automation" / "kit"
        (kit / "hermes").write_text("old")
        self.assertEqual(bash(SYNC, home).returncode, 0)
        self.assertNotEqual((kit / "hermes").read_text(), "old")
        broken = bash(SYNC.replace(f'REMOTE_KIT="{ROOT}"', 'REMOTE_KIT="/nonexistent"'), home)
        self.assertNotEqual(broken.returncode, 0)
        self.assertTrue((kit / "hermes").is_file())
        self.assertFalse((home / ".agent-automation" / "kit.new").exists())

    def test_the_path_line_is_added_once_to_the_shell_startup_file(self):
        home = Path(tempfile.mkdtemp())
        script = f'. "{ROOT}/laptop/lib.sh"; add_hermes_to_path; add_hermes_to_path'
        r = bash(script, home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((home / ".zshrc").read_text().count(".agent-automation/bin"), 1)

    def test_hermes_cli_never_waits_on_a_terminal(self):
        text = (ROOT / "vm" / "lib.sh").read_text()
        self.assertIn("setsid", text)
        self.assertRegex(text, r"hermes_cli\(\) \{ AS_HERMES_DETACHED=1 as_hermes .*</dev/null")

    def test_the_server_install_starts_from_the_root_directory(self):
        text = (ROOT / "vm" / "install.sh").read_text()
        self.assertLess(text.index("\ncd /"), text.index("lib.sh"))


if __name__ == "__main__":
    unittest.main()
