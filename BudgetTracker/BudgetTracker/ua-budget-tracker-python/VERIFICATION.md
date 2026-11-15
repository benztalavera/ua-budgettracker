# Python edition verification

## Verified locally

**Runtime:** Python 3.13.16, Flask 3.1.2, Flask-SQLAlchemy 3.1.1,
SQLAlchemy 2.0.44, Flask-WTF 1.2.2, Pillow 11.3.0, cryptography 46.0.1.

- Automated pytest workflow/security/calculation suite: **104 passed**.
- Public, admin, student, edit, guide, maintenance and print route rendering.
- Pending registration, administrator approval and first weekly budget setup.
- Student/admin URL boundaries and transaction/receipt ownership isolation.
- CSRF protection, throttling, password-change session invalidation, real OTP entry,
  TOTP reuse rejection, last-active-admin protection and private-file URL blocking.
- Decimal financial calculations, weekly anchoring and threshold state transitions.
- Image verification/re-encoding, theme activation and safe CSV formula handling.
- JSON backup round-trip, Unicode/peso preservation and unsupported-table rejection.
- **26 Chromium print/PDF scenarios** (17 representative + 9 long-text/bulk): all preview counts equalled actual PDF
  pages; all source table body rows appeared, with no measured cell/table overflow.
  How To: 16 pages; combined flowcharts: 2; monitor drill-down/behaviour: 2 each;
  other representative lists/reports: 1 page each. Bulk scenarios retained all 39–187 rows over 3–27 pages. Results are in `tests/print-results.json`.
- Desktop views at 1440px; mobile landing/dashboard/Page Studio at 390px without
  document horizontal overflow; no broken images in the desktop screenshots.
- A restored PHP MySQL/MariaDB source copied to fresh SQLite and MySQL/MariaDB
  Python targets; financial/content counts, existing passwords, encrypted TOTP and
  peso setting checked. Initial MySQL target schema and repeated upgrade passed.

The PDF tests used representative data and the bundled guide; they are not an
exhaustive test of arbitrary future long unbreakable content or every printer.
They apply to the Python edition, not the earlier PHP-only print audit.

## Not claimed as tested

- Live production hosting, Windows service installation or a built Docker image.
- PostgreSQL integration, live SMTP delivery, physical printers or external-service uptime.
- Every possible historical/customised PHP schema and every third-party video URL.
- High-load/multi-server operation or an independent penetration/security audit.

## Reproduce unit/workflow tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use temporary SQLite databases and fictional isolated accounts. No runtime
SQLite file, live credentials, backup data or local uploads are included in release
ZIPs. Follow DEPLOYMENT.md for the site-specific acceptance checklist.

## Optional browser/PDF audit

`tools/check_print_layouts.py` is the environment-configured audit runner used for
the representative 17 scenarios. It does not install accounts or create the bulk
fixture. Use a disposable, populated test copy; it signs in as an existing admin
and approved/onboarded student (with 2FA off for these automated fixture accounts).
Normal production users should keep 2FA enabled.

```bash
python -m pip install -r requirements-browser.txt
# Install Chrome/Chromium and its OS runtime libraries, then set:
export CHROME_BIN=/absolute/path/to/chrome
export BASE_URL=http://127.0.0.1:8000
export ADMIN_EMAIL=YOUR_TEST_ADMIN_EMAIL
export ADMIN_PASSWORD=YOUR_TEST_ADMIN_PASSWORD
export STUDENT_EMAIL=YOUR_TEST_STUDENT_EMAIL
export STUDENT_PASSWORD=YOUR_TEST_STUDENT_PASSWORD
export STUDENT_ID=THE_TEST_STUDENT_DATABASE_ID
python tools/check_print_layouts.py
```

Use PowerShell `$env:NAME='value'` assignments on Windows. Results/PDFs/screenshots
are written to `print-audit/` (or `OUTPUT_DIR`). These can contain user/financial
information; do not publish them or include them in a source release.
