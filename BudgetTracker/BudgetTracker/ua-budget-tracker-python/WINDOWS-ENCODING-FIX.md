# Windows Unicode startup fix

The original package read UTF-8 JSON/SVG/print assets without specifying an encoding. Windows systems using the CP1252 default could raise `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d` during `init-db`. This was an application packaging bug, not database corruption.

## Permanent fix

The updated complete Python ZIP and the separate `UA-Python-Windows-Encoding-Fix.zip` explicitly use UTF-8 for these text files. The patch includes updated `tracker/services.py`, `tracker/__init__.py`, `tracker/web.py`, `tools/configure.py`, and `tools/check_print_layouts.py`.

For an existing installation, stop the server, extract the PATCH to a temporary folder, then copy its `tracker` and `tools` folders into your project folder (beside `wsgi.py`). Allow replacement of the listed files. Do not replace/delete `.env` or `instance`; neither is included in the patch. No database migration or reset is needed for the encoding fix itself.

## Use the supported Python environment

If a traceback includes `Python314`, the command is using Python 3.14, possibly the global interpreter rather than the project's virtual environment. This release supports Python 3.12/3.13, not 3.14. Install Python 3.13 (64-bit) alongside 3.14; uninstalling 3.14 is not required.

In PowerShell, from the project folder:

```powershell
cd C:\BudgetTracker\ua-budget-tracker-python
py -3.13 --version
py -3.13 -m venv .venv313
.\.venv313\Scripts\python.exe -m pip install -r requirements.txt
.\.venv313\Scripts\python.exe -m flask --app wsgi init-db
.\.venv313\Scripts\python.exe -m flask --app wsgi create-admin
.\.venv313\Scripts\waitress-serve.exe --listen=0.0.0.0:8000 wsgi:app
```

Run `create-admin` only if you have not already created your administrator. This creates a separate `.venv313` without deleting a prior `.venv` or touching stored data. The explicit executable paths avoid PowerShell activation-policy issues and prevent accidentally using global Python 3.14.

If `py -3.13 --version` says that no suitable runtime is installed, install Python 3.13 first, then reopen PowerShell and repeat the check. If you already have a working Python 3.13 virtual environment, you may use its executable instead of creating `.venv313`.

Keep the existing LAN setting `SESSION_COOKIE_SECURE=0` while using HTTP. Keep the same SECRET_KEY. No need to rerun configuration generation on an existing install.

## Temporary workaround only

Explicit UTF-8 mode can bypass the original encoding error for this PowerShell session:

```powershell
$env:PYTHONUTF8="1"
```

Then use the supported virtual environment's Python executable. This does not make Python 3.14 a tested/supported version and does not replace the permanent source patch.

## Verification

105 automated tests passed on Python 3.13.16, including a new isolated test that simulates CP1252 default text reads/writes while loading the defaults, landing/About pages, print assets and flowchart SVGs. This is a simulated Windows-locale regression check, not a claim of testing on an actual Windows machine.
