#!/usr/bin/env python3
"""Gmail reader that can read mail and save drafts, nothing else.

Talks IMAP to imap.gmail.com with the owner's app password (read from
/data/.hermes/owner/.secrets/gmail.env). The mailbox is always opened read-only and
messages are fetched with BODY.PEEK, so reading never marks mail as read. The only
write is `draft`, which APPENDs a message to [Gmail]/Drafts. There is no SMTP code
here and no delete, move, flag or expunge call, so it cannot send or change mail.

Usage:
  gmail_read.py list [--limit N] [--unread] [--folder NAME]   recent mail as JSON
  gmail_read.py search "QUERY" [--limit N]                      Gmail search syntax (from:, subject:, newer_than:2d ...)
  gmail_read.py read N                                          full text of row N from the last list/search
  gmail_read.py draft --to ADDR --subject S [--reply-to N]      body on stdin; saved to Drafts, the owner sends it
  gmail_read.py check                                           silent if login works, else an alert
"""
import argparse
import email
import email.policy
import imaplib
import json
import re
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

SECRETS = Path("/data/.hermes/owner/.secrets/gmail.env")
LAST = Path("/data/.hermes/gmail_last.json")
DRAFTS = "[Gmail]/Drafts"
ALL_MAIL = '"[Gmail]/All Mail"'
BODY_LIMIT = 8000


def creds():
    vals = {}
    for line in SECRETS.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals["GMAIL_ADDRESS"], vals["GMAIL_APP_PASSWORD"].replace(" ", "")


def connect():
    addr, pw = creds()
    m = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    m.login(addr, pw)
    return m, addr


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))


def hdr(msg, name):
    return re.sub(r"\s+", " ", str(msg.get(name, ""))).strip()


def body_text(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return "(no text body)"
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?s)<(script|style).*?</\1>", "", text)
        text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def rows_for(m, ids, limit, folder):
    rows = []
    for uid in list(reversed(ids))[:limit]:
        _, data = m.uid("fetch", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.300>)")
        raw_head = next((p[1] for p in data if isinstance(p, tuple) and b"HEADER" in p[0]), b"")
        raw_prev = next((p[1] for p in data if isinstance(p, tuple) and b"TEXT" in p[0]), b"")
        flags = b" ".join(p[0] for p in data if isinstance(p, tuple))
        msg = email.message_from_bytes(raw_head, policy=email.policy.default)
        prev = re.sub(r"\s+", " ", raw_prev.decode("utf-8", "replace")).strip()[:200]
        rows.append({"n": len(rows) + 1, "uid": uid.decode(), "folder": folder, "unread": b"\\Seen" not in flags,
                     "from": hdr(msg, "From"), "subject": hdr(msg, "Subject"),
                     "received": hdr(msg, "Date"), "preview": prev})
    LAST.write_text(json.dumps(rows))
    return rows


def cmd_list(a):
    m, _ = connect()
    m.select(a.folder, readonly=True)
    _, d = m.uid("search", None, "UNSEEN" if a.unread else "ALL")
    out({"emails": rows_for(m, d[0].split(), a.limit, a.folder)})


def cmd_search(a):
    m, _ = connect()
    m.select(ALL_MAIL, readonly=True)
    _, d = m.uid("search", None, "X-GM-RAW", '"' + a.query.replace("\\", "\\\\").replace('"', '\\"') + '"')
    out({"emails": rows_for(m, d[0].split(), a.limit, ALL_MAIL)})


def fetch_full(m, uid):
    _, data = m.uid("fetch", uid, "(BODY.PEEK[])")
    raw = next(p[1] for p in data if isinstance(p, tuple))
    return email.message_from_bytes(raw, policy=email.policy.default)


def last_row(n):
    rows = json.loads(LAST.read_text())
    return rows[n - 1]


def cmd_read(a):
    m, _ = connect()
    row = last_row(a.n)
    m.select(row["folder"], readonly=True)
    msg = fetch_full(m, row["uid"])
    text = body_text(msg)
    out({"from": hdr(msg, "From"), "to": hdr(msg, "To"), "date": hdr(msg, "Date"),
         "subject": hdr(msg, "Subject"), "attachments": [p.get_filename() for p in msg.iter_attachments()],
         "body": text[:BODY_LIMIT], "truncated": len(text) > BODY_LIMIT})


def cmd_draft(a):
    m, addr = connect()
    draft = EmailMessage()
    draft["From"], draft["To"], draft["Subject"] = addr, a.to, a.subject
    draft["Date"], draft["Message-ID"] = formatdate(localtime=True), make_msgid()
    if a.reply_to:
        row = last_row(a.reply_to)
        m.select(row["folder"], readonly=True)
        orig = fetch_full(m, row["uid"])
        if orig["Message-ID"]:
            draft["In-Reply-To"] = orig["Message-ID"]
            draft["References"] = (str(orig.get("References", "")) + " " + orig["Message-ID"]).strip()
    draft.set_content(sys.stdin.read())
    typ, _ = m.append(DRAFTS, "\\Draft", None, draft.as_bytes())
    out({"saved": typ == "OK", "folder": "Drafts", "note": "Draft only. The owner reviews and sends it from Gmail."})


def cmd_check(a):
    try:
        connect()
    except Exception as e:
        print(f"Gmail login failed ({type(e).__name__}): the app password may have been revoked. Tell the owner.")
        sys.exit(1)


p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
s = sub.add_parser("list"); s.add_argument("--limit", type=int, default=15); s.add_argument("--unread", action="store_true"); s.add_argument("--folder", default="INBOX"); s.set_defaults(f=cmd_list)
s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--limit", type=int, default=15); s.set_defaults(f=cmd_search)
s = sub.add_parser("read"); s.add_argument("n", type=int); s.set_defaults(f=cmd_read)
s = sub.add_parser("draft"); s.add_argument("--to", required=True); s.add_argument("--subject", required=True); s.add_argument("--reply-to", type=int); s.set_defaults(f=cmd_draft)
s = sub.add_parser("check"); s.set_defaults(f=cmd_check)
a = p.parse_args()
try:
    a.f(a)
except (imaplib.IMAP4.error, FileNotFoundError, KeyError) as e:
    out({"error": "gmail_unavailable", "detail": f"{type(e).__name__}: {e}"})
    sys.exit(1)
