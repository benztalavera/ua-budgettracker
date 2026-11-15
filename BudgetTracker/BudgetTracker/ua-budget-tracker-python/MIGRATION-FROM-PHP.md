# Moving an existing PHP installation to the Python edition

## Important boundaries

The Python schema is independent. **Do not run Python `init-db` or `upgrade-db`
against the live PHP database.** The application deliberately refuses to create
Python tables over a detected legacy PHP users table.

PHP SQL backups are not Python JSON backups. There is no PHP dependency at Python
runtime; the one-time importer reads a legacy MySQL database via PyMySQL.
The old site and source files are not changed by this importer.

## What imports

- Users, roles, approval state, profile details, avatars and student information.
- Password hashes: existing PHP bcrypt logins are accepted and upgraded to scrypt
  after a successful password sign-in. No cleartext password export is necessary.
- Existing TOTP secrets are encrypted with the Python SECRET_KEY. A user whose
  clock is correct can continue using their authenticator; re-enrolment is not
  normally necessary. Take special care to preserve the new secret afterwards.
- Categories, incomes, expenses, receipt paths, budgets and weekly-start settings.
- Published/draft/hidden events, galleries/images, videos and advertisements.
- Company/settings, About and landing JSON configuration, custom themes and audit logs.
- Built-in themes are repaired/seeded without overwriting imported theme edits.

Uploads need the matching source folder. Supported raster images are copied;
legacy SVGs receive screening and are served with restrictive CSP/sandbox headers.
The importer refuses unsafe asset paths/unsupported files rather than executing them.
Very old inconsistent schemas/data should be repaired and reviewed in a test copy
before cutover. Historical PHP SQL backup archives and PHP migration tracking
are **not** converted; retain them separately and privately for rollback.

## Recommended migration procedure

### A. Freeze and preserve the original

1. Put the live PHP site in maintenance mode or stop writes during final cutover.
2. Export its MySQL database through phpMyAdmin or your database tooling.
3. Download the complete matching `uploads/` directory.
4. Preserve PHP source/config and the original database/export in secure storage.
   Never publish that archive or include the live config in a public ZIP.
5. Restore the SQL export into a **separate temporary MySQL database**, not the
   live production database. Create a migration account with read-only `SELECT`
   access to that copy (plus permission to inspect its tables).

### B. Prepare a separate Python target

1. Follow the installation guide to create `.venv`, install requirements and
   generate a new, strong, stable Python SECRET_KEY.
2. Set `DATABASE_URL` to a **new empty target database** (or omit it for a new
   SQLite `DATA_DIR`). This is NOT the PHP source URL.
3. Initialise the Python schema:

```bash
python -m flask --app wsgi init-db
```

4. **Do not run `create-admin` or register users before importing.** The importer
   requires a target with no users and no financial records, preventing accidental
   data merging/replacement on a populated installation. The PHP admin is imported.

### C. Import the copy, including uploads

Linux / macOS (use your actual values; URL-encode the password):

```bash
export PHP_DATABASE_URL='mysql+pymysql://READ_USER:URL_ENCODED_PASSWORD@HOST:3306/PHP_COPY_DB?charset=utf8mb4'
python -m flask --app wsgi import-php --uploads /private/php-copy/uploads --yes
unset PHP_DATABASE_URL
```

Windows PowerShell:

```powershell
$env:PHP_DATABASE_URL='mysql+pymysql://READ_USER:URL_ENCODED_PASSWORD@HOST:3306/PHP_COPY_DB?charset=utf8mb4'
python -m flask --app wsgi import-php --uploads 'C:\private\php-copy\uploads' --yes
Remove-Item Env:PHP_DATABASE_URL
```

If there are genuinely no uploaded files, create an empty folder and supply that
path to the required `--uploads` option. Otherwise provide the full matching copy
so stored image/receipt paths have matching files. The importer validates the
payload and replaces the initially seeded settings/categories/themes. It does not
attempt arbitrary SQL execution or modify the source MySQL database.

The target is a fresh install; if a failed attempt copied some assets before data
validation failed, use a fresh target/data folder for the next rehearsal. Do not
repeatedly retry over a partially modified live deployment.

### D. Validate before changing the site URL

1. Run `python -m flask --app wsgi system-check`.
2. Compare row counts for each imported table against the PHP copy.
3. Sign in as the imported administrator; verify their existing password and OTP.
4. Test a student password/OTP, pending registration approval and first-budget flow.
5. Compare income, expenses, current budget windows, category spend and reports.
6. Check profile photos, logos, gallery images, About/hero images and private receipts.
7. Review Page Studio controls and re-save if a legacy visual setting needs adaptation.
8. Check header/footer colours, theme activation, map location and each public section.
9. Print representative reports and confirm totals/page counts.
10. Create a new Python JSON backup and archive uploads + new SECRET_KEY securely.
11. Only then point your domain/proxy to the Python site. Keep the PHP copy read-only
    until the school accepts the cutover and rollback window expires.

### E. Rollback

Stop the Python site, preserve its post-cutover data, and point traffic back to the
untouched PHP site/database if required. New Python writes are not automatically
mirrored back into PHP; reconcile them deliberately. There is no bidirectional sync
or Python-to-PHP reverse importer.

## Known differences to review

- Backend, templates, styling and admin editors are rewritten in Python; visual
  details/animation implementations need not be pixel-identical to the PHP version.
- New image uploads are verified raster images; SVG upload is not an unrestricted
  editor feature. Migrated trusted SVG assets are screened separately.
- Backups use typed JSON and separately managed uploads, rather than MySQL SQL dumps.
- Schema updates use Python/Alembic, not the PHP migration runner/version history.
- Deployment uses a Python server and operator CLI, not PHP's browser installer.
- Existing malformed encodings are preserved as stored; importing does not guess
  corrections for already-corrupted text. Export/import with `utf8mb4` throughout.
- Single-use OTP tracking is fresh after import; old PHP sessions do not carry over.
- Database identifiers are preserved so financial relationships remain linked.

## Verification scope

The migration was rehearsed locally from a restored MySQL/MariaDB source copy to
new SQLite and MySQL/MariaDB Python targets. Counts were checked for 2 users,
15 categories, 4 incomes, 17 expenses, 7 budgets, 2 events, 1 gallery, 4 gallery
images, 3 videos and 1 advertisement. Existing PHP password verification, encrypted
TOTP preservation and the peso currency setting passed. This is a representative
fixture, not a promise that every historical/customised schema will import without
review. Test your actual production export and matching uploads before cutover.
