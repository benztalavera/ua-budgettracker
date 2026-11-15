"""Operator commands. No default account or password is ever installed."""

import json, os, shutil
from pathlib import Path
import click
from flask import current_app
from sqlalchemy import inspect, select
from .models import db, User, AuthState, utcnow
from .services import seed_defaults
from .auth import new_password


def upgrade_database():
    from alembic.config import Config
    from alembic import command

    root = Path(__file__).resolve().parent.parent
    db.session.remove()
    inspector = inspect(db.engine)
    if inspector.has_table("users") and not inspector.has_table("python_migrations"):
        raise click.ClickException(
            "This appears to be a legacy database. Use an EMPTY database for Python, then run import-php from a COPY of the legacy database."
        )
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(cfg, "head")
    current_app.config["_SCHEMA_READY"] = True


def register_commands(app):
    @app.cli.command("init-db")
    def init_db():
        """Create/upgrade the schema and seed categories/themes, never users."""
        upgrade_database()
        seed_defaults()
        click.echo("Database ready. Run create-admin to create your own administrator.")

    @app.cli.command("upgrade-db")
    def upgrade_db():
        """Apply bundled Alembic database revisions."""
        upgrade_database()
        seed_defaults()
        click.echo("Database is up to date.")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", default="Administrator", show_default=True)
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        envvar="UA_ADMIN_PASSWORD",
    )
    def create_admin(email, name, password):
        """Create an administrator using a user-supplied password."""
        import re

        email = email.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise click.ClickException("A valid email is required.")
        if db.session.scalar(select(User.id).where(User.email == email)):
            raise click.ClickException(
                "An account with this email already exists. Use reset-password if needed."
            )
        try:
            hashed = new_password(password)
        except ValueError as ex:
            raise click.ClickException(str(ex))
        user = User(
            name=name,
            email=email,
            password=hashed,
            role="admin",
            status="active",
            approved_at=utcnow(),
            onboarded_at=utcnow(),
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(AuthState(user_id=user.id))
        db.session.commit()
        click.echo(
            "Administrator created. Sign in and enrol 2FA in Profile & Security."
        )

    @app.cli.command("reset-password")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option(
        "--reset-2fa",
        is_flag=True,
        help="Explicitly clear 2FA after verifying account ownership offline.",
    )
    def reset_password(email, password, reset_2fa):
        from .auth import bump_auth

        user = db.session.scalar(select(User).where(User.email == email.lower()))
        if not user:
            raise click.ClickException("Account not found.")
        try:
            user.password = new_password(password)
        except ValueError as ex:
            raise click.ClickException(str(ex))
        if reset_2fa:
            user.two_fa_enabled = False
            user.two_fa_secret = None
        bump_auth(user)
        db.session.commit()
        click.echo("Password reset; previous sessions invalidated.")

    @app.cli.command("backup")
    def backup():
        from .maintenance import create_backup

        record = create_backup("cli")
        click.echo(str(Path(app.config["BACKUP_DIR"]) / record.filename))

    @app.cli.command("restore")
    @click.argument("file", type=click.Path(exists=True, dir_okay=False))
    @click.option(
        "--yes", is_flag=True, help="Confirm replacement of ALL current records."
    )
    def restore(file, yes):
        from .maintenance import create_backup, restore_payload, validate_payload

        if not yes:
            raise click.ClickException(
                "Use --yes after backing up your data AND uploads."
            )
        try:
            payload = json.loads(Path(file).read_text(encoding="utf-8-sig"))
            validate_payload(payload)
            create_backup("before-restore")
            restore_payload(payload)
        except (ValueError, KeyError) as ex:
            raise click.ClickException(str(ex))
        click.echo(
            "Data restored atomically. Copy the matching uploads directory separately. Sign in again."
        )

    @app.cli.command("import-php")
    @click.option(
        "--source-url",
        envvar="PHP_DATABASE_URL",
        required=True,
        help="MySQL URL for a COPY of the fully migrated PHP database.",
    )
    @click.option(
        "--uploads", type=click.Path(exists=True, file_okay=False), required=True
    )
    @click.option("--yes", is_flag=True)
    def import_php(source_url, uploads, yes):
        """Migrate data from a legacy MySQL database copy into the Python schema."""
        from .maintenance import php_export, create_backup, restore_payload

        if not yes:
            raise click.ClickException(
                "Use --yes after creating an isolated source COPY and empty Python target."
            )
        if db.session.scalar(select(User.id).limit(1)):
            raise click.ClickException(
                "Import requires a fresh target without user accounts. Do not run create-admin before importing existing accounts."
            )
        if str(db.engine.url.render_as_string(hide_password=False)) == source_url:
            raise click.ClickException("Source and target must be different databases.")
        payload = php_export(source_url)
        # Archive only on-server: never write password hashes/secrets into the release ZIP.
        root = Path(app.config["UPLOAD_DIR"]).resolve()
        source = Path(uploads).resolve()
        if source == root or source.is_relative_to(root) or root.is_relative_to(source):
            raise click.ClickException(
                "Source uploads and Python uploads must be separate, non-nested folders."
            )
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
        for path in source.rglob("*"):
            if (
                path.is_symlink()
                or not path.is_file()
                or path.suffix.lower() not in allowed
            ):
                continue
            rel = path.relative_to(source)
            dest = (root / rel).resolve()
            if not dest.is_relative_to(root):
                continue
            if path.suffix.lower() == ".svg":
                # Legacy SVGs must be trusted artwork. Deny active content even though
                # the upload endpoint additionally serves SVGs under a sandbox CSP.
                import re

                content = path.read_text(encoding="utf-8-sig")
                if re.search(
                    r"<\s*(script|foreignObject|iframe)|\bon\w+\s*=|(?:href|src)\s*=\s*[\"\']\s*(?:https?:|javascript:|//)",
                    content,
                    re.I,
                ):
                    continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        restore_payload(payload)
        seed_defaults()
        click.echo(
            "PHP data imported into Python. Password hashes upgrade at next successful login. Verify images, users, reports and 2FA before changing your domain. Source data was not modified."
        )

    @app.cli.command("seed-content")
    def sample_content():
        from .services import seed_content

        seed_content()
        click.echo(
            "Optional public sample content added. No accounts or passwords were created."
        )

    @app.cli.command("system-check")
    def system_check():
        import platform
        from .web import image_checks

        click.echo("Python " + platform.python_version())
        click.echo("Database: " + db.engine.dialect.name)
        for name, state in image_checks():
            click.echo(name + ": " + state)
        click.echo(
            "Backups directory writable: "
            + str(os.access(app.config["BACKUP_DIR"], os.W_OK))
        )
