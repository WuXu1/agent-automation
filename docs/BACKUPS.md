# Backups to your Google Drive (optional)

Your agents' memory, settings, chats and your notebooks live on one small server. If that server is deleted, breaks, or your Azure credit
runs out, they are gone. This add-on makes one **encrypted** copy every night and puts it in **your own Google Drive**, so you can bring
everything back, on the same server or on a brand-new one.

- Every night at about **04:20** (your time) the server packs up everything that can't be rebuilt, locks it with **a passphrase only you
  know**, uploads it to the folder **`agent-automation-backups`** in your Drive, and deletes it from the server again.
- It keeps the last **35 days** (you can choose fewer) and deletes older ones itself.
- It is silent when it works. If a night fails, your chief of staff tells you on Telegram.

## What it costs

**Nothing.** rclone (the upload tool) and gpg (the lock) are free. There is no Azure storage involved.

- **Google Drive space:** each backup is up to about **250 MB** (a new install is much smaller; it grows with chats and memory).
  35 days of them is up to about **9 GB**. Google's free plan gives 15 GB, **shared with your Gmail and Google Photos**, so check
  how much you use at <https://one.google.com/storage> first. Tight on space? Choose 14 days when you set it up (about 3.5 GB).
  Old backups are deleted for good, not moved to the bin, so they never take space you can't see.
- **The server:** nothing is kept on it. For a few minutes at night it uses some spare disk space while it packs and uploads.
- **Network:** a few GB a month of upload, well inside the 100 GB a month that Azure gives free.

## What is in a backup

| Backed up | Where on the server |
|---|---|
| Your four agents: personalities, settings, their keys (`.env`), chat history, the board, scheduled jobs | `/data/.hermes` (and `/data/.hermes/profiles/…`) |
| Your notebooks | `/data/.hermes/owner/` |
| Your settings (`hermes.json`: your name, timezone, add-ons) | `/data/.hermes/hermes.json` |
| The shared memory ("second brain"): its database and settings | Postgres databases `mem0` and `mem0_app`, `/data/.hermes/mem0-server` |
| Files the agents made for you | `/data/workspace` |
| The tools' data (e.g. the Gmail sign-in) | `/data/tools` |

**Not backed up** (and why):

- Hermes Agent itself, the memory server's program, Python environments, caches and logs: `./install.sh` rebuilds them in minutes.
- The server's own settings (Tailscale, ssh, system services): a new server gets fresh ones from `./install.sh`.
- The backup's passphrase and its Google sign-in: they must never be inside the thing they protect. Keep the passphrase yourself.
- Anything outside the server: your Telegram chats are in Telegram, your email is in Gmail, and so on.
- Anything that changed after the last backup (at most one day's worth).

## Is it safe?

- The backup holds every key your agents use, so it is **encrypted (AES-256) with your passphrase before it leaves the server**.
  Google only ever stores scrambled data. A long passphrase matters: 12 characters is the minimum, a few random words is better.
- The Google sign-in uses Google's narrowest Drive permission, **`drive.file`**: rclone can only see and change the files it created
  itself (the backups). It cannot see anything else in your Drive.
- The passphrase and the sign-in are kept on the server in `/etc/hermes-backup/`, readable by the administrator (root) only. Your agents
  run as a normal user and cannot read them, or change the backup job.
- **Without the passphrase nobody can open a backup, including you.** There is no reset. Write it down.

## Setting it up (about 10 minutes, once)

You need: the Google account whose Drive should hold the backups, and a terminal in the `agent-automation` folder on your laptop.

### 1. Sign in to Google on your laptop

The server has no web browser, so the Google sign-in happens on your laptop and you paste the result into the server.

```bash
hermes backup-login
```

(Same thing without the `hermes` command: `bash vm/backup/laptop-authorize.sh`.)

It installs **rclone** if your laptop doesn't have it (it asks first). To install it yourself instead:

| Your computer | Install rclone |
|---|---|
| Mac | `brew install rclone` (or, without Homebrew: `curl https://rclone.org/install.sh \| sudo bash`) |
| Linux, or Ubuntu in WSL | `sudo apt install -y unzip curl && curl https://rclone.org/install.sh \| sudo bash` |
| Plain Windows (PowerShell, no WSL) | `winget install Rclone.Rclone`, open a new PowerShell, then `rclone authorize "drive" --drive-scope drive.file` |

Then:

1. **Mac:** a Google page opens in your browser. **Linux / WSL:** a link appears (`http://127.0.0.1:53682/auth?state=…`); open it in
   your browser. In WSL, paste it into your normal Windows browser; that works.
2. Choose the Google account for the backups and click **Allow**. Google says rclone may "see, edit, create and delete only the specific
   Google Drive files you use with this app": that is the narrow permission.
3. Back in the terminal, rclone prints:

   ```
   Paste the following into your remote machine --->
   {"access_token":"ya29.…","token_type":"Bearer","refresh_token":"1//…","expiry":"…"}
   <---End paste
   ```

   **Copy the whole `{…}` line.** Treat it like a password: don't paste it into a chat or an email.

### 2. Switch on the backup

```bash
hermes addon backup
```

(This opens the server and runs `sudo hermes-addon backup` there. Already on the server? Run `sudo hermes-addon backup` yourself.)

It asks, at hidden prompts (nothing shows as you type or paste, that's normal):

1. **A passphrase**, twice. **Write it down now** (a password manager, or paper somewhere safe).
2. **The `{…}` line** from step 1. It checks it with Google and creates the folder `agent-automation-backups` in your Drive.
3. **How many days to keep** (35 unless you type another number).

Then it switches on the nightly job and **makes the first backup straight away** (a minute or two), and tells you how it went.
After that you can clear the laptop terminal that showed the token (Mac: Cmd+K; Linux/WSL: `clear`).

> Don't create the `agent-automation-backups` folder by hand in Drive: with the narrow permission rclone can't see a folder it didn't
> make, and would make a second one with the same name.

## Checking it works

- **In your browser:** <https://drive.google.com> → My Drive → `agent-automation-backups`: one `hermes-backup-DATE.tar.gz.gpg` per night.
- **On the server** (`hermes ssh`):

  ```bash
  sudo hermes-addon-backup --status      # last result, next run, newest backups in Drive
  ```

  The last result looks like `2026-10-14T04:27:03+01:00 ok hermes-backup-2026-10-14-0427.tar.gz.gpg 61M | drive`.
- **Make one now:** `sudo hermes-backup` (add `BACKUP_QUIET=1` in front for no Telegram note if it fails).
- **If a night fails** you get a Telegram message saying why. Details: `journalctl -u hermes-backup -n 50`. Common causes:
  - *the Google sign-in needs renewing* (you removed rclone's access, or changed something in your Google account): do setup step 1
    again, then `hermes addon backup`, keep the passphrase, paste the new line.
  - *Drive looks full*: free some space, or run `hermes addon backup` again and keep fewer days.
  - *rate limit*: Google sometimes limits rclone's shared sign-in for everybody; it normally works the next night.

  When an upload fails, that night's (encrypted) backup stays on the server until the next good night, then is deleted.

## Restoring

Practise once, early on, so you know it works and you know your passphrase.

### On the same server (to undo a mess)

```bash
hermes ssh
sudo hermes-restore
```

1. It lists the backups in your Drive, newest first. Pick one by its number.
2. It downloads it and unlocks it (with the passphrase saved on the server, or it asks you for the one that backup was made with).
3. It shows what the backup holds and asks you to type **`RESTORE`**. Anything else stops without changing a thing.
4. It stops the agents and the memory server, puts the files and the memory back, and starts everything again (a minute or two).
   Anything newer than the backup is lost, but every file it replaced is kept in `/var/backups/hermes-restore-DATE`; delete that folder
   once you're happy (`sudo rm -rf /var/backups/hermes-restore-…`).
5. Check with `sudo hermes-doctor`.

### On a brand-new server (the old one is gone)

1. On your laptop: `./install.sh` builds a new server and fresh agents. Answer its questions as before. You can reuse your Telegram bots
   and keys; the restore puts the old settings back anyway.
2. On your laptop: `hermes backup-login` (a fresh Google sign-in for the new server).
3. `hermes ssh`, then `sudo bash /opt/agent-automation/vm/backup/hermes-restore`. It asks for the `{…}` line from step 2, then your passphrase,
   and continues as above.
4. Switch the nightly backups on again on the new server: `hermes addon backup`.
5. `sudo hermes-doctor`. If you made **new** Telegram bots for the new server, the restore put the old bot tokens back: set the new ones
   with `sudo hermes-key telegram-chief` (and `-tutor`, `-assistant`, `-coach`).

### Without the server, or just one file

You can open a backup on your laptop:

1. Download it from <https://drive.google.com> (folder `agent-automation-backups`).
2. Install gpg: Mac `brew install gnupg`; Linux/WSL `sudo apt install -y gnupg`; Windows: Gpg4win (<https://gpg4win.org>) or WSL.
3. Unlock and unpack it into an empty folder (it asks for the passphrase):

   ```bash
   mkdir restore && gpg -d hermes-backup-DATE.tar.gz.gpg | tar -xzf - -C restore
   ```

   The files are under `restore/data/…` (for example your notebooks in `restore/data/.hermes/owner/`). The databases are under
   `restore/sqlite/data/…` and the shared memory under `restore/postgres/` (those two need the server to be useful).

## Changing things

| To… | Do |
|---|---|
| change the passphrase, the Google account or the number of days | `hermes addon backup` again (it offers to keep what you don't change). A new passphrase applies to new backups; older ones still open with the old one, so keep both until the old ones have aged out. |
| switch the nightly backup off | `hermes addon backup off`. The backups in your Drive stay. |
| cut Google's link completely | switch it off, then on the server `sudo rm /etc/hermes-backup/rclone.conf`, and remove "rclone" at <https://myaccount.google.com/permissions>. |
| delete all backups | delete the folder `agent-automation-backups` in Drive (and empty Drive's bin). |

## For the curious: how it works

| Piece | What it is |
|---|---|
| `/usr/local/sbin/hermes-backup` | the nightly job (`vm/backup/hermes-backup` in this kit): SQLite databases copied safely with SQLite's own backup call, the memory databases dumped with `pg_dump`, everything packed with `tar`, encrypted with `gpg` (AES-256), checked by unpacking it again, uploaded with `rclone`, old ones deleted |
| `hermes-backup.timer` / `hermes-backup.service` | the schedule (04:20 plus up to 15 minutes; a night missed while the server was off runs when it starts) |
| `/etc/hermes-backup/` | root only: `passphrase`, `rclone.conf` (the Google sign-in), `keep-days` |
| `/var/backups/hermes-backup/last-status` | one line: when the last backup ran and how it went (no secrets) |
| `sudo hermes-addon backup` / `hermes-addon-backup` | set up, `--status`, `--off` |
| `sudo hermes-restore` | restore (`--list` only lists; `sudo hermes-restore FILE` uses an archive you copied to the server) |
