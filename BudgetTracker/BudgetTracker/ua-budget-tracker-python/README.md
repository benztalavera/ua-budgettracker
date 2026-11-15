# UA Student Budget Tracker — Python Edition

A standalone Flask/SQLAlchemy rewrite of the University of the Assumption PHP
Budget Tracker. This edition does **not** invoke PHP, shell out to PHP scripts,
or require the PHP application at runtime. The PHP edition is kept separately.

## Start here

- **Python:** 3.12 or 3.13; verified on **Python 3.13.16**. Use 64-bit Python.
- **Stack:** Flask 3.1.2, SQLAlchemy 2.0.44, Flask-WTF, Jinja, Pillow and PyOTP.
- **Default database:** SQLite, for local use / small single-server installations.
- **Production database choices:** PostgreSQL or MySQL via `DATABASE_URL`.
- **Hosting:** a Python WSGI server or Docker. A PHP-only hosting account is not
  a Python runtime; do not deploy this ZIP using the InfinityFree PHP installer.
- Full instructions: **[DEPLOYMENT.md](DEPLOYMENT.md)**.
- Existing PHP data: **[MIGRATION-FROM-PHP.md](MIGRATION-FROM-PHP.md)**.
- Implemented modules and deliberate differences: **[FEATURE-MATRIX.md](FEATURE-MATRIX.md)**.
- Verification evidence / limitations: **[VERIFICATION.md](VERIFICATION.md)**.

## Local quick start

From this folder, using an activated virtual environment:

```bash
python -m pip install -r requirements.txt
python tools/configure.py --local
python -m flask --app wsgi init-db
python -m flask --app wsgi create-admin
python run.py
```

Open **http://127.0.0.1:8000** and sign in using the administrator email and
password you just supplied. No account or default password is shipped.
Optional: `python -m flask --app wsgi seed-content` adds public sample content
only; it does not create student accounts.

A student registers on `/register`; the administrator approves them in
**People → Registrations**. Their first sign-in offers budget setup. Weekly
budgets start today, or on a weekday chosen by the student.

## Main features

- Registration with student details/photo; pending, approved, rejected/disabled states.
- Authenticator 2FA with encrypted server-side secrets and single-use codes.
- Personal income, expenses, private receipt images, recurring/custom budgets and alerts.
- Shared budget behaviour/discipline analytics and admin student drill-downs.
- Filterable lists, safe CSV exports and measured A4 portrait/landscape print previews.
- All public-content admin menus, Page Studio, map distance/reset and About editor.
- Fourteen editable/activatable themes; logo, currency and school branding settings.
- Private JSON backup/download/restore, automatic backups without cron, Alembic updates,
  audit logs, How To guide, glossary and student/admin flowcharts.

## Private data

`instance/` (or `DATA_DIR`) holds the SQLite file, uploads, backups and the local
secret file. It is **not** a static directory. Receipt access checks ownership.
`.env`, databases, backups, test accounts, personal uploads, caches and virtual
environments are intentionally omitted from release ZIPs.

Back up **database + uploads + SECRET_KEY** together. Do not rotate a working
SECRET_KEY casually: it signs sessions and encrypts TOTP secrets. Production
requires your own strong environment secret and HTTPS-secure cookies.

## Operator commands

```text
python -m flask --app wsgi init-db
python -m flask --app wsgi upgrade-db
python -m flask --app wsgi create-admin
python -m flask --app wsgi reset-password --email EMAIL
python -m flask --app wsgi backup
python -m flask --app wsgi restore /private/path/backup.json --yes
python -m flask --app wsgi system-check
python -m flask --app wsgi seed-content
python -m flask --app wsgi import-php --uploads /copy/of/php/uploads --yes
```

The last command reads its source URL from `PHP_DATABASE_URL`. Use a **copy** of
the PHP database and a separate, fresh Python target. Read the migration guide
before running it; never point both editions at the same live schema.

## Development tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests create isolated temporary databases and do not require production passwords.
The browser/PDF verification was done separately; production hosting, SMTP delivery
and real printer output still require the deployment acceptance checklist.

## Structure

```text
tracker/          Flask factory, Python routes/models/services and Jinja templates
tracker/static/   Local CSS/JS, Leaflet and trusted artwork/diagrams
tracker/data/     UI defaults and legacy help reference data (not user records)
migrations/       Python/Alembic migration history, independent of PHP migrations
tests/            Automated workflow/security/calculation tests
instance/         Created locally; private, persistent runtime data (not shipped)
deploy/           Nginx and systemd production examples
Dockerfile        Non-root Python 3.13 container
compose.yaml      Persistent-volume single-server example
.env.example      Configuration names, without real secrets
```

The Page Studio interface is rewritten for Python rather than a pixel-for-pixel
copy. Core workflows and admin menus are carried over. Review the feature matrix
and run the acceptance checklist with your own data before replacing your site.
