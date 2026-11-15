"""Public website, student workspace and complete administrator menu routes."""

import copy, csv, io, json, os, re, secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
    Response,
)
from sqlalchemy import select, func, or_, delete, update
from sqlalchemy.exc import IntegrityError
from .models import *
from .services import *
from .auth import (
    login_required,
    admin_required,
    new_password,
    password_ok,
    bump_auth,
    state_for,
)

web = Blueprint("web", __name__)


def F(name, label=None, kind="text", required=False, options=None, **extra):
    return dict(
        name=name,
        label=label or name.replace("_", " ").title(),
        kind=kind,
        required=required,
        options=options or [],
        **extra,
    )


PUBLISH = ["published", "draft", "hidden"]
ANIM = [
    "none",
    "fade-up",
    "zoom-in",
    "slide-in",
    "bounce-in",
    "ken-burns",
    "float",
    "pulse",
    "pan",
    "fade-in",
]
STYLES = [
    "rounded",
    "circle",
    "blob",
    "frame",
    "polaroid",
    "shadow-pop",
    "gradient-border",
    "overlay-caption",
    "neon-glow",
]
CONTENT = {
    "events": dict(
        model=Event,
        title="Events",
        fields=[
            F("title", required=True, maxlength=190),
            F("description", kind="textarea"),
            F("event_date", kind="date", required=True),
            F("event_time", kind="time"),
            F("cover_image", kind="file"),
            F("latitude", kind="number", step="0.0000001", min=-90, max=90),
            F("longitude", kind="number", step="0.0000001", min=-180, max=180),
        ],
    ),
    "galleries": dict(
        model=Gallery,
        title="Galleries",
        fields=[
            F("title", required=True, maxlength=190),
            F("description", kind="textarea"),
            F("cover_image", kind="file"),
        ],
    ),
    "videos": dict(
        model=Video,
        title="Videos",
        fields=[
            F("title", required=True, maxlength=190),
            F(
                "platform",
                kind="select",
                options=["youtube", "tiktok", "facebook", "external"],
            ),
            F("video_url", required=True, maxlength=300),
            F("thumbnail", kind="file"),
            F("sort_order", kind="number", min=0, max=100000),
        ],
    ),
    "advertisements": dict(
        model=Advertisement,
        title="Advertisements",
        fields=[
            F("title", required=True, maxlength=190),
            F("description", kind="textarea"),
            F("cover_image", kind="file"),
            F("link_url", maxlength=300),
            F("start_date", kind="date"),
            F("end_date", kind="date"),
        ],
    ),
    "categories": dict(
        model=Category,
        title="Categories",
        fields=[
            F("name", required=True, maxlength=80),
            F("type", kind="select", options=["income", "expense"], required=True),
        ],
    ),
}
for spec in CONTENT.values():
    if spec["model"] != Category:
        spec["fields"] += [
            F("status", kind="select", options=PUBLISH),
            F("animation", kind="select", options=ANIM),
            F("style", kind="select", options=STYLES),
        ]


def get_object(model, id, owner=False):
    obj = db.session.get(model, id)
    if obj is None or owner and obj.user_id != g.user.id:
        abort(404)
    return obj


def filter_objects(objects, date_attr=None):
    q = request.args.get("q", "").strip().casefold()
    start = parse_date(request.args.get("from"), False)
    end = parse_date(request.args.get("to"), False)
    out = []
    for obj in objects:
        if q:
            hay = " ".join(
                str(getattr(obj, c.name) or "")
                for c in obj.__table__.columns
                if c.name not in ("password", "two_fa_secret")
            ).casefold()
            if q not in hay:
                continue
        if (
            request.args.get("status")
            and getattr(obj, "status", None) != request.args["status"]
        ):
            continue
        if date_attr:
            d = getattr(obj, date_attr)
            if isinstance(d, datetime):
                d = d.date()
            if start and d < start or end and d > end:
                continue
        if (
            request.args.get("category_id")
            and str(getattr(obj, "category_id", "")) != request.args["category_id"]
        ):
            continue
        out.append(obj)
    return out


def export_or_table(
    title,
    headers,
    rows,
    *,
    fields=None,
    objects=None,
    orientation="portrait",
    totals=None,
    subtitle="",
    extra=None,
):
    mode = request.args.get("do")
    if mode == "csv":
        plain = [
            [c.get("text", "") if isinstance(c, dict) else c for c in row]
            for row in rows
        ]
        return Response(
            csv_bytes(headers, plain),
            mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="report.csv"'},
        )
    if mode == "print":
        return render_template(
            "print.html",
            title=title,
            headers=headers,
            rows=rows,
            orientation=orientation,
            totals=totals,
            subtitle=subtitle or filter_description(),
        )
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    count = len(rows)
    last = max(1, (count + 19) // 20)
    page = min(page, last)
    return render_template(
        "table.html",
        title=title,
        headers=headers,
        rows=rows[(page - 1) * 20 : page * 20],
        fields=fields or [],
        objects=objects or [],
        totals=totals,
        subtitle=subtitle,
        count=count,
        page=page,
        last=last,
        extra=extra or {},
        edit_url=request.path,
    )


def filter_description():
    return (
        " | ".join(
            f"{k.replace('_', ' ').title()}: {v}"
            for k, v in request.args.items()
            if k not in ("do", "page") and v
        )
        or "No filters applied (all records)"
    )


def assign_fields(obj, fields, folder):
    for field in fields:
        name = field["name"]
        kind = field["kind"]
        raw = request.form.get(name, "").strip()
        if kind == "file":
            img = save_image(request.files.get(name), folder)
            if img:
                setattr(obj, name, img)
            if request.form.get("remove_" + name):
                setattr(obj, name, None)
            continue
        if field["required"] and not raw:
            raise ValueError(field["label"] + " is required.")
        if kind == "select":
            opts = [
                str(o[0] if isinstance(o, (tuple, list)) else o)
                for o in field["options"]
            ]
            if raw and raw not in opts:
                raise ValueError("Select a valid " + field["label"].lower() + ".")
        if kind == "date":
            value = parse_date(raw, field["required"])
        elif kind == "number":
            try:
                value = Decimal(raw) if raw else None
            except Exception:
                raise ValueError(field["label"] + " must be a number.")
            if value is not None and (
                not value.is_finite()
                or value < Decimal(str(field.get("min", -1000000000)))
                or value > Decimal(str(field.get("max", 1000000000)))
            ):
                raise ValueError(field["label"] + " is outside its allowed range.")
            if name == "sort_order":
                value = int(value or 0)
        elif kind == "checkbox":
            value = raw == "1"
        elif kind == "time":
            try:
                value = (
                    datetime.strptime(raw, "%H:%M").strftime("%H:%M") if raw else None
                )
            except ValueError:
                raise ValueError("Use a valid time (HH:MM).")
        else:
            value = raw
            if len(raw) > field.get("maxlength", 20000 if kind == "textarea" else 190):
                raise ValueError(field["label"] + " is too long.")
            if name.endswith("_url") and raw and safe_url(raw, "") == "":
                raise ValueError("Use an http(s) or local URL.")
        setattr(obj, name, value)


@web.get("/")
def home():
    lc = config("landing")
    content = {}
    for key, model in [
        ("events", Event),
        ("galleries", Gallery),
        ("videos", Video),
        ("ads", Advertisement),
    ]:
        records = list(
            db.session.scalars(
                select(model)
                .where(model.status == "published")
                .order_by(model.id.desc())
            )
        )
        if key == "ads":
            records = [
                r
                for r in records
                if (not r.start_date or r.start_date <= today())
                and (not r.end_date or r.end_date >= today())
            ]
        content[key] = records[: int(lc[key].get("limit", 6))]
    counts = dict(
        events=db.session.scalar(
            select(func.count()).select_from(Event).where(Event.status == "published")
        ),
        galleries=db.session.scalar(
            select(func.count())
            .select_from(Gallery)
            .where(Gallery.status == "published")
        ),
        videos=db.session.scalar(
            select(func.count()).select_from(Video).where(Video.status == "published")
        ),
        students=db.session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "student", User.status == "active")
        ),
    )
    return render_template("landing.html", lc=lc, content=content, counts=counts)


@web.get("/about")
def about():
    return render_template(
        "about.html",
        cfg=config("about"),
        stats={
            "Students": db.session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "student", User.status == "active")
            ),
            "Categories": db.session.scalar(select(func.count()).select_from(Category)),
            "Income records": db.session.scalar(
                select(func.count()).select_from(Income)
            ),
            "Expense records": db.session.scalar(
                select(func.count()).select_from(Expense)
            ),
        },
    )


@web.get("/gallery")
def gallery_query():
    try:
        id = int(request.args.get("id", "0"))
    except ValueError:
        abort(404)
    return redirect(url_for("web.gallery", id=id))


@web.get("/gallery/<int:id>")
def gallery(id):
    album = get_object(Gallery, id)
    if album.status != "published" and (not g.user or g.user.role != "admin"):
        abort(404)
    images = list(
        db.session.scalars(
            select(GalleryImage)
            .where(GalleryImage.gallery_id == id)
            .order_by(GalleryImage.sort_order, GalleryImage.id)
        )
    )
    return render_template("gallery.html", album=album, images=images)


@web.get("/uploads/<path:filename>")
def upload(filename):
    root = Path(current_app.config["UPLOAD_DIR"]).resolve()
    target = (root / filename).resolve()
    if (
        not target.is_relative_to(root)
        or target.suffix.lower()
        not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")
        or not target.is_file()
    ):
        abort(404)
    canonical = target.relative_to(root).as_posix()
    if canonical.startswith("receipts/"):
        if not g.user:
            abort(403)
        expense = db.session.scalar(
            select(Expense).where(Expense.receipt_image == canonical)
        )
        if not expense or (g.user.role != "admin" and expense.user_id != g.user.id):
            abort(403)
    return send_file(target, conditional=True)


@web.get("/admin")
@admin_required
def admin_dashboard():
    metrics = dict(
        students=db.session.scalar(
            select(func.count()).select_from(User).where(User.role == "student")
        ),
        pending=db.session.scalar(
            select(func.count()).select_from(User).where(User.status == "pending")
        ),
        income=db.session.scalar(select(func.coalesce(func.sum(Income.amount), 0))),
        expenses=db.session.scalar(select(func.coalesce(func.sum(Expense.amount), 0))),
    )
    students = list(
        db.session.scalars(
            select(User)
            .where(User.role == "student", User.status == "active")
            .limit(12)
        )
    )
    snaps = [snapshot(u.id) for u in students]
    snaps.sort(key=lambda s: s["score"])
    return render_template(
        "dashboard.html",
        title="Administrator Dashboard",
        metrics=metrics,
        snaps=snaps,
        admin=True,
    )


@web.get("/user/dashboard")
@login_required
def dashboard():
    if g.user.role == "admin":
        return redirect(url_for("web.admin_dashboard"))
    if not g.user.onboarded_at:
        return redirect(url_for("web.onboarding"))
    s = snapshot(g.user.id)
    return render_template(
        "dashboard.html",
        title="My Dashboard",
        metrics=dict(
            income=s["income"],
            expenses=s["expenses"],
            balance=s["balance"],
            budgets=len(s["budgets"]),
        ),
        s=s,
        admin=False,
    )


def budget_fields():
    cats = list(
        db.session.scalars(
            select(Category).where(
                Category.type == "expense",
                or_(Category.user_id == None, Category.user_id == g.user.id),
            )
        )
    )
    return [
        F(
            "category_id",
            "Budget scope",
            kind="select",
            options=[("", "All categories")] + [(str(c.id), c.name) for c in cats],
        ),
        F("period_type", kind="select", required=True, options=PERIODS),
        F(
            "amount",
            kind="number",
            required=True,
            min="0.01",
            max="999999999999.99",
            step="0.01",
        ),
        F(
            "week_start",
            kind="select",
            options=[("today", "Today · 7-day cycle")]
            + list((k, k.title()) for k in WEEKDAYS),
        ),
        F("period_start", "Custom start date", kind="date"),
        F("period_end", "Custom end date", kind="date"),
        F("alert_enabled", "Enable threshold warning", kind="checkbox"),
        F(
            "alert_threshold",
            "Warning threshold (%)",
            kind="number",
            min=1,
            max=100,
            step="0.01",
        ),
    ]


def save_budget(obj):
    kind = text("period_type", 10, True)
    week = text("week_start", 8) or "today"
    if kind not in PERIODS or week not in ["today"] + list(WEEKDAYS):
        raise ValueError("Choose a valid period and week start.")
    obj.category_id = category_for(
        request.form.get("category_id"), "expense", g.user.id
    )
    obj.amount = amount(request.form.get("amount"))
    if kind == "custom":
        start = parse_date(request.form.get("period_start"))
        end = parse_date(request.form.get("period_end"))
        if end < start:
            raise ValueError("End date cannot be before start date.")
    else:
        anchor = (
            obj.period_start
            if obj.id and obj.period_type == "weekly" and obj.week_start == week
            else today()
        )
        start, end = period_window(kind, week_start=week, anchor=anchor)
    obj.period_type = kind
    obj.week_start = week
    obj.period_start = start
    obj.period_end = end
    obj.alert_enabled = request.form.get("alert_enabled") == "1"
    try:
        threshold = Decimal(request.form.get("alert_threshold") or "80")
    except Exception:
        raise ValueError("Choose an alert threshold from 1 to 100.")
    if not threshold.is_finite() or not 1 <= threshold <= 100:
        raise ValueError("Choose an alert threshold from 1 to 100.")
    obj.alert_threshold = threshold


@web.route("/user/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if g.user.role == "admin":
        return redirect(url_for("web.admin_dashboard"))
    if request.method == "POST":
        try:
            if request.form.get("action") != "skip":
                obj = Budget(user_id=g.user.id)
                save_budget(obj)
                db.session.add(obj)
            g.user.onboarded_at = utcnow()
            audit("onboarding_budget")
            db.session.commit()
            return redirect(url_for("web.dashboard"))
        except ValueError as ex:
            db.session.rollback()
            flash(str(ex), "error")
    return render_template(
        "form.html",
        title="Set up your first budget",
        subtitle="Your account is approved. Choose your period, amount and spending scope. Weekly budgets start today or on your selected weekday.",
        fields=budget_fields(),
        obj={
            "period_type": "weekly",
            "week_start": "today",
            "alert_enabled": True,
            "alert_threshold": 80,
        },
        skip=True,
    )


@web.route("/user/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    if request.method == "POST":
        try:
            id = int(request.form.get("id") or 0)
            obj = get_object(Budget, id, True) if id else Budget(user_id=g.user.id)
            if request.form.get("action") == "delete":
                if not obj.id:
                    abort(400)
                db.session.delete(obj)
            else:
                save_budget(obj)
                db.session.add(obj)
            audit("budget_" + request.form.get("action", "save"))
            db.session.commit()
            flash("Budget saved.", "success")
            return redirect(request.path)
        except (ValueError, IntegrityError) as ex:
            db.session.rollback()
            flash(
                str(ex) if isinstance(ex, ValueError) else "Unable to save budget.",
                "error",
            )
    if request.args.get("form"):
        obj = (
            get_object(Budget, int(request.args["form"]), True)
            if request.args["form"] != "new"
            else {
                "period_type": "monthly",
                "week_start": "today",
                "alert_enabled": True,
                "alert_threshold": 80,
            }
        )
        return render_template(
            "form.html", title="Budget", fields=budget_fields(), obj=obj
        )
    evaluated = [
        evaluate(b)
        for b in filter_objects(
            list(db.session.scalars(select(Budget).where(Budget.user_id == g.user.id)))
        )
    ]
    if request.args.get("period_type"):
        evaluated = [
            b for b in evaluated if b["period_type"] == request.args["period_type"]
        ]
    if request.args.get("state"):
        evaluated = [b for b in evaluated if b["state"] == request.args["state"]]
    rows = [
        [
            b["id"],
            b["category"],
            b["period_type"].title(),
            f"{b['start']} → {b['end']}",
            money(b["amount"]),
            money(b["spent"]),
            money(b["remaining"]),
            f"{b['pct']:.1f}%",
            state_label(b["state"]),
        ]
        for b in evaluated
    ]
    return export_or_table(
        "My Budgets",
        [
            "#",
            "Category",
            "Period",
            "Current window",
            "Budget",
            "Spent",
            "Remaining",
            "Used",
            "Status",
        ],
        rows,
        fields=budget_fields(),
        orientation="landscape",
        totals=[
            "Totals",
            "",
            "",
            "",
            money(sum((b["amount"] for b in evaluated), Decimal(0))),
            money(sum((b["spent"] for b in evaluated), Decimal(0))),
            money(sum((b["remaining"] for b in evaluated), Decimal(0))),
            "",
            "",
        ],
    )


@web.route("/user/<kind>", methods=["GET", "POST"])
@login_required
def ledger(kind):
    if kind not in ("incomes", "expenses"):
        abort(404)
    is_income = kind == "incomes"
    model = Income if is_income else Expense
    date_attr = "income_date" if is_income else "expense_date"
    label = "source" if is_income else "description"
    cats = list(
        db.session.scalars(
            select(Category).where(
                Category.type == ("income" if is_income else "expense"),
                or_(Category.user_id == None, Category.user_id == g.user.id),
            )
        )
    )
    fields = [
        F(label, required=True, maxlength=150 if is_income else 190),
        F(
            "category_id",
            kind="select",
            options=[("", "Uncategorised")] + [(str(c.id), c.name) for c in cats],
        ),
        F(
            "amount",
            kind="number",
            required=True,
            min=".01",
            max="999999999999.99",
            step=".01",
        ),
        F(date_attr, kind="date", required=True),
    ]
    if not is_income:
        fields += [
            F("payee", maxlength=120),
            F("receipt_image", "Receipt image", kind="file"),
        ]
    fields += [F("notes", kind="textarea")]
    if request.method == "POST":
        try:
            id = int(request.form.get("id") or 0)
            obj = get_object(model, id, True) if id else model(user_id=g.user.id)
            if request.form.get("action") == "delete":
                if not obj.id:
                    abort(400)
                db.session.delete(obj)
            else:
                setattr(obj, label, text(label, 150 if is_income else 190, True))
                obj.amount = amount(request.form.get("amount"))
                setattr(obj, date_attr, parse_date(request.form.get(date_attr)))
                obj.category_id = category_for(
                    request.form.get("category_id"),
                    "income" if is_income else "expense",
                    g.user.id,
                )
                obj.notes = text("notes", 20000)
                if not is_income:
                    obj.payee = text("payee", 120)
                    image = save_image(request.files.get("receipt_image"), "receipts")
                    if image:
                        obj.receipt_image = image
                    if request.form.get("remove_receipt_image"):
                        obj.receipt_image = None
                db.session.add(obj)
            audit(kind + "_" + request.form.get("action", "save"))
            db.session.commit()
            flash("Record saved.", "success")
            return redirect(request.path)
        except (ValueError, IntegrityError) as ex:
            db.session.rollback()
            flash(
                str(ex)
                if isinstance(ex, ValueError)
                else "Unable to save this record.",
                "error",
            )
    if request.args.get("form"):
        obj = (
            get_object(model, int(request.args["form"]), True)
            if request.args["form"] != "new"
            else {date_attr: today()}
        )
        return render_template(
            "form.html",
            title=("Income" if is_income else "Expense") + " entry",
            fields=fields,
            obj=obj,
        )
    objects = filter_objects(
        list(
            db.session.scalars(
                select(model)
                .where(model.user_id == g.user.id)
                .order_by(getattr(model, date_attr).desc(), model.id.desc())
            )
        ),
        date_attr,
    )
    rows = []
    for r in objects:
        row = [
            r.id,
            str(getattr(r, date_attr)),
            r.category.name if r.category else "Uncategorised",
            getattr(r, label),
        ]
        if not is_income:
            row += [
                r.payee or "",
                {
                    "text": "View receipt" if r.receipt_image else "—",
                    "href": image_url(r.receipt_image) if r.receipt_image else "",
                },
            ]
        row += [r.notes or "", money(r.amount)]
        rows.append(row)
    heads = (
        ["#", "Date", "Category", "Source" if is_income else "Description"]
        + ([] if is_income else ["Payee", "Receipt"])
        + ["Notes", "Amount"]
    )
    return export_or_table(
        "Income" if is_income else "Expenses",
        heads,
        rows,
        fields=fields,
        totals=["Total"]
        + [""] * (len(heads) - 2)
        + [money(sum((r.amount for r in objects), Decimal(0)))],
        extra={
            "alerts": [b for b in snapshot(g.user.id)["budgets"] if b["state"] != "ok"]
        },
    )


def video_embed(value):
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(value or "")
    vid = ""
    if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        vid = parse_qs(parsed.query).get("v", [""])[0]
    elif parsed.hostname == "youtu.be":
        vid = parsed.path.strip("/")
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        return "https://www.youtube-nocookie.com/embed/" + vid
    return ""


def state_label(state):
    return {"ok": "On track", "warn": "Near limit", "over": "Over budget"}[state]


@web.get("/user/behavior")
@login_required
def behavior():
    s = snapshot(g.user.id)
    if request.args.get("do") == "print":
        return render_template(
            "behavior_print.html",
            title="My Budget Behaviour",
            s=s,
            orientation="landscape",
        )
    return render_template("behavior.html", title="My Budget Behaviour", s=s)


@web.route("/admin/<entity>", methods=["GET", "POST"])
@admin_required
def content_crud(entity):
    spec = CONTENT.get(entity)
    if not spec:
        abort(404)
    model = spec["model"]
    fields = spec["fields"]
    folder = {"advertisements": "ads"}.get(entity, entity)
    if request.method == "POST":
        try:
            id = int(request.form.get("id") or 0)
            obj = get_object(model, id) if id else model()
            if request.form.get("action") == "delete":
                if model == Category:
                    for linked in (Income, Expense, Budget):
                        db.session.execute(
                            update(linked)
                            .where(linked.category_id == id)
                            .values(category_id=None)
                        )
                if model == Gallery:
                    db.session.execute(
                        delete(GalleryImage).where(GalleryImage.gallery_id == id)
                    )
                db.session.delete(obj)
            else:
                assign_fields(obj, fields, folder)
                if (
                    model == Advertisement
                    and obj.start_date
                    and obj.end_date
                    and obj.end_date < obj.start_date
                ):
                    raise ValueError("End date must follow start date.")
                db.session.add(obj)
            audit(entity + "_" + request.form.get("action", "save"))
            db.session.commit()
            flash("Changes saved.", "success")
            return redirect(request.path)
        except (ValueError, IntegrityError) as ex:
            db.session.rollback()
            flash(
                str(ex) if isinstance(ex, ValueError) else "Unable to save record.",
                "error",
            )
    if request.args.get("form"):
        obj = (
            get_object(model, int(request.args["form"]))
            if request.args["form"] != "new"
            else {
                "status": "published",
                "animation": "fade-up",
                "style": "rounded",
                "type": "expense",
            }
        )
        return render_template("form.html", title=spec["title"], fields=fields, obj=obj)
    records = filter_objects(
        list(db.session.scalars(select(model).order_by(model.id.desc()))), "created_at"
    )
    rows = []
    for r in records:
        if model == Category:
            row = [r.id, r.name, r.type, r.created_at.strftime("%Y-%m-%d")]
        else:
            image = getattr(r, "cover_image", None) or getattr(r, "thumbnail", None)
            row = [r.id, {"text": r.title, "image": image_url(image) if image else ""}]
            if model == Event:
                row += [str(r.event_date), r.event_time or ""]
            if model == Gallery:
                row += [
                    {
                        "text": "Manage photos",
                        "href": url_for("web.gallery_images", gallery_id=r.id),
                    }
                ]
            if model == Video:
                row += [{"text": r.platform, "href": safe_url(r.video_url)}]
            row += [r.status, r.created_at.strftime("%Y-%m-%d")]
        rows.append(row)
    headers = (
        ["#", "Name", "Type", "Created"]
        if model == Category
        else ["#", "Title"]
        + (
            ["Date", "Time"]
            if model == Event
            else ["Photos"]
            if model == Gallery
            else ["Platform"]
            if model == Video
            else []
        )
        + ["Status", "Created"]
    )
    return export_or_table(spec["title"], headers, rows, fields=fields)


@web.route("/admin/gallery_images", methods=["GET", "POST"])
@admin_required
def gallery_images():
    gallery = get_object(Gallery, int(request.args.get("gallery_id", "0")))
    if request.method == "POST":
        try:
            if request.form.get("action") == "delete":
                record = get_object(GalleryImage, int(request.form.get("id", "0")))
                if record.gallery_id != gallery.id:
                    abort(404)
                db.session.delete(record)
            elif request.form.get("action") == "edit":
                record = get_object(GalleryImage, int(request.form.get("id", "0")))
                if record.gallery_id != gallery.id:
                    abort(404)
                record.caption = text("caption", 190)
                record.sort_order = max(
                    0, min(100000, int(request.form.get("sort_order") or 0))
                )
            elif request.form.get("action") == "cover":
                record = get_object(GalleryImage, int(request.form.get("id", "0")))
                if record.gallery_id != gallery.id:
                    abort(404)
                gallery.cover_image = record.image
            else:
                file = save_image(request.files.get("image"), "galleries")
                if not file:
                    raise ValueError("Select a photo.")
                db.session.add(
                    GalleryImage(
                        gallery_id=gallery.id,
                        image=file,
                        caption=text("caption", 190),
                        sort_order=int(request.form.get("sort_order") or 0),
                    )
                )
            db.session.commit()
            flash("Gallery updated.", "success")
            return redirect(request.url)
        except ValueError as ex:
            db.session.rollback()
            flash(str(ex), "error")
    return render_template(
        "gallery_admin.html",
        gallery=gallery,
        images=list(
            db.session.scalars(
                select(GalleryImage)
                .where(GalleryImage.gallery_id == gallery.id)
                .order_by(GalleryImage.sort_order)
            )
        ),
    )


@web.route("/admin/users", methods=["GET", "POST"])
@admin_required
def users():
    fields = [
        F("name", required=True, maxlength=120),
        F("email", kind="email", required=True, maxlength=190),
        F("student_number", maxlength=40),
        F(
            "grade_level",
            kind="select",
            options=[("", "Not applicable")] + [(x, x) for x in LEVELS],
        ),
        F("course", maxlength=120),
        F("section", maxlength=60),
        F("contact_number", maxlength=40),
        F("role", kind="select", options=["student", "admin"]),
        F(
            "status",
            kind="select",
            options=["pending", "active", "rejected", "disabled"],
        ),
        F("password", "New password (required for new accounts)", kind="password"),
        F(
            "_admin_password",
            "Your current administrator password",
            kind="password",
            required=True,
        ),
    ]
    if request.method == "POST":
        try:
            if not password_ok(
                g.user.password, request.form.get("_admin_password", "")
            ):
                raise ValueError(
                    "Enter your own current administrator password to manage accounts."
                )
            id = int(request.form.get("id") or 0)
            obj = get_object(User, id) if id else User()
            old_admin = obj.role == "admin" and obj.status == "active"
            if request.form.get("action") == "delete":
                obj.status = "disabled"
            else:
                obj.name = text("name", 120, True)
                email = text("email", 190, True).lower()
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                    raise ValueError("Enter a valid email.")
                obj.email = email
                obj.student_number = text("student_number", 40) or None
                obj.grade_level = text("grade_level", 40)
                obj.course = text("course", 120)
                obj.section = text("section", 60)
                obj.contact_number = text("contact_number", 40)
                role = text("role", 20)
                status = text("status", 20)
                if role not in ("student", "admin") or status not in (
                    "pending",
                    "active",
                    "rejected",
                    "disabled",
                ):
                    raise ValueError("Choose valid role and status values.")
                obj.role = role
                obj.status = status
                raw = request.form.get("password", "")
                if raw:
                    obj.password = new_password(raw)
                elif not obj.id:
                    raise ValueError("A new account needs a password.")
            if old_admin and (obj.role != "admin" or obj.status != "active"):
                # no_autoflush keeps the count based on the pre-edit state
                with db.session.no_autoflush:
                    active = db.session.scalar(
                        select(func.count())
                        .select_from(User)
                        .where(User.role == "admin", User.status == "active")
                    )
                if active <= 1:
                    raise ValueError(
                        "The last active administrator cannot be disabled or demoted."
                    )
            if obj.status == "active":
                obj.approved_by = g.user.id
                obj.approved_at = utcnow()
            db.session.add(obj)
            db.session.flush()
            bump_auth(obj)
            audit("user_manage", str(obj.id))
            db.session.commit()
            if obj.id == g.user.id:
                session["auth_version"] = state_for(obj.id).version
            flash(
                "Account updated. Removal disables access but preserves financial records.",
                "success",
            )
            return redirect(request.path)
        except (ValueError, IntegrityError) as ex:
            db.session.rollback()
            flash(
                str(ex)
                if isinstance(ex, ValueError)
                else "Email or student number is already in use.",
                "error",
            )
    if request.args.get("form"):
        obj = (
            get_object(User, int(request.args["form"]))
            if request.args["form"] != "new"
            else {"role": "student", "status": "pending"}
        )
        return render_template(
            "form.html", title="User Account", fields=fields, obj=obj
        )
    records = filter_objects(
        list(db.session.scalars(select(User).order_by(User.name))), "created_at"
    )
    rows = [
        [
            u.id,
            u.name,
            u.email,
            u.role,
            u.status,
            "Enabled" if u.two_fa_enabled else "Off",
            str(u.last_login or "—"),
            str(u.created_at),
        ]
        for u in records
    ]
    return export_or_table(
        "User Accounts",
        ["#", "Name", "Email", "Role", "Status", "2FA", "Last login", "Created"],
        rows,
        fields=fields,
        orientation="landscape",
        extra={"disable_only": True},
    )


@web.route("/admin/registrations", methods=["GET", "POST"])
@admin_required
def registrations():
    if request.method == "POST":
        try:
            ids = request.form.getlist("ids") or [request.form.get("id", "")]
            action = request.form.get("action")
            reason = text("reason", 190)
            if action not in ("approve", "reject", "reconsider"):
                abort(400)
            if action == "reject" and not reason:
                raise ValueError("Enter a reason for rejection.")
            approved = []
            for raw in ids:
                user = get_object(User, int(raw))
                if user.role != "student":
                    raise ValueError("Only student registrations are reviewed here.")
                if action == "approve" and user.status != "pending":
                    continue
                user.status = "rejected" if action == "reject" else "active"
                user.approved_by = g.user.id
                user.approved_at = utcnow()
                user.rejection_reason = reason if action == "reject" else None
                bump_auth(user)
                audit("registration_" + action, user.email)
                if user.status == "active":
                    approved.append(user)
            db.session.commit()
            for approved_user in approved:
                notify_approval(approved_user)
            flash(
                "Registration decisions saved. Approved students can now sign in. Notify the students directly if email is not configured.",
                "success",
            )
            return redirect(request.url)
        except ValueError as ex:
            db.session.rollback()
            flash(str(ex), "error")
    stmt = select(User).where(User.role == "student")
    history = request.args.get("tab") == "history"
    stmt = (
        stmt.where(User.status != "pending")
        if history
        else stmt.where(User.status == "pending")
    )
    records = filter_objects(
        list(db.session.scalars(stmt.order_by(User.created_at.desc()))), "created_at"
    )
    rows = [
        [
            u.id,
            u.name,
            u.student_number or "—",
            u.grade_level or "—",
            u.course or "",
            u.section or "",
            u.email,
            u.contact_number or "",
            str(u.created_at.date()),
            u.status,
        ]
        for u in records
    ]
    return export_or_table(
        "Registration History" if history else "Pending Registrations",
        [
            "#",
            "Student",
            "Student no.",
            "Grade / year",
            "Course",
            "Section",
            "Email",
            "Contact",
            "Registered",
            "Status",
        ],
        rows,
        orientation="landscape",
        extra={"registrations": True, "history": history},
    )


@web.get("/admin/monitor")
@admin_required
def monitor():
    uid = request.args.get("student")
    if uid:
        user = get_object(User, int(uid))
        if user.role != "student":
            abort(404)
        s = snapshot(user.id)
        s["entries"] = filter_objects(
            list(
                db.session.scalars(
                    select(Expense)
                    .where(Expense.user_id == user.id)
                    .order_by(Expense.expense_date.desc())
                )
            ),
            "expense_date",
        )
        if request.args.get("do") == "csv":
            return Response(
                csv_bytes(
                    ["Date", "Category", "Description", "Payee", "Amount"],
                    [
                        [
                            str(e.expense_date),
                            e.category.name if e.category else "Uncategorised",
                            e.description,
                            e.payee or "",
                            str(e.amount),
                        ]
                        for e in s["entries"]
                    ],
                ),
                mimetype="text/csv",
                headers={
                    "Content-Disposition": "attachment; filename=student-expenses.csv"
                },
            )
        if request.args.get("do") == "print":
            return render_template(
                "behavior_print.html",
                title="Student Monitor — " + user.name,
                s=s,
                orientation="landscape",
                admin=True,
            )
        return render_template(
            "behavior.html", title="Student Monitor — " + user.name, s=s, admin=True
        )
    people = filter_objects(
        list(db.session.scalars(select(User).where(User.role == "student")))
    )
    snaps = [snapshot(u.id) for u in people]
    snaps.sort(key=lambda s: s["score"])
    if request.args.get("state"):
        snaps = [
            s
            for s in snaps
            if ("over" if s["over"] else "warn" if s["warn"] else "ok")
            == request.args["state"]
        ]
    rows = []
    for snap in snaps:
        entries = filter_objects(
            list(
                db.session.scalars(
                    select(Expense).where(Expense.user_id == snap["user"].id)
                )
            ),
            "expense_date",
        )
        pct = float(snap["spent"] / snap["planned"] * 100) if snap["planned"] else 0
        rows.append(
            [
                snap["user"].id,
                {
                    "text": snap["user"].name + " · " + snap["user"].email,
                    "href": url_for("web.monitor", student=snap["user"].id),
                },
                len(snap["budgets"]),
                str(snap["score"]) + "/100",
                money(snap["planned"]),
                money(snap["spent"]),
                money(snap["planned"] - snap["spent"]),
                f"{pct:.1f}%",
                state_label(
                    "over" if snap["over"] else "warn" if snap["warn"] else "ok"
                ),
                len(entries),
                money(sum((e.amount for e in entries), Decimal(0))),
            ]
        )
    return export_or_table(
        "Student Monitoring Report",
        [
            "#",
            "Student",
            "Budgets",
            "Score",
            "Planned",
            "Spent (windows)",
            "Remaining",
            "Used",
            "Status",
            "Expenses (range)",
            "Range spend",
        ],
        rows,
        orientation="landscape",
    )


def financial_rows(admin=False):
    items = []
    for model, attr, desc, kind in [
        (Income, "income_date", "source", "Income"),
        (Expense, "expense_date", "description", "Expense"),
    ]:
        stmt = select(model)
        if not admin:
            stmt = stmt.where(model.user_id == g.user.id)
        elif request.args.get("student"):
            stmt = stmt.where(model.user_id == int(request.args["student"]))
        if (
            request.args.get("ttype")
            and request.args["ttype"].casefold() != kind.casefold()
        ):
            continue
        for obj in filter_objects(list(db.session.scalars(stmt)), attr):
            items.append(
                [
                    getattr(obj, attr),
                    obj.user.name,
                    kind,
                    obj.category.name if obj.category else "Uncategorised",
                    getattr(obj, desc),
                    obj.amount,
                ]
            )
    return sorted(items, key=lambda r: r[0], reverse=True)


def financial_report(admin=False):
    items = financial_rows(admin)
    inc = sum((r[-1] for r in items if r[2] == "Income"), Decimal(0))
    exp = sum((r[-1] for r in items if r[2] == "Expense"), Decimal(0))
    rows = [
        [i + 1, str(r[0])] + ([r[1]] if admin else []) + [r[2], r[3], r[4], money(r[5])]
        for i, r in enumerate(items)
    ]
    headers = (
        ["#", "Date"]
        + (["Student"] if admin else [])
        + ["Type", "Category", "Description", "Amount"]
    )
    return export_or_table(
        "Financial Report" if admin else "My Financial Report",
        headers,
        rows,
        totals=["Net balance"] + [""] * (len(headers) - 2) + [money(inc - exp)],
        subtitle=f"{filter_description()} | Income: {money(inc)} | Expenses: {money(exp)} | Net: {money(inc - exp)}",
    )


@web.get("/admin/reports")
@admin_required
def admin_reports():
    return financial_report(True)


@web.get("/user/reports")
@login_required
def reports():
    return financial_report(False)


@web.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def company_settings():
    fields = [
        F(k, kind="textarea" if k == "site_tagline" else "text", maxlength=300)
        for k in [
            "site_name",
            "company_name",
            "site_tagline",
            "company_address",
            "company_email",
            "company_phone",
            "company_website",
            "currency_symbol",
            "currency_code",
        ]
    ]
    fields += [
        F("currency_position", kind="select", options=["before", "after"]),
        F(
            "timezone",
            kind="select",
            options=[
                "Asia/Manila",
                "Pacific/Port_Moresby",
                "UTC",
                "Asia/Singapore",
                "America/New_York",
                "Europe/London",
            ],
        ),
        F("header_bg", kind="color"),
        F("header_fg", kind="color"),
        F("footer_bg", kind="color"),
        F("footer_fg", kind="color"),
        F("force_2fa_admin", "Require 2FA for administrators", kind="checkbox"),
        F("logo", kind="file"),
        F("favicon", kind="file"),
    ]
    if request.method == "POST":
        try:
            if request.form.get("action") == "image_check":
                return render_template(
                    "diagnostics.html",
                    title="Image Delivery Check",
                    checks=image_checks(),
                )
            for f in fields:
                k = f["name"]
                if f["kind"] == "file":
                    image = save_image(request.files.get(k), "logo")
                    if image:
                        set_setting(k, image)
                    if request.form.get("remove_" + k):
                        set_setting(k, "")
                elif f["kind"] == "checkbox":
                    set_setting(k, "1" if request.form.get(k) == "1" else "0")
                else:
                    value = text(k, f.get("maxlength", 190))
                    if f["kind"] == "color" and value and not color(value):
                        raise ValueError("Use six-digit hex colours.")
                    if f["kind"] == "select" and value not in f["options"]:
                        raise ValueError("Choose a valid " + f["label"] + ".")
                    set_setting(k, value)
            audit("settings_save")
            db.session.commit()
            flash("Settings saved.", "success")
            return redirect(request.path)
        except ValueError as ex:
            db.session.rollback()
            flash(str(ex), "error")
    return render_template(
        "form.html",
        title="Company Settings",
        fields=fields,
        obj={k: setting(k) for k in SETTINGS},
        image_check=True,
    )


def image_checks():
    checks = []
    for folder in [
        "logo",
        "avatars",
        "events",
        "galleries",
        "ads",
        "videos",
        "receipts",
        "landing",
        "about",
    ]:
        path = Path(current_app.config["UPLOAD_DIR"]) / folder
        path.mkdir(exist_ok=True)
        checks.append(
            (folder, "Writable" if os.access(path, os.W_OK) else "Not writable")
        )
    for name in ["logo", "favicon"]:
        value = setting(name)
        if value and not value.startswith("assets-img:"):
            checks.append(
                (
                    name + " → " + value,
                    "Present"
                    if (Path(current_app.config["UPLOAD_DIR"]) / value).is_file()
                    else "Missing · re-upload image",
                )
            )
    return checks


@web.route("/admin/themes", methods=["GET", "POST"])
@admin_required
def themes():
    if request.method == "POST":
        try:
            obj = get_object(Theme, int(request.form.get("id", "0")))
            if request.form.get("action") == "activate":
                set_setting("theme_slug", obj.slug)
            else:
                cfg = json.loads(obj.config_json)
                for key in [
                    "bg",
                    "surface",
                    "surface_2",
                    "text",
                    "muted",
                    "primary",
                    "primary_dark",
                    "accent",
                    "border",
                ]:
                    val = text(key, 7)
                    if not color(val):
                        raise ValueError("Theme colours must use #RRGGBB.")
                    cfg[key] = val
                cfg["font_choice"] = request.form.get("font_choice", "sans")
                if cfg["font_choice"] not in ("sans", "serif", "mono"):
                    raise ValueError("Choose a supported font stack.")
                cfg["gradient"] = (
                    f"linear-gradient(135deg,{cfg['primary']},{cfg['accent']})"
                )
                obj.config_json = json.dumps(cfg)
                obj.name = text("name", 100, True)
            audit("theme_update", obj.slug)
            db.session.commit()
            flash("Theme saved and applied when active.", "success")
            return redirect(request.path)
        except ValueError as ex:
            db.session.rollback()
            flash(str(ex), "error")
    if request.args.get("form"):
        obj = get_object(Theme, int(request.args["form"]))
        cfg = json.loads(obj.config_json)
        cfg.update(id=obj.id, name=obj.name)
        cfg.setdefault("font_choice", "sans")
        return render_template(
            "form.html",
            title="Edit theme",
            obj=cfg,
            fields=[
                F("name", required=True, maxlength=100),
                F(
                    "font_choice",
                    "Typography",
                    kind="select",
                    options=["sans", "serif", "mono"],
                ),
            ]
            + [
                F(k, kind="color")
                for k in [
                    "bg",
                    "surface",
                    "surface_2",
                    "text",
                    "muted",
                    "primary",
                    "primary_dark",
                    "accent",
                    "border",
                ]
            ],
        )
    # Re-add built-in themes deleted from an existing installation, without overwriting edits.
    seed_defaults()
    records = list(db.session.scalars(select(Theme).order_by(Theme.id)))
    return render_template(
        "themes.html", themes=[(r, json.loads(r.config_json)) for r in records]
    )


STUDIO_CHOICES = {
    "layout": ["text-only", "image-right", "image-left", "background"],
    "align": ["left", "center"],
    "height": ["screen", "compact", "standard", "tall"],
    "bg_gradient": ["none", "brand", "dark", "bottom"],
    "image_style": ["rounded", "circle", "blob", "frame", "polaroid"],
    "title_size": ["sm", "md", "lg", "xl"],
    "sub_size": ["sm", "md", "lg"],
    "kicker_style": ["glass", "solid", "plain"],
    "btn_style": ["white", "glass", "solid"],
    "stats_style": ["glass", "solid", "outline"],
    "media_size": ["sm", "md", "lg", "full"],
    "shadow": ["none", "soft", "medium", "strong", "glow"],
    "content_vpos": ["top", "middle", "bottom"],
    "text_vpos": ["auto", "top", "middle", "bottom"],
    "media_vpos": ["auto", "top", "middle", "bottom"],
    "text_align": ["", "left", "center", "right"],
    "media_align": ["auto", "left", "center", "right"],
    "anim_image": ANIM,
    "anim_bg": ANIM,
}


@web.route("/admin/landing", methods=["GET", "POST"])
@admin_required
def landing_studio():
    cfg = config("landing")
    section = request.args.get("section", "hero")
    if section not in cfg:
        section = "hero"
    values = cfg[section]
    fields = []
    for key, default in DEFAULTS["landing"][section].items():
        if section in ("location", "band") and key in ("cols", "limit"):
            continue
        if key in ("image", "bg") and section == "hero":
            f = F(
                key,
                "Hero foreground image" if key == "image" else "Background image",
                kind="file",
            )
        elif key in STUDIO_CHOICES and section == "hero":
            f = F(key, kind="select", options=STUDIO_CHOICES[key])
        elif key in (
            "on",
            "show_stats",
            "kicker_show",
            "sub_show",
            "btn1_show",
            "btn2_show",
            "btn3_show",
        ) or key.startswith("stat_"):
            f = F(key, kind="checkbox")
        elif isinstance(default, int):
            f = F(
                key,
                kind="range",
                min=-200
                if key.endswith(("_x", "_y"))
                else 1
                if key in ("cols", "limit")
                else 0,
                max=200
                if key.endswith(("_x", "_y"))
                else 150
                if key == "shadow_strength"
                else 130
                if key == "media_scale"
                else 100
                if key in ("bg_trans", "overlay")
                else 4
                if key == "cols"
                else 30
                if key == "limit"
                else 12,
            )
        elif "color" in key or key.endswith(("_fg", "_bd", "_bg")):
            f = F(
                key,
                kind="text",
                maxlength=7,
                help="Blank = theme default; otherwise #RRGGBB.",
            )
        elif key in ("style", "animation"):
            f = F(key, kind="select", options=STYLES if key == "style" else ANIM)
        else:
            f = F(key, kind="textarea" if key == "subtitle" else "text", maxlength=1000)
        fields.append(f)
    if section == "hero":
        fields = [
            F(k, kind="textarea" if k == "hero_subtitle" else "text", maxlength=1000)
            for k in ["hero_title", "hero_subtitle", "hero_cta", "hero_cta_link"]
        ] + fields
        values = {
            **values,
            **{
                k: setting(k)
                for k in ["hero_title", "hero_subtitle", "hero_cta", "hero_cta_link"]
            },
        }
    if request.method == "POST":
        try:
            for f in fields:
                k = f["name"]
                raw = request.form.get(k, "").strip()
                if k.startswith("hero_"):
                    set_setting(k, text(k, 1000))
                    continue
                if f["kind"] == "file":
                    image = save_image(request.files.get(k), "landing")
                    if image:
                        cfg[section][k] = image
                    if request.form.get("remove_" + k):
                        cfg[section][k] = ""
                elif f["kind"] == "checkbox":
                    cfg[section][k] = int(raw == "1")
                elif f["kind"] == "range":
                    cfg[section][k] = max(f["min"], min(f["max"], int(raw or 0)))
                else:
                    if f["kind"] == "select" and raw not in f["options"]:
                        raise ValueError("Select a valid " + f["label"] + ".")
                    if (
                        ("color" in k or k.endswith(("_fg", "_bg", "_bd")))
                        and k != "anim_bg"
                        and raw
                        and not color(raw)
                    ):
                        raise ValueError("Use #RRGGBB or leave the colour blank.")
                    if (
                        k == "layout"
                        and section != "hero"
                        and raw
                        not in (
                            "grid",
                            "list",
                            "carousel",
                            "masonry",
                            "featured",
                            "split",
                            "map-right",
                            "map-left",
                            "stacked",
                            "banner",
                            "cards",
                        )
                    ):
                        raise ValueError(
                            "Choose a supported section layout: grid, list, carousel, featured, split, map-left, map-right, stacked or banner."
                        )
                    if (
                        k in ("bg",)
                        and section != "hero"
                        and raw not in ("plain", "tinted", "dark", "gradient")
                    ):
                        raise ValueError(
                            "Background must be plain, tinted, dark or gradient."
                        )
                    cfg[section][k] = text(k, f.get("maxlength", 1000))
            set_setting("landing_cfg", json.dumps(cfg, ensure_ascii=False))
            audit("landing_update", section)
            db.session.commit()
            flash("Landing section saved.", "success")
            return redirect(request.url)
        except ValueError as ex:
            db.session.rollback()
            flash(str(ex), "error")
    return render_template(
        "form.html",
        title="Page Studio · " + section.title(),
        subtitle="Every entity is configurable. Blank colours use the active theme. Adjust each section, then preview the public website.",
        fields=fields,
        obj=values,
        tabs=[(k, "?section=" + k) for k in cfg],
        preview="/",
    )


@web.route("/admin/about", methods=["GET", "POST"])
@admin_required
def about_editor():
    cfg = config("about")
    fields = []
    for k, v in DEFAULTS["about"].items():
        if k == "updated_at":
            continue
        fields.append(
            F(
                k,
                kind="file"
                if k == "image"
                else "checkbox"
                if k.startswith("show_")
                else "json"
                if isinstance(v, list)
                else "textarea"
                if k in ("body", "lead")
                else "text",
                maxlength=20000 if k in ("body", "lead") else 1000,
            )
        )
    if request.method == "POST":
        try:
            for f in fields:
                k = f["name"]
                kind = f["kind"]
                if kind == "file":
                    image = save_image(request.files.get(k), "about")
                    if image:
                        cfg[k] = image
                    if request.form.get("remove_" + k):
                        cfg[k] = ""
                elif kind == "checkbox":
                    cfg[k] = int(request.form.get(k) == "1")
                elif kind == "json":
                    value = json.loads(request.form.get(k, "[]"))
                    if not isinstance(value, list) or not all(
                        isinstance(item, dict)
                        and all(isinstance(x, str) for x in item.values())
                        for item in value
                    ):
                        raise ValueError("Use an array of text objects.")
                    cfg[k] = value
                else:
                    cfg[k] = text(k, f.get("maxlength", 1000))
            cfg["updated_at"] = utcnow().isoformat()
            set_setting("about_cfg", json.dumps(cfg, ensure_ascii=False))
            db.session.commit()
            flash("About page saved.", "success")
            return redirect(request.path)
        except ValueError as ex:
            db.session.rollback()
            flash(str(ex), "error")
    return render_template(
        "form.html", title="About Page", fields=fields, obj=cfg, preview="/about"
    )


@web.route("/admin/map", methods=["GET", "POST"])
@admin_required
def map_editor():
    fields = [
        F("company_address", required=True, maxlength=300),
        F("latitude", kind="number", step=".0000001", min=-90, max=90, required=True),
        F(
            "longitude",
            kind="number",
            step=".0000001",
            min=-180,
            max=180,
            required=True,
        ),
    ]
    if request.method == "POST":
        try:
            lat = Decimal(request.form.get("latitude", ""))
            lon = Decimal(request.form.get("longitude", ""))
            if (
                not lat.is_finite()
                or not lon.is_finite()
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
            ):
                raise ValueError("Enter valid latitude and longitude.")
            set_setting("company_address", text("company_address", 300, True))
            set_setting("latitude", lat)
            set_setting("longitude", lon)
            db.session.commit()
            flash("Map location saved.", "success")
            return redirect(request.path)
        except Exception as ex:
            db.session.rollback()
            if not isinstance(ex, (ValueError, ArithmeticError)):
                raise
            flash("Enter a valid address, latitude and longitude.", "error")
    return render_template(
        "form.html",
        title="Map & Location",
        subtitle="The public map includes geolocation distance, directions and Reset.",
        fields=fields,
        obj={f["name"]: setting(f["name"]) for f in fields},
        show_map=True,
    )


@web.route("/admin/database", methods=["GET", "POST"])
@admin_required
def database():
    from .maintenance import create_backup, restore_payload

    if request.method == "POST":
        try:
            action = request.form.get("action")
            if action in ("backup", "restore", "delete_backup") and not password_ok(
                g.user.password, request.form.get("current_password", "")
            ):
                raise ValueError("Enter your current administrator password.")
            if action == "backup":
                backup = create_backup()
                flash("Backup created: " + backup.filename, "success")
            elif action == "schedule":
                freq = int(request.form.get("auto_backup_freq") or 24)
                keep = int(request.form.get("auto_backup_keep") or 5)
                if freq not in (6, 12, 24, 48, 168, 720) or not 2 <= keep <= 100:
                    raise ValueError("Choose a valid interval and keep count.")
                set_setting(
                    "auto_backup",
                    "1" if request.form.get("auto_backup") == "1" else "0",
                )
                set_setting("auto_backup_freq", freq)
                set_setting("auto_backup_keep", keep)
                db.session.commit()
                flash(
                    "Automatic backups configured. Due backups run on the next administrator page load.",
                    "success",
                )
            elif action == "restore":
                if request.form.get("confirm") != "RESTORE":
                    raise ValueError(
                        "Type RESTORE to confirm replacement of live data."
                    )
                file = request.files.get("backup")
                if not file:
                    raise ValueError("Choose a Python JSON backup.")
                raw = file.read(current_app.config["MAX_CONTENT_LENGTH"] + 1)
                if len(raw) > current_app.config["MAX_CONTENT_LENGTH"]:
                    raise ValueError(
                        "Backup exceeds upload limit. Use the CLI for larger backups."
                    )
                payload = json.loads(raw.decode("utf-8-sig"))
                from .maintenance import validate_payload

                validate_payload(payload)
                create_backup("before-restore")
                restore_payload(payload)
                session.clear()
                flash(
                    "Backup restored. Sign in again. Uploaded files are separate: restore their directory snapshot too.",
                    "success",
                )
                return redirect(url_for("auth.login"))
            elif action == "delete_backup":
                backup = get_object(Backup, int(request.form.get("id", "0")))
                path = (
                    Path(current_app.config["BACKUP_DIR"]) / backup.filename
                ).resolve()
                root = Path(current_app.config["BACKUP_DIR"]).resolve()
                if not path.is_relative_to(root):
                    abort(400)
                path.unlink(missing_ok=True)
                db.session.delete(backup)
                db.session.commit()
                flash("Backup removed.", "success")
            else:
                abort(400)
            return redirect(request.path)
        except (ValueError, IntegrityError) as ex:
            db.session.rollback()
            flash(
                str(ex)
                if isinstance(ex, ValueError)
                else "The restore was rolled back because the backup violates data constraints.",
                "error",
            )
    records = list(
        db.session.scalars(select(Backup).order_by(Backup.created_at.desc()))
    )
    logs = list(
        db.session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(50))
    )
    import platform

    checks = [
        ("Python", platform.python_version()),
        ("Database", db.engine.dialect.name),
        (
            "Upload limit",
            str(current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)) + " MB",
        ),
        (
            "SMTP",
            "Configured"
            if os.getenv("SMTP_HOST")
            else "Not configured; approval does not require email",
        ),
        ("Automatic backups", "Piggyback on admin GET requests; CLI also available"),
        ("Upload folders", str(len(image_checks())) + " checks"),
        ("Private files", "Instance data is never served as static files"),
    ]
    return render_template("database.html", backups=records, checks=checks, logs=logs)


@web.get("/admin/backups/<int:id>")
@admin_required
def backup_download(id):
    obj = get_object(Backup, id)
    root = Path(current_app.config["BACKUP_DIR"]).resolve()
    path = (root / obj.filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=obj.filename,
        mimetype="application/json",
    )


@web.route("/admin/migrations", methods=["GET", "POST"])
@admin_required
def migrations():
    if request.method == "POST":
        if not password_ok(g.user.password, request.form.get("current_password", "")):
            flash("Enter your current administrator password.", "error")
        else:
            from .commands import upgrade_database
            from .maintenance import create_backup

            create_backup("before-migration")
            upgrade_database()
            audit("migrations_apply")
            db.session.commit()
            flash("Bundled Python migrations applied. Re-running is safe.", "success")
        return redirect(request.path)
    records = list(db.session.scalars(select(Migration).order_by(Migration.version)))
    return render_template("migrations.html", migrations=records)


def python_guide():
    guide = copy.deepcopy(DEFAULTS["guide"])
    overrides = {
        "Page Studio": [
            "Choose Hero or a landing section using the section tabs. Update its copy, layout, visibility, colours, animation and limits. Upload foreground/background images; configure individual hero buttons, text offsets, image size and shadows. Blank colours follow the active theme. Save, then use Preview website."
        ],
        "Database": [
            "Review the system checks, private upload/backups paths and recent audit log. Enter your password to create a portable JSON backup, then download it off-server.",
            "Configure automatic backups on administrator page loads or call the backup CLI from your own scheduler.",
            "Before restore, take a backup of both the database and the uploads directory. Select a Python JSON backup, enter your password and type RESTORE. A pre-restore backup is created automatically. All sessions are invalidated and you sign in again. PHP SQL files are not accepted here.",
        ],
        "Migrations": [
            "Back up first. Apply the bundled Python/Alembic migrations using this page and your administrator password, or run python -m flask --app wsgi upgrade-db. Applied revisions are skipped. Never run the PHP SQL migrations on a Python database."
        ],
        "Company Settings": [
            "Update company identity, logo/favicon, currency, timezone and header/footer colours. Require administrator 2FA when ready. Save all settings.",
            "Use Image Delivery Check to verify writable upload folders and referenced logo files. Python serves uploads directly; Apache .htaccess repair is not used.",
        ],
        "Theme Studio": [
            "Choose one of 14 built-in themes and press Activate. Edit the palette to customise an active theme. Built-ins are re-added if missing without overwriting existing palette edits."
        ],
        "Flowchart": [
            "Read the student and administrator journeys. Download each SVG or print one/both with the portrait A4 preview."
        ],
        "How To": [
            "Search menu names and glossary terms. Expand the matching guide, or print the complete guide and glossary."
        ],
        "About Page": [
            "Update the title, summary, description, image, captions and call-to-action links. Toggle sections; edit pillar/audience/term text using the JSON arrays. Save then preview About."
        ],
        "User Accounts": [
            "Create accounts or edit names, email, student details, role and status. Enter your own administrator password for each account change.",
            "Disabling an account preserves its financial records. The last active administrator cannot be disabled or demoted.",
        ],
    }
    for side, group in guide["menus"].items():
        for item in group["items"]:
            item["url"] = safe_url(item.get("url", ""))
            if item["label"] in overrides:
                item["steps"] = overrides[item["label"]]
            if item["label"] == "Database":
                item["what"] = (
                    "Portable backups, validated atomic restore, automatic-backup scheduling, hosting checks and an audit trail."
                )
            if item["label"] == "Migrations":
                item["what"] = (
                    "Versioned Python database updates managed by Alembic, independent of the legacy PHP migration history."
                )
    excluded = [
        "Free hosting (InfinityFree)",
        "Hosting account",
        "Upload guard (uploads/.htaccess)",
        ".htaccess",
        "Reserved folder or file name",
        "Cron key",
    ]
    for group, terms in guide["glossary"].items():
        for term in list(terms):
            if term in excluded or any(
                w in terms[term]
                for w in [
                    "php_value",
                    "php_flag",
                    "phpMyAdmin",
                    "install.php",
                    "schema_migrations",
                    "mail()",
                    "/migrations",
                    "php.ini",
                ]
            ):
                del terms[term]
    guide["glossary"]["Python deployment"] = {
        "Python version": "Requires Python 3.12–3.13; this build is verified on Python 3.13.16. Pin the Python minor version on your server.",
        "Flask": "The Python web application framework handling routes, sessions, Jinja templates and requests. No PHP interpreter is needed.",
        "SQLAlchemy": "The data layer supporting SQLite, PostgreSQL and MySQL through DATABASE_URL.",
        "Alembic migration": "A versioned Python schema update; bundled revisions run once through upgrade-db or System → Migrations.",
        "Portable JSON backup": "The Python backup format: UTF-8 data, dates and exact decimal strings. It is private and includes sensitive user/authentication data. Uploaded files must be copied separately.",
        "SECRET_KEY": "A long random secret for signed sessions and encrypted TOTP secrets. Keep it private, stable across restarts, and backed up outside the ZIP.",
        "Persistent volume": "Storage that survives deployments. Keep instance uploads, backups and SQLite data here; an ephemeral platform disk will lose files.",
        "Production server": "Gunicorn on Linux, or Waitress for local/Windows deployments. Use HTTPS behind a trusted reverse proxy; Flask development mode is not a production server.",
        "Hosting compatibility": "The Python edition needs Python/WSGI or Docker hosting. Do not upload it to a PHP-only shared-hosting account.",
    }
    return guide


@web.get("/admin/howto")
@admin_required
def howto():
    guide = python_guide()
    return render_template(
        "guide_print.html" if request.args.get("do") == "print" else "howto.html",
        title="How To · System Guide",
        guide=guide,
        orientation="portrait",
    )


@web.get("/admin/flowchart")
@admin_required
def flowchart():
    from markupsafe import Markup

    charts = []
    for role, title in [
        ("student", "Student journey"),
        ("admin", "Administrator operations"),
    ]:
        if (
            request.args.get("do") == "print"
            and request.args.get("role") in ("student", "admin")
            and request.args["role"] != role
        ):
            continue
        file = Path(current_app.static_folder) / "img" / f"flowchart-{role}.svg"
        charts.append(dict(role=role, title=title, svg=Markup(file.read_text(encoding="utf-8"))))
    return render_template(
        "flowchart_print.html"
        if request.args.get("do") == "print"
        else "flowchart.html",
        title="System Flowcharts",
        charts=charts,
    )


@web.get("/healthz")
def health():
    db.session.execute(__import__("sqlalchemy").text("SELECT 1"))
    return {"status": "ok"}, 200
