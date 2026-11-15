"""SQLAlchemy schema. Money is Decimal, dates are real DATE values."""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Stamp:
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class User(Stamp, db.Model):
    __tablename__ = "users"
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(190), unique=True, nullable=False, index=True)
    student_number = db.Column(db.String(40), unique=True)
    grade_level = db.Column(db.String(40))
    course = db.Column(db.String(120))
    section = db.Column(db.String(60))
    contact_number = db.Column(db.String(40))
    avatar = db.Column(db.String(190))
    birth_date = db.Column(db.Date)
    gender = db.Column(db.String(20))
    address = db.Column(db.String(190))
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="student", nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)
    two_fa_enabled = db.Column(db.Boolean, default=False, nullable=False)
    two_fa_secret = db.Column(db.String(255))
    approved_by = db.Column(db.Integer)
    approved_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.String(190))
    onboarded_at = db.Column(db.DateTime)
    last_login = db.Column(db.DateTime)
    __table_args__ = (
        CheckConstraint("role IN ('student','admin')"),
        CheckConstraint("status IN ('pending','active','rejected','disabled')"),
    )


class AuthState(db.Model):
    __tablename__ = "python_auth_state"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    version = db.Column(db.Integer, default=1, nullable=False)
    last_otp_step = db.Column(db.BigInteger, default=-1, nullable=False)
    enroll_secret = db.Column(db.String(255))


class AuthAttempt(Stamp, db.Model):
    __tablename__ = "python_auth_attempts"
    bucket = db.Column(db.String(80), nullable=False, index=True)


class Setting(db.Model):
    __tablename__ = "settings"
    skey = db.Column(db.String(64), primary_key=True)
    svalue = db.Column(db.Text)


class Theme(db.Model):
    __tablename__ = "themes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    config_json = db.Column(db.Text, nullable=False)


class Category(Stamp, db.Model):
    __tablename__ = "categories"
    name = db.Column(db.String(80), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("type IN ('income','expense')"),)


class Income(Stamp, db.Model):
    __tablename__ = "incomes"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    source = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    income_date = db.Column(db.Date, nullable=False, index=True)
    notes = db.Column(db.Text)
    category = db.relationship(Category)
    user = db.relationship(User)
    __table_args__ = (CheckConstraint("amount > 0"),)


class Expense(Stamp, db.Model):
    __tablename__ = "expenses"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    expense_date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(190), nullable=False)
    payee = db.Column(db.String(120))
    notes = db.Column(db.Text)
    receipt_image = db.Column(db.String(190))
    category = db.relationship(Category)
    user = db.relationship(User)
    __table_args__ = (CheckConstraint("amount > 0"),)


class Budget(Stamp, db.Model):
    __tablename__ = "budgets"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    period_type = db.Column(db.String(10), default="monthly", nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    week_start = db.Column(db.String(8), default="today", nullable=False)
    alert_enabled = db.Column(db.Boolean, default=True, nullable=False)
    alert_threshold = db.Column(db.Numeric(5, 2), default=80, nullable=False)
    category = db.relationship(Category)
    __table_args__ = (
        CheckConstraint("amount > 0"),
        CheckConstraint("alert_threshold >= 1 AND alert_threshold <= 100"),
    )


class Event(Stamp, db.Model):
    __tablename__ = "events"
    title = db.Column(db.String(190), nullable=False)
    description = db.Column(db.Text)
    event_date = db.Column(db.Date, nullable=False)
    event_time = db.Column(db.String(8))
    cover_image = db.Column(db.String(190))
    latitude = db.Column(db.Numeric(10, 7))
    longitude = db.Column(db.Numeric(10, 7))
    animation = db.Column(db.String(30), default="fade-up")
    style = db.Column(db.String(30), default="rounded")
    status = db.Column(db.String(20), default="published", nullable=False)


class Gallery(Stamp, db.Model):
    __tablename__ = "galleries"
    title = db.Column(db.String(190), nullable=False)
    description = db.Column(db.Text)
    cover_image = db.Column(db.String(190))
    animation = db.Column(db.String(30), default="fade-up")
    style = db.Column(db.String(30), default="rounded")
    status = db.Column(db.String(20), default="published", nullable=False)


class GalleryImage(Stamp, db.Model):
    __tablename__ = "gallery_images"
    gallery_id = db.Column(db.Integer, db.ForeignKey("galleries.id"), nullable=False)
    image = db.Column(db.String(190), nullable=False)
    caption = db.Column(db.String(190))
    sort_order = db.Column(db.Integer, default=0, nullable=False)


class Video(Stamp, db.Model):
    __tablename__ = "videos"
    title = db.Column(db.String(190), nullable=False)
    platform = db.Column(db.String(20), default="youtube", nullable=False)
    video_url = db.Column(db.String(300), nullable=False)
    thumbnail = db.Column(db.String(190))
    animation = db.Column(db.String(30), default="fade-up")
    style = db.Column(db.String(30), default="rounded")
    status = db.Column(db.String(20), default="published", nullable=False)
    sort_order = db.Column(db.Integer, default=0)


class Advertisement(Stamp, db.Model):
    __tablename__ = "advertisements"
    title = db.Column(db.String(190), nullable=False)
    cover_image = db.Column(db.String(190))
    link_url = db.Column(db.String(300))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    description = db.Column(db.Text)
    animation = db.Column(db.String(30), default="fade-up")
    style = db.Column(db.String(30), default="rounded")
    status = db.Column(db.String(20), default="published", nullable=False)


class Backup(Stamp, db.Model):
    __tablename__ = "backups"
    filename = db.Column(db.String(190), nullable=False)
    size_bytes = db.Column(db.BigInteger, default=0, nullable=False)
    kind = db.Column(db.String(20), default="manual", nullable=False)


class AuditLog(Stamp, db.Model):
    __tablename__ = "audit_logs"
    user_id = db.Column(db.Integer)
    action = db.Column(db.String(60), nullable=False)
    details = db.Column(db.String(255))
    ip = db.Column(db.String(45))


class Migration(db.Model):
    __tablename__ = "python_migrations"
    version = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(190), nullable=False)
    applied_at = db.Column(db.DateTime, default=utcnow, nullable=False)


DATA_MODELS = [
    Setting,
    Theme,
    User,
    Category,
    Income,
    Expense,
    Budget,
    Event,
    Gallery,
    GalleryImage,
    Video,
    Advertisement,
    AuditLog,
]
