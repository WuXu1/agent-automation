"""uni-login: the authenticator code (against the RFC 6238 test values) and the whole sign-in walk against a fake university
that serves the same page ids as the real ones (a Moodle host, the university's IdP and a Microsoft-style sign-in).
The browser part is skipped where Playwright's Chromium isn't installed."""
import http.server
import importlib.util
import json
import os
import socketserver
import tempfile
import threading
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("uni_login", os.path.join(HERE, "..", "vm", "tools", "uni-login", "uni_login.py"))
ul = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ul)

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"   # "12345678901234567890"
PASSWORD = "correct horse"
APP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
COOKIE = "abc123LOGGEDINcookie456"


class TotpTest(unittest.TestCase):
    def test_rfc6238_vectors(self):
        # RFC 6238 appendix B (SHA-1), the last six digits of the 8-digit values
        self.assertEqual(ul.totp(RFC_SECRET, at=59), "287082")
        self.assertEqual(ul.totp(RFC_SECRET, at=1111111109), "081804")
        self.assertEqual(ul.totp(RFC_SECRET, at=1234567890), "005924")

    def test_secret_formats(self):
        spaced = " ".join(RFC_SECRET[i:i + 4] for i in range(0, len(RFC_SECRET), 4)).lower()
        self.assertEqual(ul.totp(spaced, at=59), "287082")
        for bad in ("", "short", "0189" * 8, "not base32 !!!!!!!!!!!!"):
            with self.assertRaises(ValueError):
                ul.clean_secret(bad)


class FakeUniversity(http.server.BaseHTTPRequestHandler):
    scenario = "direct"
    log = []

    def log_message(self, *a):
        pass

    def send(self, body="", code=200, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def redirect(self, to, headers=None):
        self.send("", 302, dict({"Location": to}, **(headers or {})))

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}

    def do_GET(self):
        self.route(self.path, {})

    def do_POST(self):
        self.route(self.path, self.form())

    def route(self, path, form):
        host = self.headers["Host"]
        port = host.split(":")[1]
        idp = "http://127.0.0.1:%s" % port
        moodle = "http://localhost:%s" % port
        path = path.split("?")[0]
        cls = type(self)
        cls.log.append(path)
        if host.startswith("localhost"):
            if path == "/auth/saml2/login.php":
                return self.redirect(idp + "/idp/sso")
            if path == "/auth/saml2/acs":
                return self.redirect("/my/", {"Set-Cookie": "MoodleSession=%s; Path=/" % COOKIE})
            if path == "/my/":
                return self.send("<h1>Dashboard</h1>")
            return self.send("", 404)
        if path == "/idp/sso":
            return self.send('<title>Loading Session Information</title><form method=post action=/idp/chooser>'
                             '<input name=_eventId_proceed type=hidden><input type=submit value=Continue></form>')
        if path == "/idp/chooser":
            return self.send('<form method=post action=/ms/email><button type=submit name=_eventId_AzureAuthn>UofG email</button></form>')
        if path == "/ms/email":
            if "loginfmt" in form:
                cls.log.append("email=" + form["loginfmt"])
                return self.redirect("/ms/password")
            # Microsoft keeps the password box in the email page too, parked off-screen: it must not be taken for the password step
            return self.send('<form method=post action=/ms/email><input name=loginfmt type=email>'
                             '<input name=passwd type=password style="position:absolute;left:-10000px">'
                             '<input type=submit id=idSIButton9 value=Next></form>')
        if path == "/ms/password":
            return self.send('<form method=post action=/ms/check><input name=passwd type=password></form>')
        if path == "/ms/check":
            if form.get("passwd") != PASSWORD:
                return self.send('<div id=passwordError>Your account or password is incorrect.</div>'
                                 '<form method=post action=/ms/check><input name=passwd type=password></form>')
            if cls.scenario == "setup":
                return self.send('<div id=idDiv_ProofUp><button id=idSubmit_ProofUp_Redirect>Next</button></div>')
            if cls.scenario == "push" or cls.scenario == "onlypush":
                more = '<a id=signInAnotherWay href=/ms/methods>Sign in another way</a>' if cls.scenario == "push" else ""
                return self.send('<div id=idDiv_SAOTCAS_Title>Approve sign in request</div>' + more)
            return self.redirect("/ms/otcpage")
        if path == "/ms/methods":
            return self.send('<a data-value=PhoneAppOTP href=/ms/otcpage>Use a verification code</a>')
        if path == "/ms/otcpage":
            return self.send('<form method=post action=/ms/otc><input name=otc></form>')
        if path == "/ms/otc":
            if cls.scenario == "badcode" or form.get("otc") != ul.totp(APP_SECRET):
                return self.send('<span id=idSpan_SAOTCC_Error_OTC>The code is incorrect</span>'
                                 '<form method=post action=/ms/otc><input name=otc></form>')
            return self.send('<div id=KmsiDescription>Stay signed in?</div><a id=idBtn_Back href=/ms/done>No</a>')
        if path == "/ms/done":
            return self.redirect(moodle + "/auth/saml2/acs")
        return self.send("", 404)


def have_browser():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True, args=["--no-sandbox"]).close()
        return True
    except Exception:
        return False


@unittest.skipUnless(have_browser(), "Playwright's Chromium isn't installed here")
class SignInWalkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeUniversity)
        cls.srv.daemon_threads = True
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        ul.PRIV = self.tmp
        ul.CREDS_FILE = os.path.join(self.tmp, "creds.json")
        ul.LAST_FILE = os.path.join(self.tmp, "last.json")
        ul.SHOT_FILE = os.path.join(self.tmp, "shot.png")
        ul.CFG_FILE = os.path.join(self.tmp, "config.json")
        ul.SETTLE_SECONDS = 1
        ul.seconds_left = lambda step=30: 10            # never wait for a rollover in a test
        with open(ul.CFG_FILE, "w") as f:
            json.dump({"moodle_url": "http://localhost:%d" % self.port}, f)
        self.creds = {"email": "s123@student.example.ac.uk", "password": PASSWORD, "totp_secret": APP_SECRET, "saved_at": 1}
        ul.save_private(ul.CREDS_FILE, self.creds)
        FakeUniversity.log = []

    def run_login(self, scenario, creds=None):
        FakeUniversity.scenario = scenario
        if creds:
            ul.save_private(ul.CREDS_FILE, creds)
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ul.cmd_login(force=True)
        return code, out.getvalue().strip(), err.getvalue(), ul.load_json(ul.LAST_FILE)

    def test_direct_code_prompt(self):
        code, out, err, last = self.run_login("direct")
        self.assertEqual((code, out), (0, COOKIE), err)
        self.assertTrue(last["ok"])
        self.assertIn("email=" + self.creds["email"], FakeUniversity.log)
        self.assertEqual(FakeUniversity.log.count("/ms/check"), 1)

    def test_push_prompt_then_another_way(self):
        code, out, err, _ = self.run_login("push")
        self.assertEqual((code, out), (0, COOKIE), err)

    def test_wrong_password_is_typed_once_and_blocks_retries(self):
        bad = dict(self.creds, password="nope")
        code, out, err, last = self.run_login("direct", bad)
        self.assertEqual(code, 3)
        self.assertEqual(last["reason"], "wrong-password")
        self.assertEqual(FakeUniversity.log.count("/ms/check"), 1)      # one try at the password, never two
        self.assertNotIn("nope", json.dumps(last) + err)
        # a later (non-forced) run refuses until `setup` has saved new details
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ul.cmd_login(force=False), 4)

    def test_only_phone_approval_is_reported(self):
        code, out, err, last = self.run_login("onlypush")
        self.assertEqual((code, last["reason"]), (3, "only-push"))

    def test_account_needing_setup_is_reported(self):
        code, out, err, last = self.run_login("setup")
        self.assertEqual((code, last["reason"]), (3, "needs-setup"))

    def test_wrong_secret_gives_up_after_two_codes(self):
        code, out, err, last = self.run_login("direct", dict(self.creds, totp_secret=RFC_SECRET))
        self.assertEqual((code, last["reason"]), (3, "bad-code"))
        self.assertLessEqual(FakeUniversity.log.count("/ms/otc"), 2)
        self.assertNotIn(RFC_SECRET, err)

    def test_not_set_up(self):
        os.remove(ul.CREDS_FILE)
        self.assertEqual(self.run_login("direct")[0], 2)

    def test_the_cookie_is_the_only_stdout(self):
        code, out, err, _ = self.run_login("direct")
        self.assertEqual(out, COOKIE)
        self.assertNotIn(PASSWORD, out + err)
        self.assertNotIn(APP_SECRET, out + err)


@unittest.skipUnless(have_browser() and all(os.path.exists(os.path.join(d, c)) for c in ("jq", "flock") for d in ("/usr/bin", "/bin")),
                     "needs Playwright's Chromium, jq and flock")
class RootCommandTest(unittest.TestCase):
    """The root-owned `uni-login` command (setup aside, which needs a terminal) against the same fake university:
    it must put the new cookie into the agents' env files, keep their other lines, and keep an honest status."""
    CLI = os.path.join(HERE, "..", "vm", "tools", "uni-login", "uni-login")

    @classmethod
    def setUpClass(cls):
        cls.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeUniversity)
        cls.srv.daemon_threads = True
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        import subprocess
        import sys
        self.sp = subprocess
        self.tmp = tempfile.mkdtemp()
        t = self.tmp
        for d in ("state/private", "state/home", "run", "bin", "lib"):
            os.makedirs(os.path.join(t, d))
        self.envs = [os.path.join(t, "tutor.env"), os.path.join(t, "assistant.env")]
        for f in self.envs:
            with open(f, "w") as h:
                h.write("OTHER=keep\nMOODLE_TOKEN=oldcookie\n")
            os.chmod(f, 0o600)
        self.cfg = os.path.join(t, "config.json")
        json.dump({"moodle_url": "http://localhost:%d" % self.port, "targets": self.envs + [os.path.join(t, "missing.env")],
                   "restart_cmd": os.path.join(t, "bin", "restart")}, open(self.cfg, "w"))
        stubs = {"runuser": 'shift 3\nexec "$@"\n',     # no second user in a test: run the rest as ourselves
                 "systemd-run": 'while [ "$1" != "--" ]; do shift; done; shift\necho "$@" >> %s/restarted\n' % t}
        for name, body in stubs.items():
            path = os.path.join(t, "bin", name)
            open(path, "w").write("#!/bin/bash\n" + body)
            os.chmod(path, 0o755)
        # the helper runs with the test's Python, which has Playwright; its settings come from the UNI_* variables
        import shutil
        shutil.copy(os.path.join(HERE, "..", "vm", "tools", "uni-login", "uni_login.py"), os.path.join(t, "lib", "uni_login.py"))
        self.env = dict(os.environ, PATH=os.path.join(t, "bin") + ":" + os.environ["PATH"], UNI_CFG=self.cfg,
                        UNI_STATE=os.path.join(t, "state"), UNI_RUN=os.path.join(t, "run"), UNI_PY=sys.executable,
                        UNI_LIB=os.path.join(t, "lib"),
                        UNI_BROWSERS=os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
        ul.save_private(os.path.join(t, "state", "private", "creds.json"),
                        {"email": "s1@student.example.ac.uk", "password": PASSWORD, "totp_secret": APP_SECRET, "saved_at": 1})
        open(os.path.join(t, "state", "configured"), "w").close()
        FakeUniversity.scenario = "direct"

    def cli(self, *args):
        return self.sp.run(["bash", self.CLI, *args], env=self.env, capture_output=True, text=True, timeout=200)

    def read(self, *parts):
        return open(os.path.join(self.tmp, *parts)).read()

    def test_refresh_writes_the_cookie_everywhere_and_restarts(self):
        r = self.cli("refresh", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in self.envs:
            self.assertEqual(open(f).read(), "OTHER=keep\nMOODLE_TOKEN=%s\n" % COOKIE)
            self.assertEqual(oct(os.stat(f).st_mode & 0o777), "0o600")
        self.assertTrue(self.read("state", "status").startswith("ok "))
        self.assertIn("restart", self.read("restarted"))
        self.assertNotIn(COOKIE, r.stdout + r.stderr)
        self.assertTrue(self.cli("state").stdout.startswith("configured ok "))

    def test_failed_sign_in_leaves_the_old_cookie_and_says_why(self):
        FakeUniversity.scenario = "onlypush"
        r = self.cli("refresh", "--force")
        self.assertEqual(r.returncode, 0)
        for f in self.envs:
            self.assertIn("MOODLE_TOKEN=oldcookie", open(f).read())
        parts = self.read("state", "status").split()
        self.assertEqual((parts[0], parts[2]), ("failed", "only-push"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "restarted")))

    def test_request_file_and_not_set_up(self):
        self.assertEqual(self.cli("request").returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "run", "request")))
        self.cli("refresh", "--force")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "run", "request")))   # a renewal clears the request
        os.remove(os.path.join(self.tmp, "state", "configured"))
        self.assertTrue(self.cli("state").stdout.startswith("none "))


if __name__ == "__main__":
    unittest.main()
