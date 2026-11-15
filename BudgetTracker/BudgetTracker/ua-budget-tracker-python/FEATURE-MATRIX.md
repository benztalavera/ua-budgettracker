# Conversion scope & deliberate changes

This is a real, separate Python application, not PHP wrapped in Python. The UI was
rewritten and the data model adapted. The PHP source directory remains separate.

| Area | Python implementation |
|---|---|
| Public landing | Full-height hero; text/image/background layouts; no white wave; content sections |
| Hero controls | Images, overlay/transparency/gradient, entity colours, buttons, sizes, offsets, alignment, shadows, animation choices |
| Events | Date/time, venue coordinates, image, draft/published/hidden, style/animation, CRUD |
| Galleries | Albums and photos, captions/order editing, cover selection, publish controls |
| Videos | Video URLs/thumbnails; standard YouTube watch/short URL embeds; external-link fallback for other providers |
| Advertisements | Title/body/image/link and publication controls |
| Location | Leaflet/OSM map, company coordinates, geolocation, straight-line distance, directions/reset |
| About | Image upload, professional text, pillars/feature content, stats and logic diagram |
| Registration | Whole-page form, student number, grade/course/contact details, optional image |
| Approval | Pending accounts blocked; admin approval/rejection/reconsideration and history |
| Onboarding | First budget period/amount; today-based or selected-weekday weekly start |
| Authentication | Session protection, password hashing/legacy PHP bcrypt migration, throttling, logout |
| 2FA | Authenticator setup/manual secret, real OTP screen, encrypted secrets, single-use codes |
| Profile | Personal details/image, password and authenticator settings |
| Income | Private CRUD, category, amount, source/date/notes, CSV and print |
| Expenses | Private CRUD, category/amount/payee/date/notes, owner/admin-only receipt access |
| Budgets | Daily/weekly/monthly recurring or custom dates; overall/category scope; threshold alerts |
| Behaviour | Budget totals/status/pace/projection, daily/category spending, allowance comparisons and discipline score |
| Dashboards | Student financial summaries/charts and admin counts/recent activity |
| Monitoring | Student budget score/status and drill-down; date-range expense count/spend; CSV and print |
| Reports | Filterable transaction ledger and printable/exportable lists |
| Users | Role/status/password management, re-authentication, last-admin protection, session invalidation |
| Settings | School identity/images, currency, header/footer colours, map and automatic-backup controls |
| Themes | 14 seeded themes, activate/edit palette/name/local font stack; deleted built-ins reappear |
| Maintenance | Diagnostics, JSON backup/download/restore, opportunistic automatic backup and retention |
| Migration | Separate Python Alembic history, operator commands and authenticated admin status/update page |
| Guide | Searchable per-menu How To, glossary and Python-specific deployment/maintenance entries |
| Flowcharts | Student and administrator SVG workflows, zoom/reset/download and fixed-A4 printing |
| Print | Close button, professional portrait/landscape preview, measured pagination and PDF-friendly styles |

## Intentional changes / limits

- Python-capable hosting, not PHP-only InfinityFree. No browser-based Python install
  wizard; a trusted operator runs schema/admin commands.
- SQLite is the easy-start default. MySQL/MariaDB was exercised locally.
  PostgreSQL driver/configuration exists but needs site-specific integration testing.
- Backups are private JSON. Uploaded files and SECRET_KEY are backed up separately.
  Historical PHP SQL backup archives are retained separately, not imported as records.
- Automatic backups run on admin traffic; for guaranteed scheduled jobs, use an
  external scheduler calling the backup CLI.
- Map distance is straight-line, not driving distance/time. Directions open the
  external maps service. OSM tiles need network; geolocation needs permission/HTTPS.
- No geocoding autocomplete/API key is bundled; set campus coordinates in settings.
- YouTube embeds use a parsed allowlisted video ID. Facebook/TikTok and unsupported
  URLs remain safe external links; third-party embeds/tiles are not offline assets.
- SMTP approval notices are optional and environment-configured. No anonymous
  password-reset flow; a trusted operator uses the reset-password command.
- Animations/styles are reimplemented, not exact replicas of every CSS effect.
  Reduced-motion preferences are honoured. Hero offsets/scales are bounded.
- Destructive raw table reset tools are not exposed publicly; use a disposable
  database to start over. Account deletion disables access and preserves ledgers.
- No mobile app installer/EXE, automatic PHP/Python synchronisation, or production
  hosting account is bundled. Dependencies are installed from the requirements file.
- Local tests do not substitute for your school-data/privacy review, live SMTP,
  provider configuration, real printer tests or an independent security audit.
