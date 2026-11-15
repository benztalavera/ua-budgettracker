"""Shared finance, settings, uploads and analytics services."""

import calendar, copy, csv, io, json, re, secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
from flask import current_app, g, request, url_for, has_request_context
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from .models import *

DEFAULTS = json.loads(
    (Path(__file__).parent / "data/original_defaults.json").read_text(encoding="utf-8")
)
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
PERIODS = ["daily", "weekly", "monthly", "custom"]
LEVELS = [
    "Grade 7",
    "Grade 8",
    "Grade 9",
    "Grade 10",
    "Grade 11",
    "Grade 12",
    "1st Year College",
    "2nd Year College",
    "3rd Year College",
    "4th Year College",
    "5th Year College",
    "Graduate Studies",
]
SETTINGS = {
    "site_name": "UA Student Budget Tracker",
    "company_name": "University of the Assumption",
    "site_tagline": "Plan your allowance. Track your spending. Build better habits.",
    "company_address": "San Fernando, Pampanga, Philippines",
    "company_email": "",
    "company_phone": "",
    "company_website": "https://www.ua.edu.ph",
    "footer_text": "University of the Assumption · Student Budget Tracker",
    "currency_symbol": "₱",
    "currency_code": "PHP",
    "currency_position": "before",
    "timezone": "Asia/Manila",
    "hero_title": "A smarter budget. A brighter student life.",
    "hero_subtitle": "A simple space to plan your allowance, track everyday spending and grow confident money habits.",
    "hero_cta": "Sign in",
    "hero_cta_link": "/login",
    "logo": "assets-img:ua-logo.png",
    "favicon": "assets-img:ua-logo.png",
    "header_bg": "",
    "header_fg": "",
    "footer_bg": "",
    "footer_fg": "",
    "latitude": "15.0288",
    "longitude": "120.6994",
    "force_2fa_admin": "0",
    "auto_backup": "1",
    "auto_backup_freq": "24",
    "auto_backup_keep": "5",
    "theme_slug": "ua-navy-gold",
}


def settings():
    if not hasattr(g, "settings"):
        g.settings = {r.skey: r.svalue for r in db.session.scalars(select(Setting))}
    return g.settings


def setting(key, default=None):
    v = settings().get(key)
    return (
        v
        if v is not None and v != ""
        else SETTINGS.get(key, default if default is not None else "")
    )


def set_setting(key, value):
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(skey=key)
        db.session.add(row)
    row.svalue = str(value)
    if hasattr(g, "settings"):
        g.settings[key] = str(value)


def config(section):
    value = copy.deepcopy(DEFAULTS[section])
    try:
        stored = json.loads(
            setting("landing_cfg" if section == "landing" else "about_cfg", "{}")
        )
    except (ValueError, TypeError):
        stored = {}
    if isinstance(stored, dict):
        for k, v in stored.items():
            if isinstance(v, dict) and isinstance(value.get(k), dict):
                value[k].update(v)
            else:
                value[k] = v
    return value


def today():
    try:
        return datetime.now(ZoneInfo(setting("timezone"))).date()
    except (ValueError, KeyError):
        return datetime.now(ZoneInfo("Asia/Manila")).date()


def amount(value):
    try:
        n = Decimal(str(value).replace(",", "")).quantize(Decimal(".01"))
        if not n.is_finite() or n <= 0 or n > Decimal("999999999999.99"):
            raise ValueError()
        return n
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter a positive amount up to 999,999,999,999.99.")


def parse_date(value, required=True):
    if not value and not required:
        return None
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise ValueError("Use a valid date (YYYY-MM-DD).")


def text(name, limit=190, required=False, form=None):
    v = str((form if form is not None else request.form).get(name, "")).strip()
    if required and not v:
        raise ValueError(name.replace("_", " ").title() + " is required.")
    if len(v) > limit:
        raise ValueError(
            name.replace("_", " ").title() + f" must be {limit} characters or fewer."
        )
    return v


def safe_url(value, fallback="#"):
    value = str(value or "").strip()
    if any(ord(c) < 32 for c in value) or "\\" in value:
        return fallback
    p = urlsplit(value)
    if p.scheme and p.scheme not in ("https", "http"):
        return fallback
    if value.startswith("//"):
        return fallback
    if p.scheme:
        return value
    if value.startswith("#"):
        return value
    if value.endswith(".php") or ".php?" in value:
        value = value.replace(".php", "")
        value = "/" + value.lstrip("/")
        if value == "/index":
            value = "/"
    return value if value.startswith("/") else "/" + value


def color(value, default=""):
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", str(value or "")) else default


def money(value):
    n = Decimal(str(value or 0))
    s = setting("currency_symbol")
    formatted = f"{abs(n):,.2f}"
    out = (
        f"{formatted} {s}"
        if setting("currency_position") == "after"
        else f"{s}{formatted}"
    )
    return ("-" if n < 0 else "") + out


def image_url(value):
    if not value:
        return ""
    if value.startswith("assets-img:"):
        return url_for("static", filename="img/" + value.split(":", 1)[1])
    return url_for("web.upload", filename=value)


def save_image(file, folder):
    if not file or not file.filename:
        return None
    allowed = {
        "logo",
        "avatars",
        "events",
        "galleries",
        "ads",
        "videos",
        "receipts",
        "landing",
        "about",
    }
    if folder not in allowed:
        raise ValueError("Unknown upload folder.")
    try:
        Image.MAX_IMAGE_PIXELS = 25000000
        img = Image.open(file.stream)
        if img.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
            raise ValueError("Use a JPEG, PNG, WebP or GIF image.")
        img.verify()
        file.stream.seek(0)
        img = Image.open(file.stream)
        img.load()
        if img.width * img.height > 25000000:
            raise ValueError("Image is too large (maximum 25 megapixels).")
        # Decode and re-encode: do not retain script/polyglot payloads or EXIF data.
        img.thumbnail((2400, 2400))
        ext = "png" if img.mode in ("RGBA", "P") else "jpg"
        img = img.convert("RGBA" if ext == "png" else "RGB")
        rel = f"{folder}/{secrets.token_hex(16)}.{ext}"
        target = Path(current_app.config["UPLOAD_DIR"]) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        img.save(
            target,
            "PNG" if ext == "png" else "JPEG",
            **({} if ext == "png" else {"quality": 88}),
        )
        return rel
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("The selected file is not a valid, safe image.")


def audit(action, details="", uid=None):
    db.session.add(
        AuditLog(
            user_id=uid
            if uid is not None
            else getattr(getattr(g, "user", None), "id", None),
            action=action[:60],
            details=details[:255],
            ip=(request.remote_addr or "")[:45] if has_request_context() else "",
        )
    )


def period_window(kind, ref=None, week_start="today", anchor=None):
    ref = ref or today()
    if kind == "daily":
        return ref, ref
    if kind == "monthly":
        return ref.replace(day=1), ref.replace(
            day=calendar.monthrange(ref.year, ref.month)[1]
        )
    if kind == "weekly":
        if week_start == "today":
            anchor = anchor if anchor and anchor <= ref else ref
            start = anchor + timedelta(days=((ref - anchor).days // 7) * 7)
        else:
            start = ref - timedelta(
                days=(ref.weekday() - WEEKDAYS.get(week_start, 0)) % 7
            )
        return start, start + timedelta(days=6)
    raise ValueError("Select daily, weekly, monthly or custom.")


def evaluate(b, ref=None):
    ref = ref or today()
    start, end = (
        (b.period_start, b.period_end)
        if b.period_type == "custom"
        else period_window(b.period_type, ref, b.week_start, b.period_start)
    )
    stmt = select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.user_id == b.user_id, Expense.expense_date.between(start, end)
    )
    if b.category_id:
        stmt = stmt.where(Expense.category_id == b.category_id)
    spent = db.session.scalar(stmt) or Decimal(0)
    limit = b.amount or Decimal(0)
    pct = float(spent / limit * 100) if limit else 0
    state = (
        "over"
        if pct >= 100
        else "warn"
        if b.alert_enabled and pct >= float(b.alert_threshold)
        else "ok"
    )
    total = max(1, (end - start).days + 1)
    elapsed = min(total, max(0, (ref - start).days + 1))
    expected = 100 * elapsed / total
    diff = pct - expected
    return dict(
        id=b.id,
        model=b,
        category=b.category.name if b.category else "All categories",
        period_type=b.period_type,
        start=start,
        end=end,
        active=start <= ref <= end,
        amount=limit,
        spent=spent,
        remaining=limit - spent,
        pct=pct,
        state=state,
        expected_pct=expected,
        pace="under" if diff <= 5 else "on" if diff <= 15 else "over",
        projected=spent / max(1, elapsed) * total,
        days_left=max(0, total - elapsed),
        total_days=total,
    )


def snapshot(uid, ref=None):
    ref = ref or today()
    budgets = [
        evaluate(b, ref)
        for b in db.session.scalars(select(Budget).where(Budget.user_id == uid))
    ]
    budgets.sort(key=lambda b: ({"over": 0, "warn": 1, "ok": 2}[b["state"]], -b["pct"]))
    inc = db.session.scalar(
        select(func.coalesce(func.sum(Income.amount), 0)).where(Income.user_id == uid)
    ) or Decimal(0)
    exp = db.session.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.user_id == uid)
    ) or Decimal(0)
    daily = {ref - timedelta(days=i): Decimal(0) for i in reversed(range(30))}
    for d, total in db.session.execute(
        select(Expense.expense_date, func.sum(Expense.amount))
        .where(
            Expense.user_id == uid,
            Expense.expense_date.between(ref - timedelta(days=29), ref),
        )
        .group_by(Expense.expense_date)
    ):
        daily[d] = total
    allowance = Decimal(0)
    bytype = {}
    for b in budgets:
        if not b["active"] or b["period_type"] == "custom":
            continue
        group = bytype.setdefault(
            b["period_type"], {"overall": None, "cats": Decimal(0)}
        )
        if b["model"].category_id is None:
            group["overall"] = b["amount"]
        else:
            group["cats"] += b["amount"]
    daysmonth = calendar.monthrange(ref.year, ref.month)[1]
    for kind, v in bytype.items():
        allowance += (v["overall"] if v["overall"] is not None else v["cats"]) / (
            {"daily": 1, "weekly": 7, "monthly": daysmonth}[kind]
        )
    values14 = list(daily.values())[-14:]
    over = sum(b["state"] == "over" for b in budgets)
    warn = sum(b["state"] == "warn" for b in budgets)
    paceover = sum(
        b["state"] == "ok" and b["active"] and b["pace"] == "over" for b in budgets
    )
    daysover = sum(v > allowance for v in values14) if allowance else 0
    score = (
        max(
            0,
            100
            - min(54, 18 * over)
            - min(32, 8 * warn)
            - min(18, 6 * paceover)
            - min(15, 3 * daysover),
        )
        if budgets
        else 0
    )
    month_start, month_end = period_window("monthly", ref)
    month_spend = db.session.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.user_id == uid, Expense.expense_date.between(month_start, month_end)
        )
    ) or Decimal(0)
    cats = db.session.execute(
        select(Category.name, func.sum(Expense.amount), func.count(Expense.id))
        .outerjoin(Category, Category.id == Expense.category_id)
        .where(
            Expense.user_id == uid, Expense.expense_date.between(month_start, month_end)
        )
        .group_by(Category.name)
    ).all()
    return dict(
        user=db.session.get(User, uid),
        budgets=budgets,
        income=inc,
        expenses=exp,
        balance=inc - exp,
        allowance=allowance,
        planned=sum((b["amount"] for b in budgets), Decimal(0)),
        spent=sum((b["spent"] for b in budgets), Decimal(0)),
        over=over,
        warn=warn,
        score=score,
        score_label="Excellent"
        if score >= 85
        else "Good"
        if score >= 70
        else "Needs attention"
        if score >= 50
        else "At risk"
        if score
        else "Not monitored",
        daily=list(daily.items()),
        no_spend_days=sum(v == 0 for v in daily.values()),
        month_spend=month_spend,
        month_projection=month_spend / ref.day * daysmonth,
        categories=cats,
        days_over=daysover,
    )


def category_for(value, kind, uid):
    if not value:
        return None
    try:
        c = db.session.get(Category, int(value))
    except (ValueError, TypeError):
        raise ValueError("Select a valid category.")
    if not c or c.type != kind or c.user_id not in (None, uid):
        raise ValueError("Select a valid category for this transaction.")
    return c.id


def csv_bytes(headers, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    for row in rows:
        # Prevent spreadsheet formula injection in user-controlled cells.
        writer.writerow(
            [
                "'" + v
                if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@"))
                else v
                for v in row
            ]
        )
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def seed_defaults():
    for k, v in SETTINGS.items():
        if db.session.get(Setting, k) is None:
            db.session.add(Setting(skey=k, svalue=v))
    if db.session.get(Setting, "session_epoch") is None:
        set_setting("session_epoch", secrets.token_hex(16))
    if not db.session.scalar(select(Category.id).limit(1)):
        for kind, names in [
            (
                "income",
                [
                    "Allowance",
                    "Part-time Job",
                    "Scholarship",
                    "Gift",
                    "Freelance / Others",
                ],
            ),
            (
                "expense",
                [
                    "Food & Drinks",
                    "Transportation",
                    "School Supplies",
                    "Internet & Mobile",
                    "Dorm / Rent",
                    "Clothing",
                    "Health",
                    "Entertainment",
                    "Utilities",
                    "Others",
                ],
            ),
        ]:
            for name in names:
                db.session.add(Category(name=name, type=kind))
    palettes = list(DEFAULTS["themes"])
    extra = [
        ("Royal Academic", "royal-academic", "#312e81", "#d4a017"),
        ("Ocean Breeze", "ocean-breeze", "#0891b2", "#06b6d4"),
        ("Sunset Gradient", "sunset-gradient", "#ea580c", "#ec4899"),
        ("Midnight Pro", "midnight-pro", "#38bdf8", "#a78bfa"),
        ("Forest Fresh", "forest-fresh", "#15803d", "#65a30d"),
        ("Candy Pop", "candy-pop", "#db2777", "#8b5cf6"),
        ("Minimal Mono", "minimal-mono", "#171717", "#525252"),
        ("Aurora Lights", "aurora-lights", "#7c3aed", "#14b8a6"),
        ("Terracotta", "terracotta", "#c2410c", "#0d9488"),
        ("Cyber Lime", "cyber-lime", "#a3e635", "#22d3ee"),
    ]
    base = palettes[0][2]
    for name, slug, primary, accent in extra:
        cfg = dict(
            base,
            primary=primary,
            primary_dark=primary,
            accent=accent,
            gradient=f"linear-gradient(135deg,{primary},{accent})",
        )
        if slug in ("midnight-pro", "cyber-lime"):
            cfg.update(
                bg="#0f172a",
                surface="#1e293b",
                surface_2="#273449",
                text="#e2e8f0",
                muted="#94a3b8",
                border="#334155",
            )
        palettes.append([name, slug, cfg])
    for name, slug, cfg in palettes:
        if not db.session.scalar(select(Theme.id).where(Theme.slug == slug)):
            db.session.add(Theme(name=name, slug=slug, config_json=json.dumps(cfg)))
    db.session.commit()


def theme_vars():
    theme = db.session.scalar(select(Theme).where(Theme.slug == setting("theme_slug")))
    try:
        cfg = json.loads(theme.config_json) if theme else DEFAULTS["themes"][0][2]
    except ValueError:
        cfg = DEFAULTS["themes"][0][2]
    valid = {k: color(v) for k, v in cfg.items() if color(v)}
    valid["font"] = {
        "sans": "system-ui, sans-serif",
        "serif": "Georgia, serif",
        "mono": "ui-monospace, monospace",
    }.get(cfg.get("font_choice", "sans"), "system-ui, sans-serif")
    return valid


def notify_approval(user):
    """Optional SMTP. Never require host mail() or sendmail. Returns delivery status."""
    import os, smtplib, ssl
    from email.message import EmailMessage

    host = os.getenv("SMTP_HOST")
    if not host:
        return False
    message = EmailMessage()
    message["Subject"] = "Your student budget tracker account is approved"
    message["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USERNAME", "")
    message["To"] = user.email
    message.set_content(
        f"Hello {user.name},\n\nYour registration to {setting('site_name')} is approved. Open the school budget tracker and sign in with the email and password you registered with.\n\nDo not share your password or authentication codes."
    )
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
            if os.getenv("SMTP_TLS", "1") == "1":
                smtp.starttls(context=ssl.create_default_context())
            if os.getenv("SMTP_USERNAME"):
                smtp.login(os.environ["SMTP_USERNAME"], os.getenv("SMTP_PASSWORD", ""))
            smtp.send_message(message)
        return True
    except Exception:
        current_app.logger.exception("Approval email delivery failed")
        return False


def seed_content():
    """Optional public sample content; never creates users or passwords."""
    if not db.session.scalar(select(Event.id).limit(1)):
        db.session.add(
            Event(
                title="Student Budgeting Workshop",
                description="Practical strategies for planning your allowance, saving for goals and making confident everyday choices.",
                event_date=today() + timedelta(days=14),
                event_time="14:00",
                cover_image="assets-img:about-default.jpg",
                status="published",
                animation="fade-up",
                style="rounded",
            )
        )
    if not db.session.scalar(select(Gallery.id).limit(1)):
        album = Gallery(
            title="Student life & learning",
            description="Planning for a confident semester.",
            cover_image="assets-img:about-default.jpg",
            status="published",
            animation="fade-up",
            style="rounded",
        )
        db.session.add(album)
        db.session.flush()
        db.session.add(
            GalleryImage(
                gallery_id=album.id,
                image="assets-img:about-default.jpg",
                caption="Plan, record, review and improve.",
                sort_order=1,
            )
        )
    if not db.session.scalar(select(Advertisement.id).limit(1)):
        db.session.add(
            Advertisement(
                title="Start the semester with a plan",
                description="Register for a student account. Your administrator reviews the details before enabling access.",
                link_url="/register",
                status="published",
                animation="fade-up",
                style="rounded",
            )
        )
    db.session.commit()


def print_columns(headers):
    """Allocate real paper width to prose/identity columns, not equal-width grids."""
    weights = []
    for label in headers:
        name = label.lower().strip()
        if name == "#":
            weight = 0.45
        elif name in ("student", "name"):
            weight = 3.5
        elif "email" in name:
            weight = 3.0
        elif name in ("description", "source", "title"):
            weight = 4.0
        elif name in ("category", "payee"):
            weight = 2.0
        elif "date" in name or name in ("created", "last login"):
            weight = 1.6
        elif name in ("status", "role", "type"):
            weight = 1.3
        elif name in ("score", "used", "2fa", "budgets") or "expenses (range)" in name:
            weight = 0.9
        else:
            weight = 1.4
        weights.append(weight)
    total = sum(weights) or 1
    return [round(100 * weight / total, 4) for weight in weights]
