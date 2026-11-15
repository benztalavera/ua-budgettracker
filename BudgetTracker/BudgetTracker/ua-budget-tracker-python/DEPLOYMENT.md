# Python deployment & operation guide

## 1. What you need

- A 64-bit Python **3.12 or 3.13** installation. The release was verified on
  Python **3.13.16**. Do not assume Python 3.14 compatibility for these pins.
- Internet for the first dependency installation (packages are not bundled).
- A private persistent data folder with enough space for uploads and backups.
- Local installation: SQLite is included with Python; no MySQL setup is needed.
- Production: a WSGI-capable host/container, HTTPS and a stable SECRET_KEY.

This is not a desktop EXE, and it does not run by uploading Python files into a
PHP-only `htdocs` folder. Keep the original PHP site if the host cannot run Python.
Deploy the two editions to separate folders, URLs and databases.

## 2. Windows local installation (PowerShell)

Extract `UA-Budget-Tracker-Python-Complete.zip`, open PowerShell inside
`ua-budget-tracker-python`, then run:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python tools/configure.py --local
python -m flask --app wsgi init-db
python -m flask --app wsgi create-admin
python -m flask --app wsgi system-check
python run.py
```

If Python 3.12 is installed instead, use `py -3.12`. If PowerShell blocks
activation, use `Set-ExecutionPolicy -Scope Process Bypass` for this window only,
or invoke `.\.venv\Scripts\python.exe` explicitly instead of activation.

The admin command prompts for name, email and password; the password is not echoed.
Open **http://127.0.0.1:8000**. `run.py` binds to all interfaces for local testing;
use your firewall to restrict access. It is not the production deployment command.

For a non-development Windows WSGI server, with the environment already active:

```powershell
waitress-serve --listen=127.0.0.1:8000 --call tracker:create_app
```

For an Internet-facing installation, put Waitress behind an HTTPS reverse proxy.
Do not rely on the Flask development server or expose a database port publicly.

## 3. Linux / macOS local installation

```bash
cd ua-budget-tracker-python
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python tools/configure.py --local
python -m flask --app wsgi init-db
python -m flask --app wsgi create-admin
python -m flask --app wsgi system-check
python run.py
```

Use `python3.12` if appropriate. Open http://127.0.0.1:8000. The default private
folder is `instance/`; SQLite, uploads and backups are created automatically.

`tools/configure.py` refuses to overwrite an existing `.env`; this prevents
accidental key rotation. Edit an existing file deliberately, keeping SECRET_KEY.

## 4. First-use checklist

1. Sign in with your newly created administrator account.
2. **System → Company Settings:** name, school identity, logo, favicon, currency,
   address, footer and backup schedule; save and reload to verify persistence.
3. **System → Themes:** activate a palette, and verify the public and workspace views.
4. **Landing Page → Page Studio:** edit hero, images, layout, sections, buttons,
   colours, backgrounds, positions, shadows and animations. Save each section.
5. Set coordinates/address in **Map & Location**. Location permission works on
   HTTPS or localhost and requires browser/user approval; map tiles need Internet.
6. Edit **About Page**, categories and optional public content (events/albums/videos/ads).
7. Register a test student on `/register`; approve in **People → Registrations**.
8. Sign in as that student, choose the first budget, then add income and expenses.
9. Check **Budget Behaviour**, admin **Student Monitoring** and print previews.
10. Enrol authenticator 2FA in **Account → Profile**; sign out and verify the OTP step.
11. Create/download a backup, and rehearse restore on a disposable test instance.
12. Read **System → How To** and **System → Flowcharts** for menu workflows.

Optional, public samples without accounts:

```bash
python -m flask --app wsgi seed-content
```

The Videos section shows an empty-content message until you publish a video. Published,
not draft, records appear publicly. No production/demo accounts are installed.

## 5. Configuration reference

The app reads environment variables and a project-root `.env` file. Real process
environment values take precedence. Never put `.env` in a public/static directory.

| Variable | Meaning |
|---|---|
| `APP_ENV` | `development` locally; `production` on a live site |
| `SECRET_KEY` | Your stable random secret, at least 32 characters; never share it |
| `SESSION_COOKIE_SECURE` | `0` for local HTTP; `1` for HTTPS production |
| `DATA_DIR` | Absolute private persistent folder, recommended for production |
| `DATABASE_URL` | Optional SQLAlchemy URL; otherwise `DATA_DIR/budget.sqlite3` |
| `TRUST_PROXY` | `1` only behind a trusted, single-hop reverse proxy |
| `MAX_UPLOAD_MB` | Whole-request upload limit in MB; default 8 (allowed 1–32) |
| `SMTP_HOST`, `SMTP_PORT` | Optional SMTP approval notices, typically port 587 |
| `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | SMTP authentication and sender |
| `SMTP_TLS` | `1` for STARTTLS (default); only `0` on a trusted internal relay |
| `PHP_DATABASE_URL` | Temporary PHP source database URL used only by importer |

The form's contact email is branding/contact information, not SMTP credentials.
SMTP approval notice is optional; no SMTP means admin approval still works.
Use your SMTP provider's approved sender. An email failure does not undo approval;
review server logs. SMTP delivery was not tested against a live provider.

### Database examples

```text
# SQLite default: omit DATABASE_URL, or use an absolute path:
DATABASE_URL=sqlite:////var/lib/ua-budget-tracker/budget.sqlite3

# PostgreSQL:
DATABASE_URL=postgresql+psycopg://USER:URL_ENCODED_PASSWORD@HOST:5432/DBNAME

# MySQL / MariaDB, new empty database, UTF-8:
DATABASE_URL=mysql+pymysql://USER:URL_ENCODED_PASSWORD@HOST:3306/DBNAME?charset=utf8mb4
```

URL-encode reserved password characters, including `@`, `:`, `/`, `#`, `%`.
Create the server database and a dedicated app user first. The Python app creates
its tables, not the database server or account. Do not reuse the live PHP schema.
SQLite and MySQL/MariaDB were exercised locally; PostgreSQL configuration is
provided but still requires your own integration test before production.

## 6. Linux production with Gunicorn, systemd and Nginx

The examples assume code at `/opt/ua-budget-tracker-python`, a dedicated account
`ua-budget`, and private data at `/var/lib/ua-budget-tracker`. Install Python,
its `venv` support, Nginx and your TLS tooling using your OS package manager.

1. Create the service account and private data directory:

```bash
sudo useradd --system --user-group --home-dir /var/lib/ua-budget-tracker ua-budget
sudo install -d -m 700 -o ua-budget -g ua-budget /var/lib/ua-budget-tracker
```

2. Copy the extracted code to `/opt/ua-budget-tracker-python`. Create its virtual
   environment and install requirements. The service account needs read/execute
   access to the code and virtual environment, not permission to rewrite source.

```bash
cd /opt/ua-budget-tracker-python
sudo python3.13 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements.txt
```

3. Create `/etc/ua-budget-tracker.env` (owner `root:ua-budget`, mode `640`) using
   `.env.example` as the reference. Set at least:

```text
APP_ENV=production
SECRET_KEY=REPLACE_WITH_YOUR_OWN_64_HEX_CHARACTERS
DATA_DIR=/var/lib/ua-budget-tracker
SESSION_COOKIE_SECURE=1
TRUST_PROXY=1
```

Generate a secret with `.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"`.
Set `DATABASE_URL` as appropriate; omitting it selects the private SQLite path.
The example secret above is NOT valid configuration. Keep your real key backed up.

4. Initialise as the service user with that environment, then create your admin:

```bash
sudo -u ua-budget bash -c 'set -a; source /etc/ua-budget-tracker.env; set +a; cd /opt/ua-budget-tracker-python; .venv/bin/python -m flask --app wsgi init-db; .venv/bin/python -m flask --app wsgi create-admin'
```

For shell-sourcing, quote values with spaces or special characters in the env file;
never execute an env file supplied by an untrusted person. You may instead export
these variables explicitly in a secure administrative shell.

5. Install the supplied unit:

```bash
sudo cp deploy/ua-budget.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ua-budget
sudo journalctl -u ua-budget -n 100 --no-pager
```

6. Adapt `deploy/nginx.conf` to your domain and install it in your Nginx site config.
   Run `sudo nginx -t`, enable the site, and reload Nginx. Obtain/configure a TLS
   certificate and redirect HTTP to HTTPS **before signing in**. The supplied file
   is an HTTP reverse-proxy starting point, not a bundled certificate.

7. Visit `https://YOUR_DOMAIN/healthz`; after database setup it returns `{"status":"ok"}`.
   Then run the acceptance checklist below. Bind Gunicorn only to loopback behind
   Nginx. Configure the firewall for HTTPS/HTTP as needed, not port 8000 or MySQL.

Do not add Nginx static aliases to private data. Private receipts must pass through
Flask's ownership checks. `TRUST_PROXY=1` assumes Nginx overwrites forwarded headers
as supplied; do not use it with an openly reachable backend or an untrusted proxy.
For multi-server deployments, use a shared server database, shared private uploads,
a common SECRET_KEY and appropriately coordinated storage/backups.

## 7. Docker / Compose

Install Docker with Compose. From the project directory:

```bash
python tools/configure.py --production
docker compose build
docker compose run --rm app python -m flask --app wsgi init-db
docker compose run --rm app python -m flask --app wsgi create-admin
docker compose up -d
docker compose logs --tail 100 app
```

The container runs as UID/GID 10001, with persistent `budget_data` mounted at `/data`.
Put an HTTPS proxy in front of host `127.0.0.1:8000`. The default Compose example is
single-server SQLite; choose a server database for greater concurrent usage.

If you only need a local HTTP Docker demo, set `SESSION_COOKIE_SECURE=0` in `.env`.
For access from a different machine you must deliberately change the port binding,
firewall and proxy; keep production cookies secure and use HTTPS.

**Never use `docker compose down -v` unless you intentionally want to delete the
persistent data volume.** Rebuilds do not migrate automatically: take a backup and
run `docker compose run --rm app python -m flask --app wsgi upgrade-db` before restart.
If replacing the volume with a host bind mount, grant UID 10001 access to that
private directory. The Docker files are deployment templates; the container image
itself was not built/tested in this workspace.

## 8. WSGI hosting panels / managed platforms

Your plan must explicitly support Python 3.12/3.13 WSGI or Docker, package
installation, environment secrets and persistent storage. `passenger_wsgi.py`
exports `application` for compatible panels. `wsgi.py` exports `app` for Gunicorn.
`Procfile` provides a port-aware start command for hosts that use it.

Configure secrets and a durable database/data directory using the provider's panel.
Run `init-db` (or `upgrade-db`) and `create-admin` through its console or one-off
job mechanism. **There is no public Python browser installer:** the setup screen
instructs an operator; it does not expose database credentials or create an admin.
Do not use SQLite/uploads on an ephemeral filesystem that is discarded on deploy.
Confirm the host supports your chosen database driver and upload limits.

## 9. Backups and restores

- Admin → System → Database contains create/download/restore operations.
- Administrative backup/restore requires the current administrator password.
- Backups are private portable **JSON**, not SQL dumps; PHP SQL backups cannot be
  uploaded to this restore form. Use the PHP migration guide for old data.
- JSON includes users, password hashes and encrypted TOTP secrets: store it privately.
- Uploads are separate. Copy `DATA_DIR/uploads/` and preserve the same SECRET_KEY.
- Automatic backup interval/retention is configured in Company Settings and runs
  on an authenticated administrator request; it is not a guaranteed wall-clock job
  while no administrator is visiting. Use external scheduling for strict SLAs.

CLI equivalents (in an activated environment):

```bash
python -m flask --app wsgi backup
python -m flask --app wsgi restore /private/path/backup.json --yes
```

Restore replaces supported data tables atomically, verifies the backup format and
active-admin presence, and invalidates sessions. Keep the original and take a backup
before any destructive operation. Rehearse on a copy first. Restore matching uploads
outside the public web root and keep the original secret so authenticator codes work.
A full filesystem snapshot should be taken with the app stopped or storage/db
snapshot tools; avoid copying a busy SQLite file independently of its WAL/SHM files.

## 10. Updates and account recovery

1. Put the site in maintenance mode at the proxy / stop the application.
2. Back up the JSON, uploads, database and private environment configuration.
3. Replace code while preserving `.env` and `DATA_DIR`; update requirements in the venv.
4. Run `python -m flask --app wsgi upgrade-db` using the service environment.
5. Run `system-check`, restart, and verify authentication, finance and printing.

Forgotten password or lost authenticator (trusted server operator only):

```bash
python -m flask --app wsgi reset-password --email person@example.edu
# Only after verifying the user's identity, to clear a lost authenticator:
python -m flask --app wsgi reset-password --email person@example.edu --reset-2fa
```

There is no anonymous email password-reset endpoint or recovery-code mechanism.
Password recovery is deliberately an authenticated server-operator procedure.

## 11. Troubleshooting

| Symptom | Check |
|---|---|
| Setup screen / 503 | Correct environment/database selected? Run `init-db`; check write access |
| Login does not stick on local HTTP | `SESSION_COOKIE_SECURE=0` locally; `1` only with HTTPS |
| CSRF / 400 | Reload form; keep cookies; verify stable SECRET_KEY and proxy scheme |
| Pending account cannot sign in | Approve registration as admin; disabled/rejected users remain blocked |
| OTP rejected | Sync phone/server clocks; use fresh code; each accepted code works once |
| OTP lost after moving servers | Restore the original SECRET_KEY, not a new generated one |
| Images missing | Restore uploads; ensure DATA_DIR and stored paths match; check Diagnostics |
| Upload 413 | Whole request exceeds app/proxy limit; reduce image size or adjust both limits |
| External map/video missing | Internet, browser permission or third-party availability; inspect console |
| Blank Videos section | Publish a video first; YouTube embeds support standard watch/short links |
| No scheduled backups | Automatic backups need admin traffic; confirm interval and retention |
| Migration refuses schema | You pointed Python at legacy PHP tables; use a new target database |
| Production startup refuses secret | Generate a genuine random >=32-character SECRET_KEY |
| SQLite locked | Use dedicated persistent storage, avoid long writes; consider a server DB |

## 12. Production acceptance checklist

- [ ] Correct domain, HTTPS, secure cookies, restricted backend/database ports.
- [ ] Strong unique admin password; authenticator 2FA enrolment and OTP tested.
- [ ] Register → pending → approve → first-budget setup tested with a real school account.
- [ ] Income/expense/budget math and category permissions checked on representative data.
- [ ] All public Page Studio entities saved/reloaded, including header/footer/logo/images.
- [ ] Map location permission, distance/reset and directions checked on your device.
- [ ] Student cannot open admin URLs or another student's receipts/records.
- [ ] Reports/monitoring filters and exports agree with expected totals.
- [ ] Print preview pages match PDF output; browser header/footer disabled.
- [ ] Backup + matching uploads + secret stored privately; restore rehearsed on a copy.
- [ ] SMTP, if used, tested with your actual sender and delivery logs.
- [ ] Host service restarts correctly and persistent data survives a code/container update.
- [ ] Monitoring/log rotation, storage capacity and school privacy/retention policy reviewed.
