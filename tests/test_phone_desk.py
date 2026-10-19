"""The phone desk (vm/phone) is kept with {{OWNER}}-style placeholders for the names. Fill them in with two different sets of names
(the author's and somebody else's) and run the desk's own tests on each: a name hard-wired anywhere shows up as a failure."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PHONE = os.path.join(HERE, "..", "vm", "phone")
NAME_SETS = {
    "first": ["OWNER=Max", "CHIEF=Carl", "TUTOR=Tom", "ASSISTANT=Anna", "COACH=Conner", "SIR=Sir", "sir=sir"],
    "second": ["OWNER=Logan", "CHIEF=Cal", "TUTOR=Tutor", "ASSISTANT=Assistant", "COACH=Coach", "SIR=Logan", "sir=Logan"],
}


class PhoneDeskTest(unittest.TestCase):
    def run_with(self, names):
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, "desk-rendered")
            args = [sys.executable, os.path.join(PHONE, "render.py"), PHONE, dst]
            for item in names:
                args += ["--name", item]
            subprocess.run(args, check=True, capture_output=True)
            done = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", "-m", "unittest", "discover", "-s", "desk/tests"],
                                  cwd=dst, capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr[-3000:])
            self.assertNotIn("{{OWNER}}", "".join(open(os.path.join(dp, f), errors="ignore").read()
                                                  for dp, _, fs in os.walk(dst) for f in fs if f.endswith((".py", ".md"))))

    def test_the_desk_works_with_the_first_set_of_names(self):
        self.run_with(NAME_SETS["first"])

    def test_the_desk_works_with_a_different_set_of_names(self):
        self.run_with(NAME_SETS["second"])

    def test_the_installer_has_valid_shell(self):
        subprocess.run(["bash", "-n", os.path.join(PHONE, "install.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
