#!/usr/bin/env python3
"""Signs in to the university's single sign-on with a headless browser and prints the Moodle session cookie.

Runs as its own locked-down user (`unilogin`): the password and the authenticator secret live in that user's private folder,
which the agents cannot read. Only the root-owned `uni-login` command ever runs this, and it only ever prints the cookie.

  uni_login.py save     read the email, password and authenticator secret from stdin (one per line) and keep them private
  uni_login.py totp     print the current 6-digit code (to compare with the phone app)
  uni_login.py login    sign in and print the MoodleSession value on stdout (everything else goes to stderr)
  uni_login.py status   one line: configured or not, and how the last sign-in went

The authenticator is the standard time-based code (RFC 6238): any app that scans or accepts the same secret shows the same
codes, so the phone keeps working. A sign-in is tried at most once a few minutes apart, and never again after a wrong
password, so the university can't lock the account for repeated bad attempts.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import time
import urllib.parse

CFG_FILE = os.environ.get("UNI_LOGIN_CONFIG", "/etc/uni-login/config.json")
PRIV = os.environ.get("UNI_LOGIN_PRIVATE", "/var/lib/uni-login/private")
CREDS_FILE = os.path.join(PRIV, "creds.json")
LAST_FILE = os.path.join(PRIV, "last.json")
SHOT_FILE = os.path.join(PRIV, "last-failure.png")

MIN_GAP_AFTER_OK = 120          # seconds between two sign-ins that worked
MIN_GAP_AFTER_FAIL = 1800       # and after one that didn't
HARD_STOP = {"wrong-password", "locked", "account-disabled"}   # never retried until `setup` is run again
OVERALL_SECONDS = 150

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")


# ---------------------------------------------------------------- authenticator code (RFC 6238, SHA-1, 6 digits, 30 s)
def clean_secret(secret):
    s = re.sub(r"[\s-]", "", secret or "").upper().rstrip("=")
    if not re.fullmatch(r"[A-Z2-7]{16,}", s):
        raise ValueError("That isn't an authenticator secret (letters A-Z and digits 2-7, at least 16 characters).")
    return s


def totp(secret, at=None, step=30, digits=6):
    s = clean_secret(secret)
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    val = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(val).zfill(digits)


def seconds_left(step=30):
    return step - int(time.time()) % step


# ---------------------------------------------------------------- files
def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_private(path, obj):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def config():
    c = load_json(CFG_FILE, {}) or {}
    url = (c.get("moodle_url") or "").rstrip("/")
    if not url.startswith("https://") and not url.startswith("http://"):
        raise SystemExit("uni-login: no Moodle address in %s" % CFG_FILE)
    c["moodle_url"] = url
    return c


def record(ok, step, reason="", detail=""):
    save_private(LAST_FILE, {"ok": ok, "at": int(time.time()), "step": step, "reason": reason, "detail": detail})


# ---------------------------------------------------------------- the browser flow
# Pages are recognised by what is on them (ids Microsoft's sign-in uses, the university's IdP buttons), not by their text, so
# a reworded page still works. Each step has a limit on how often it may act: the password is typed once, a code twice.
LIMITS = {"continue": 3, "chooser": 2, "email": 2, "password": 1, "otc": 2, "another-way": 3, "method-list": 2, "kmsi": 3}
SETTLE_SECONDS = 8


def visible(page, selector):
    try:
        loc = page.locator(selector).first
        return loc.count() > 0 and loc.is_visible()
    except Exception:
        return False


def page_error(page):
    """The reason code for an error message on the page, or ''."""
    for sel in ("#passwordError", "#usernameError", "#idTD_Error", "#idSpan_SAOTCC_Error_OTC", "#idSpan_SAOTCAS_Error",
                "#service_exception_message", "[role=alert]"):
        if visible(page, sel):
            try:
                text = page.locator(sel).first.inner_text(timeout=2000).lower()
            except Exception:
                text = ""
            if not text.strip():
                continue
            if "locked" in text:
                return "locked"
            if "disabled" in text or "blocked" in text:
                return "account-disabled"
            if sel == "#idSpan_SAOTCC_Error_OTC" or "code" in text or "verification" in text:
                return "bad-code"
            if "password" in text or "incorrect" in text or "doesn't exist" in text or "couldn't find" in text:
                return "wrong-password"
            return "page-error"
    return ""


def detect(page):
    """Which sign-in step is showing now."""
    if visible(page, "input[name=otc]"):
        return "otc"
    if visible(page, "[data-value=PhoneAppOTP]"):
        return "method-list"
    if visible(page, "input[name=passwd], input[type=password]"):
        return "password"
    if visible(page, "input[name=loginfmt]"):
        return "email"
    if visible(page, "button[name=_eventId_AzureAuthn]"):
        return "chooser"
    if visible(page, "input[type=submit][value=Continue]"):
        return "continue"
    if visible(page, "#idDiv_SAOTCAS_Title, #idRichContext_DisplaySign"):
        return "push" if not visible(page, "#signInAnotherWay") else "another-way"
    if visible(page, "#signInAnotherWay"):
        return "another-way"
    if visible(page, "#KmsiDescription, #idBtn_Back"):
        return "kmsi"
    if visible(page, "#idSubmit_ProofUp_Redirect, #idDiv_ProofUp"):
        return "needs-setup"
    return ""


def moodle_landing(page, host):
    u = urllib.parse.urlparse(page.url)
    return u.netloc == host and not re.match(r"^/(login|auth)(/|$)", u.path)


def drive(page, ctx, cfg, creds):
    """Walks the sign-in pages. Returns (cookie, step, reason, detail)."""
    moodle = cfg["moodle_url"]
    host = urllib.parse.urlparse(moodle).netloc
    start = cfg.get("login_url") or "%s/auth/saml2/login.php?wants=%s" % (moodle, urllib.parse.quote(moodle + "/my/", safe=""))
    deadline = time.time() + OVERALL_SECONDS
    used = {}
    acted_at = {}
    last_code = None
    page.goto(start, wait_until="domcontentloaded", timeout=45000)
    last_step = "start"
    while time.time() < deadline:
        page.wait_for_timeout(800)
        if moodle_landing(page, host):
            for c in ctx.cookies():
                if c["name"] == "MoodleSession" and host.split(":")[0] in c["domain"]:
                    return c["value"], "done", "", ""
        step = detect(page)
        err = page_error(page)
        if err and (err in HARD_STOP or step in ("password", "email") and used.get(step)):
            return None, step or last_step, err, ""
        if err == "bad-code" and used.get("otc", 0) >= LIMITS["otc"]:
            return None, "otc", "bad-code", ""
        if step == "needs-setup":
            return None, step, "needs-setup", "The university wants the sign-in method set up first (More information required)."
        if step == "push":
            return None, step, "only-push", "Only an approve-on-the-phone prompt is available; add an authenticator-app code method."
        if not step:
            if time.time() - acted_at.get("_idle", time.time()) > 25 and "_idle" in acted_at:
                u = urllib.parse.urlparse(page.url)
                return None, last_step, "stuck", "%s%s: %s" % (u.netloc, u.path, (page.title() or "")[:80])
            acted_at.setdefault("_idle", time.time())
            continue
        acted_at.pop("_idle", None)
        if step in acted_at and time.time() - acted_at[step] < SETTLE_SECONDS:
            continue          # we just acted here; give the page time to move on
        used[step] = used.get(step, 0) + 1
        if used[step] > LIMITS.get(step, 2):
            return None, step, "repeat-" + step, ""
        acted_at[step] = time.time()
        last_step = step
        if step == "continue":
            page.locator("input[type=submit][value=Continue]").first.click()
        elif step == "chooser":
            page.locator("button[name=_eventId_AzureAuthn]").first.click()
        elif step == "email":
            f = page.locator("input[name=loginfmt]").first
            f.fill(creds["email"])
            f.press("Enter")
        elif step == "password":
            f = page.locator("input[name=passwd], input[type=password]").first
            f.fill(creds["password"])
            f.press("Enter")
        elif step == "another-way":
            page.locator("#signInAnotherWay").first.click()
        elif step == "method-list":
            page.locator("[data-value=PhoneAppOTP]").first.click()
        elif step == "otc":
            code = totp(creds["totp_secret"])
            if code == last_code:                     # the same code twice in one window is refused: wait for the next
                page.wait_for_timeout((seconds_left() + 1) * 1000)
                code = totp(creds["totp_secret"])
            elif seconds_left() <= 3:                  # about to roll over: use the fresh one
                page.wait_for_timeout(4000)
                code = totp(creds["totp_secret"])
            last_code = code
            f = page.locator("input[name=otc]").first
            f.fill(code)
            f.press("Enter")
        elif step == "kmsi":
            btn = page.locator("#idBtn_Back")
            (btn if visible(page, "#idBtn_Back") else page.locator("#idSIButton9")).first.click()
    u = urllib.parse.urlparse(page.url)
    return None, last_step, "timeout", "%s%s" % (u.netloc, u.path)


def cmd_login(force=False):
    cfg = config()
    creds = load_json(CREDS_FILE)
    if not creds or not all(creds.get(k) for k in ("email", "password", "totp_secret")):
        record(False, "start", "not-configured")
        print("uni-login: not set up. Run: sudo uni-login setup", file=sys.stderr)
        return 2
    last = load_json(LAST_FILE, {}) or {}
    age = time.time() - last.get("at", 0)
    if last.get("reason") in HARD_STOP and last.get("at", 0) >= creds.get("saved_at", 0):
        print("uni-login: not trying again: the last attempt said %s. Run: sudo uni-login setup" % last["reason"], file=sys.stderr)
        return 4
    if not force and last.get("at") and age < (MIN_GAP_AFTER_OK if last.get("ok") else MIN_GAP_AFTER_FAIL):
        print("uni-login: tried %d s ago (%s); waiting before trying again" % (age, "worked" if last.get("ok") else last.get("reason")),
              file=sys.stderr)
        return 5
    record(False, "start", "running")      # a crash mid-way still counts as an attempt (never hammer the sign-in)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        record(False, "start", "no-browser-library")
        print("uni-login: the browser library isn't installed (run the installer again)", file=sys.stderr)
        return 3
    cookie, step, reason, detail = None, "start", "crashed", ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                                                             "--disable-extensions", "--disable-background-networking",
                                                             "--blink-settings=imagesEnabled=false"])
            try:
                ctx = browser.new_context(user_agent=UA, locale="en-GB", timezone_id=cfg.get("timezone", "Europe/London"),
                                          viewport={"width": 1100, "height": 800})
                ctx.route(re.compile(r".*\.(png|jpe?g|gif|webp|svg|woff2?|ttf|mp4)(\?.*)?$"), lambda r: r.abort())
                page = ctx.new_page()
                page.set_default_timeout(20000)
                try:
                    cookie, step, reason, detail = drive(page, ctx, cfg, creds)
                except Exception as e:                  # a Playwright timeout or a closed page: name the kind, never the text
                    cookie, step, reason, detail = None, "browser", type(e).__name__, ""
                if not cookie:
                    try:
                        page.screenshot(path=SHOT_FILE)
                        os.chmod(SHOT_FILE, 0o600)
                    except Exception:
                        pass
            finally:
                browser.close()
    except Exception as e:                              # the browser itself wouldn't start (missing, out of memory...)
        cookie, step, reason, detail = None, "launch", "browser-" + type(e).__name__, ""
    if cookie:
        record(True, "done")
        print(cookie)
        return 0
    record(False, step, reason, detail)
    print("uni-login: sign-in failed at '%s' (%s) %s" % (step, reason, detail), file=sys.stderr)
    return 3


# ---------------------------------------------------------------- setup and status
def cmd_save():
    """Reads email, password and authenticator secret (one per line) from stdin; `uni-login setup` collects them at hidden prompts."""
    lines = sys.stdin.read().split("\n")
    email, password, secret = (lines + ["", "", ""])[:3]
    email = email.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        print("That doesn't look like an email address. Nothing saved.")
        return 1
    if not password:
        print("No password given. Nothing saved.")
        return 1
    try:
        secret = clean_secret(secret)
    except ValueError as e:
        print(e, "Nothing saved.")
        return 1
    save_private(CREDS_FILE, {"email": email, "password": password, "totp_secret": secret, "saved_at": int(time.time())})
    if os.path.exists(LAST_FILE):
        os.remove(LAST_FILE)
    print("Saved. The code right now should match your phone app's code: %s  (it changes in %d s)" % (totp(secret), seconds_left()))
    return 0


def cmd_status():
    creds = load_json(CREDS_FILE)
    if not creds:
        print("not set up")
        return 1
    last = load_json(LAST_FILE) or {}
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last["at"])) if last.get("at") else "never"
    print("set up for %s; last sign-in: %s at %s" % (re.sub(r"^(.).*@", r"\1***@", creds.get("email", "")),
                                                    "worked" if last.get("ok") else (last.get("reason") or "not yet tried"), when))
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "save":
        return cmd_save()
    if cmd == "totp":
        creds = load_json(CREDS_FILE)
        print(totp(creds["totp_secret"]) if creds else "not set up")
        return 0 if creds else 1
    if cmd == "login":
        return cmd_login(force="--force" in argv)
    if cmd == "status":
        return cmd_status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
