"""Portable, validated JSON backups and CLI PHP-MySQL data migration."""

import json, os, secrets, shutil
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from flask import current_app, g, has_request_context
from sqlalchemy import select, delete, update, inspect, create_engine, text as sqltext
from .models import *
from .services import setting, set_setting, seed_defaults
from .auth import decrypt, encrypt

FORMAT = "ua-budget-python/1"


def serialize(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def snapshot_data():
    result = {}
    for model in DATA_MODELS + [AuthState]:
        result[model.__tablename__] = [
            {c.name: serialize(getattr(r, c.name)) for c in model.__table__.columns}
            for r in db.session.scalars(select(model))
        ]
    return {"format": FORMAT, "created_at": utcnow().isoformat(), "tables": result}


def create_backup(kind="manual"):
    payload = snapshot_data()
    root = Path(current_app.config["BACKUP_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    name = f"backup_{utcnow():%Y%m%d_%H%M%S}_{secrets.token_hex(4)}.json"
    target = root / name
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(target)
    backup = Backup(filename=name, size_bytes=target.stat().st_size, kind=kind)
    db.session.add(backup)
    db.session.commit()
    return backup


def convert_column(column, value):
    if value is None:
        return None
    from sqlalchemy import Date, DateTime, Numeric, Boolean, Integer, BigInteger, String

    t = column.type
    if isinstance(t, DateTime):
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    if isinstance(t, Date):
        return date.fromisoformat(str(value)[:10])
    if isinstance(t, Numeric):
        n = Decimal(str(value))
        if not n.is_finite():
            raise ValueError("Non-finite numeric backup value.")
        return n
    if isinstance(t, Boolean):
        if value not in (True, False, 0, 1, "0", "1"):
            raise ValueError("Invalid boolean backup value.")
        return value in (True, 1, "1")
    if isinstance(t, (Integer, BigInteger)):
        return int(value)
    if isinstance(t, String):
        s = str(value)
        if t.length and len(s) > t.length:
            raise ValueError(f"{column.name} exceeds its storage limit.")
        return s
    return value


def validate_payload(payload):
    if (
        not isinstance(payload, dict)
        or payload.get("format") != FORMAT
        or not isinstance(payload.get("tables"), dict)
    ):
        raise ValueError(
            "Choose a Python-edition JSON backup. PHP SQL dumps are not Python backups."
        )
    tables = payload["tables"]
    allowed = {m.__tablename__: m for m in DATA_MODELS + [AuthState]}
    if not set(m.__tablename__ for m in DATA_MODELS).issubset(tables) or set(
        tables
    ) - set(allowed):
        raise ValueError("Backup tables are missing or unknown.")
    prepared = {}
    for name, records in tables.items():
        model = allowed[name]
        if not isinstance(records, list) or len(records) > 500000:
            raise ValueError("Invalid or oversized backup table.")
        cols = {c.name: c for c in model.__table__.columns}
        prepared[name] = []
        for record in records:
            if not isinstance(record, dict) or set(record) - set(cols):
                raise ValueError("Unknown backup fields.")
            row = {k: convert_column(cols[k], v) for k, v in record.items()}
            prepared[name].append(row)
    users = prepared["users"]
    if not any(r.get("role") == "admin" and r.get("status") == "active" for r in users):
        raise ValueError("Backup must contain an active administrator.")
    for user in users:
        if user.get("role") not in ("admin", "student") or user.get("status") not in (
            "pending",
            "active",
            "disabled",
            "rejected",
        ):
            raise ValueError("Invalid user role/status in backup.")
        if user.get("two_fa_enabled") and not decrypt(user.get("two_fa_secret")):
            raise ValueError(
                "Cannot decrypt backup 2FA secrets. Restore using the same SECRET_KEY, or use the CLI migration tool with explicit 2FA reset."
            )
    return prepared


def restore_payload(payload):
    prepared = validate_payload(payload)
    db.session.rollback()  # release request's read transaction before atomic replacement
    try:
        for model in reversed(DATA_MODELS + [AuthState]):
            db.session.execute(delete(model))
        for model in DATA_MODELS + [AuthState]:
            for row in prepared.get(model.__tablename__, []):
                db.session.add(model(**row))
            db.session.flush()
        # Invalidate all old signed sessions, even if restored auth versions match.
        if hasattr(g, "settings"):
            del g.settings
        set_setting("session_epoch", secrets.token_hex(16))
        set_setting("_last_auto_backup", utcnow().isoformat())
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    if hasattr(g, "settings"):
        del g.settings
    # PostgreSQL sequences are advanced after explicit primary-key inserts.
    reset_sequences()


def reset_sequences():
    if db.engine.dialect.name != "postgresql":
        return
    with db.engine.begin() as conn:
        for model in DATA_MODELS:
            if "id" in model.__table__.columns:
                name = model.__tablename__
                conn.execute(
                    sqltext(
                        f"SELECT setval(pg_get_serial_sequence('{name}','id'), COALESCE((SELECT MAX(id) FROM {name}),1), (SELECT COUNT(*)>0 FROM {name}))"
                    )
                )


def auto_backup_tick():
    if setting("auto_backup") != "1":
        return
    try:
        hours = max(1, min(744, int(setting("auto_backup_freq", "24"))))
    except ValueError:
        hours = 24
    key = "_last_auto_backup"
    row = db.session.get(Setting, key)
    if row is None:
        db.session.add(Setting(skey=key, svalue=utcnow().isoformat()))
        db.session.commit()
        return
    previous = row.svalue
    try:
        due = datetime.fromisoformat(previous) + timedelta(hours=hours) <= utcnow()
    except ValueError:
        due = True
    if not due:
        return
    claim = db.session.execute(
        update(Setting)
        .where(Setting.skey == key, Setting.svalue == previous)
        .values(svalue=utcnow().isoformat())
    )
    db.session.commit()
    if claim.rowcount != 1:
        return
    create_backup("auto")
    try:
        keep = max(2, min(100, int(setting("auto_backup_keep", "5"))))
    except ValueError:
        keep = 5
    older = list(
        db.session.scalars(
            select(Backup)
            .where(Backup.kind == "auto")
            .order_by(Backup.id.desc())
            .offset(keep)
        )
    )
    for record in older:
        root = Path(current_app.config["BACKUP_DIR"]).resolve()
        path = (root / record.filename).resolve()
        if path.is_relative_to(root):
            path.unlink(missing_ok=True)
        db.session.delete(record)
    db.session.commit()


def php_export(source_url):
    """Read only from a *copy* of the legacy database, never rewrite it."""
    engine = create_engine(source_url)
    result = {}
    try:
        with engine.connect() as conn:
            names = set(inspect(conn).get_table_names())
            for model in DATA_MODELS:
                name = model.__tablename__
                if name not in names:
                    raise ValueError(
                        f"Legacy database is missing {name}. Apply PHP migrations on a copy first."
                    )
                records = []
                for raw in conn.execute(sqltext(f"SELECT * FROM `{name}`")).mappings():
                    row = {
                        k: serialize(v)
                        for k, v in raw.items()
                        if k in model.__table__.columns
                    }
                    if name == "users" and row.get("two_fa_secret"):
                        row["two_fa_secret"] = encrypt(str(row["two_fa_secret"]))
                    if name == "events" and isinstance(
                        raw.get("event_time"), timedelta
                    ):
                        seconds = int(raw["event_time"].total_seconds())
                        row["event_time"] = (
                            f"{seconds // 3600:02}:{seconds // 60 % 60:02}:00"
                        )
                    records.append(row)
                result[name] = records
        # The PHP file set uses its own theme id; map it to the Python theme slug.
        vals = {r["skey"]: r["svalue"] for r in result["settings"]}
        theme_id = (
            vals.get("active_theme")
            or vals.get("theme_id")
            or vals.get("active_theme_id")
        )
        theme = next(
            (t for t in result["themes"] if str(t.get("id")) == str(theme_id)), None
        )
        if theme:
            result["settings"].append({"skey": "theme_slug", "svalue": theme["slug"]})
        return {"format": FORMAT, "created_at": utcnow().isoformat(), "tables": result}
    finally:
        engine.dispose()
