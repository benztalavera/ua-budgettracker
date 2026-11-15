"""Application factory. Importing this module never starts a server or installs data."""

import logging, os, secrets
from datetime import timedelta
from pathlib import Path
from flask import Flask, g, render_template, request, session, redirect, url_for
from flask_wtf.csrf import CSRFProtect, CSRFError
from sqlalchemy import event, inspect, select
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from .models import db, User, AuthState

csrf = CSRFProtect()


def create_app(test_config=None):
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    data_dir = Path(os.getenv("DATA_DIR", str(root / "instance"))).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    env = os.getenv("APP_ENV", "development")
    secret = os.getenv("SECRET_KEY", "")
    if test_config:
        secret = test_config.get(
            "SECRET_KEY", secret or "test-secret-key-32-characters-long"
        )
    elif env == "production" and (len(secret) < 32 or secret.startswith("REPLACE_")):
        raise RuntimeError(
            "Production requires a random SECRET_KEY of at least 32 characters in the environment."
        )
    if not secret:
        path = data_dir / ".secret-key"
        if not path.exists():
            path.write_text(secrets.token_hex(32), encoding="utf-8")
            path.chmod(0o600)
        secret = path.read_text(encoding="utf-8").strip()
    app = Flask(__name__, instance_path=str(data_dir))
    app.config.from_mapping(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///budget.sqlite3"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        DATA_DIR=str(data_dir),
        UPLOAD_DIR=str(data_dir / "uploads"),
        BACKUP_DIR=str(data_dir / "backups"),
        MAX_CONTENT_LENGTH=max(1, min(32, int(os.getenv("MAX_UPLOAD_MB", "8"))))
        * 1024
        * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv(
            "SESSION_COOKIE_SECURE", "1" if env == "production" else "0"
        )
        == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        WTF_CSRF_TIME_LIMIT=3600,
        APP_ENV=env,
    )
    if test_config:
        app.config.update(test_config)
    for p in ("UPLOAD_DIR", "BACKUP_DIR"):
        Path(app.config[p]).mkdir(parents=True, exist_ok=True)
    if os.getenv("TRUST_PROXY", "0") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=0)
    db.init_app(app)
    csrf.init_app(app)
    with app.app_context():
        if db.engine.dialect.name == "sqlite":

            @event.listens_for(db.engine, "connect")
            def sqlite_options(conn, record):
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=10000")

    from .auth import auth
    from .web import web

    app.register_blueprint(auth)
    app.register_blueprint(web)
    from .commands import register_commands

    register_commands(app)
    from .web import video_embed
    from .services import setting, money, image_url, today, safe_url, color, theme_vars

    @app.before_request
    def load_user():
        g.user = None
        if request.endpoint == "static":
            return
        if not app.config.get("_SCHEMA_READY"):
            if inspect(db.engine).has_table("python_migrations"):
                app.config["_SCHEMA_READY"] = True
            else:
                return render_template("setup.html"), 503
        uid = session.get("uid")
        if uid:
            user = db.session.get(User, uid)
            state = db.session.get(AuthState, uid)
            if (
                user
                and state
                and user.status == "active"
                and state.version == session.get("auth_version")
                and session.get("epoch") == setting("session_epoch")
            ):
                g.user = user
                session.permanent = True
            else:
                session.clear()
        # Old .php bookmarks remain usable, but no PHP file is executed.
        if request.path.endswith(".php"):
            target = request.path[:-4]
            aliases = {
                "/index": "/",
                "/admin/index": "/admin",
                "/user/dashboard": "/user/dashboard",
                "/migration": "/admin/migrations",
            }
            target = aliases.get(target, target)
            paths = {r.rule for r in app.url_map.iter_rules()}
            if (
                target in paths
                or target
                in [
                    "/admin/" + e
                    for e in (
                        "events",
                        "galleries",
                        "videos",
                        "advertisements",
                        "categories",
                    )
                ]
                or target in ["/user/incomes", "/user/expenses"]
            ):
                return redirect(
                    target
                    + (
                        "?" + request.query_string.decode()
                        if request.query_string
                        else ""
                    ),
                    code=308,
                )
        if (
            g.user
            and g.user.role == "admin"
            and request.method == "GET"
            and not request.args.get("do")
            and request.path.startswith("/admin")
        ):
            from .maintenance import auto_backup_tick

            try:
                auto_backup_tick()
            except Exception:
                db.session.rollback()
                app.logger.exception("Automatic backup failed")

    # Explicit legacy aliases funnel through the before_request canonical redirect.
    aliases = [
        "index",
        "about",
        "login",
        "register",
        "gallery",
        "migration",
        "admin/index",
        "admin/about",
        "admin/advertisements",
        "admin/categories",
        "admin/database",
        "admin/events",
        "admin/flowchart",
        "admin/galleries",
        "admin/gallery_images",
        "admin/howto",
        "admin/landing",
        "admin/map",
        "admin/monitor",
        "admin/registrations",
        "admin/reports",
        "admin/settings",
        "admin/themes",
        "admin/users",
        "admin/videos",
        "user/dashboard",
        "user/behavior",
        "user/budgets",
        "user/expenses",
        "user/incomes",
        "user/onboarding",
        "user/profile",
        "user/reports",
    ]
    for i, path in enumerate(aliases):
        app.add_url_rule(
            "/" + path + ".php",
            endpoint="legacy" + str(i),
            view_func=lambda: ("Not found", 404),
            methods=["GET", "POST"],
        )

    def query_url(**updates):
        from urllib.parse import urlencode

        params = dict(request.args)
        for k, v in updates.items():
            if v is None:
                params.pop(k, None)
            else:
                params[k] = v
        return request.path + ("?" + urlencode(params) if params else "")

    def asset_text(name):
        if name not in ("css/print.css", "js/print.js"):
            return ""
        return (Path(app.static_folder) / name).read_text(encoding="utf-8")

    @app.context_processor
    def shared():
        from .services import print_columns

        return dict(
            print_columns=print_columns,
            user=getattr(g, "user", None),
            setting=setting,
            money=money,
            image_url=image_url,
            today=today,
            safe_url=safe_url,
            color=color,
            theme_vars=theme_vars,
            query_url=query_url,
            asset_text=asset_text,
            video_embed=video_embed,
            csrf_token=__import__(
                "flask_wtf.csrf", fromlist=["generate_csrf"]
            ).generate_csrf,
            nav=web_menu(getattr(g, "user", None)),
        )

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.tile.openstreetmap.org; connect-src 'self' https://nominatim.openstreetmap.org; frame-src https://www.youtube-nocookie.com https://www.youtube.com https://www.facebook.com https://www.tiktok.com; base-uri 'self'; form-action 'self'; object-src 'none'"
        )
        if request.path.startswith("/uploads/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
            )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(ValueError)
    def validation_error(ex):
        db.session.rollback()
        return render_template("error.html", code=400, message=str(ex)), 400

    @app.errorhandler(CSRFError)
    def csrf_error(ex):
        return render_template(
            "error.html",
            code=400,
            message="Your form session expired or the security token is missing. Reload the form and try again.",
        ), 400

    for code in (400, 403, 404, 413, 429, 500):

        def handler(ex, _code=code):
            db.session.rollback()
            messages = {
                400: "The request could not be processed.",
                403: "You do not have permission to view this page.",
                404: "This page was not found.",
                413: "The upload exceeds the configured size limit.",
                429: "Too many attempts. Please wait 15 minutes.",
                500: "An unexpected error occurred. Check the private server log.",
            }
            return render_template(
                "error.html", code=_code, message=messages[_code]
            ), _code

        app.register_error_handler(code, handler)
    return app


def web_menu(user):
    if not user:
        return []
    if user.role == "admin":
        return [
            ("Overview", [("Dashboard", "/admin")]),
            (
                "Landing Page",
                [
                    ("Page Studio", "/admin/landing"),
                    ("Events", "/admin/events"),
                    ("Galleries", "/admin/galleries"),
                    ("Videos", "/admin/videos"),
                    ("Advertisements", "/admin/advertisements"),
                    ("Map & Location", "/admin/map"),
                    ("About Page", "/admin/about"),
                ],
            ),
            (
                "Finance",
                [
                    ("Categories", "/admin/categories"),
                    ("Financial Report", "/admin/reports"),
                ],
            ),
            (
                "People",
                [
                    ("User Accounts", "/admin/users"),
                    ("Registrations", "/admin/registrations"),
                    ("Student Monitor", "/admin/monitor"),
                ],
            ),
            (
                "System",
                [
                    ("Company Settings", "/admin/settings"),
                    ("Theme Studio", "/admin/themes"),
                    ("Database", "/admin/database"),
                    ("Migrations", "/admin/migrations"),
                    ("How To", "/admin/howto"),
                    ("Flowchart", "/admin/flowchart"),
                ],
            ),
            ("Account", [("Profile & Security", "/user/profile")]),
        ]
    return [
        ("Overview", [("Dashboard", "/user/dashboard")]),
        (
            "My Finances",
            [
                ("Income", "/user/incomes"),
                ("Expenses", "/user/expenses"),
                ("Budgets", "/user/budgets"),
            ],
        ),
        (
            "Analysis",
            [
                ("My Budget Behaviour", "/user/behavior"),
                ("My Reports", "/user/reports"),
            ],
        ),
        ("Account", [("Profile & Security", "/user/profile")]),
    ]
