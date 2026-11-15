import io, json, time
from datetime import date, timedelta
from decimal import Decimal
import pytest, pyotp
from PIL import Image
from sqlalchemy import select, func
from tracker.models import *
from tracker.auth import encrypt, consume_otp, password_ok, state_for
from tracker.services import (
    period_window,
    evaluate,
    snapshot,
    today,
    setting,
    set_setting,
    save_image,
    csv_bytes,
)
from tracker.maintenance import (
    snapshot_data,
    restore_payload,
    create_backup,
    validate_payload,
)
from conftest import login

ADMIN_PAGES = [
    "/admin",
    "/admin/landing",
    "/admin/landing?section=events",
    "/admin/events",
    "/admin/galleries",
    "/admin/videos",
    "/admin/advertisements",
    "/admin/map",
    "/admin/about",
    "/admin/categories",
    "/admin/reports",
    "/admin/users",
    "/admin/registrations",
    "/admin/registrations?tab=history",
    "/admin/monitor",
    "/admin/monitor?student=2",
    "/admin/settings",
    "/admin/themes",
    "/admin/database",
    "/admin/migrations",
    "/admin/howto",
    "/admin/flowchart",
]
STUDENT_PAGES = [
    "/user/dashboard",
    "/user/incomes",
    "/user/expenses",
    "/user/budgets",
    "/user/behavior",
    "/user/reports",
    "/user/onboarding",
    "/user/profile",
]


@pytest.mark.parametrize("path", ["/", "/about", "/login", "/register"])
def test_public_pages(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_admin_menu(client, path):
    login(client, "admin@test.edu")
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", STUDENT_PAGES)
def test_student_menu(client, path):
    login(client)
    assert client.get(path).status_code == 200


@pytest.mark.parametrize(
    "path", [p for p in ADMIN_PAGES if "/admin" in p and "section=" not in p]
)
def test_students_cannot_use_admin(client, path):
    login(client)
    assert client.get(path).status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/admin/events",
        "/admin/categories",
        "/admin/registrations",
        "/admin/users",
        "/admin/monitor",
        "/admin/reports",
        "/admin/howto",
        "/admin/flowchart",
        "/user/budgets",
        "/user/incomes",
        "/user/expenses",
        "/user/behavior",
        "/user/reports",
    ],
)
def test_print_routes(client, path):
    login(client, "admin@test.edu" if path.startswith("/admin") else "student@test.edu")
    r = client.get(path + "?do=print")
    assert r.status_code == 200
    assert b"Print / Save as PDF" in r.data and b"Close preview" in r.data


@pytest.mark.parametrize(
    "path",
    [
        "/admin/events.php",
        "/admin/categories.php",
        "/admin/settings.php",
        "/user/incomes.php",
        "/index.php",
        "/about.php",
    ],
)
def test_legacy_bookmarks(client, path):
    login(client, "admin@test.edu")
    r = client.get(path)
    assert r.status_code == 308


def test_csrf_required(app):
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    assert (
        c.post(
            "/login", data={"email": "admin@test.edu", "password": "TestPass123!"}
        ).status_code
        == 400
    )
    assert c.post("/logout").status_code == 400


def test_pending_approval_onboarding(client, app):
    r = client.post(
        "/register",
        data=dict(
            name="New Student",
            email="new@test.edu",
            student_number="REG-001",
            grade_level="Grade 12",
            password="Student123!",
            password2="Student123!",
            agree="1",
        ),
    )
    assert r.status_code == 200 and b"Registration received" in r.data
    assert (
        b"pending"
        in client.post(
            "/login", data={"email": "new@test.edu", "password": "Student123!"}
        ).data
    )
    login(client, "admin@test.edu")
    with app.app_context():
        uid = db.session.scalar(select(User.id).where(User.email == "new@test.edu"))
    assert (
        client.post(
            "/admin/registrations", data={"id": uid, "action": "approve"}
        ).status_code
        == 302
    )
    client.post("/logout")
    r = client.post("/login", data={"email": "new@test.edu", "password": "Student123!"})
    assert r.location.endswith("/user/onboarding")
    r = client.post(
        "/user/onboarding",
        data={
            "period_type": "weekly",
            "week_start": "today",
            "amount": "700",
            "alert_enabled": "1",
            "alert_threshold": "80",
        },
    )
    assert r.status_code == 302
    with app.app_context():
        b = db.session.scalar(select(Budget).where(Budget.user_id == uid))
        assert b.period_start == today() and b.period_end == today() + timedelta(days=6)


def test_registration_validation(client, app):
    data = dict(
        name="Name",
        email="student@test.edu",
        student_number="NEW-123",
        grade_level="Grade 12",
        password="Student123!",
        password2="Student123!",
        agree="1",
    )
    r = client.post("/register", data=data)
    assert b"already registered" in r.data
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(User)) == 3


def test_owner_isolation(client, app):
    login(client)
    client.post(
        "/user/expenses",
        data={
            "description": "Private lunch",
            "amount": "125.25",
            "expense_date": "2026-10-16",
        },
    )
    with app.app_context():
        id = db.session.scalar(select(Expense.id))
        assert db.session.get(Expense, id).amount == Decimal("125.25")
    client.post("/logout")
    login(client, "other@test.edu")
    assert client.get("/user/expenses?form=" + str(id)).status_code == 404
    assert (
        client.post("/user/expenses", data={"id": id, "action": "delete"}).status_code
        == 404
    )


def test_budget_calculation_and_overall_allowance(app):
    with app.app_context():
        ref = date(2026, 10, 16)
        start, end = period_window("weekly", ref, "today", date(2026, 10, 9))
        assert (start, end) == (date(2026, 10, 16), date(2026, 10, 22))
        assert period_window("weekly", ref, "mon")[0] == date(2026, 10, 12)
        b = Budget(
            user_id=2,
            amount=Decimal("1000"),
            period_type="monthly",
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31),
            week_start="today",
            alert_enabled=True,
            alert_threshold=80,
        )
        db.session.add(b)
        db.session.add(
            Expense(
                user_id=2, amount=Decimal("800"), expense_date=ref, description="Test"
            )
        )
        db.session.commit()
        ev = evaluate(b, ref)
        assert ev["state"] == "warn" and ev["remaining"] == Decimal("200")
        db.session.add(
            Expense(
                user_id=2, amount=Decimal("200"), expense_date=ref, description="Test 2"
            )
        )
        db.session.commit()
        assert evaluate(b, ref)["state"] == "over"
        assert snapshot(2, ref)["allowance"] == Decimal("1000") / 31


def test_totp_single_use(app, client):
    secret = pyotp.random_base32()
    with app.app_context():
        u = db.session.get(User, 2)
        u.two_fa_enabled = True
        u.two_fa_secret = encrypt(secret)
        db.session.commit()
    r = login(client)
    assert r.location.endswith("/login/otp")
    code = pyotp.TOTP(secret).now()
    assert client.post("/login/otp", data={"otp_code": code}).status_code == 302
    client.post("/logout")
    login(client)
    r = client.post("/login/otp", data={"otp_code": code})
    assert r.status_code == 200 and b"already-used" in r.data


def test_password_change_invalidates_other_sessions(client, app):
    a = client
    b = app.test_client()
    login(a)
    login(b)
    r = a.post(
        "/user/profile",
        data={
            "action": "password",
            "current_password": "TestPass123!",
            "password": "ChangedPass123!",
            "password2": "ChangedPass123!",
        },
    )
    assert r.status_code == 302
    assert b.get("/user/dashboard").status_code == 302


def test_login_throttling(client):
    for i in range(5):
        client.post("/login", data={"email": "student@test.edu", "password": "bad"})
    assert (
        client.post(
            "/login", data={"email": "student@test.edu", "password": "TestPass123!"}
        ).status_code
        == 429
    )


def test_image_verification_and_private_receipts(client, app):
    login(client)
    image = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(image, "PNG")
    image.seek(0)
    assert (
        client.post(
            "/user/expenses",
            data={
                "description": "With receipt",
                "amount": "100",
                "expense_date": "2026-10-16",
                "receipt_image": (image, "receipt.png"),
            },
            content_type="multipart/form-data",
        ).status_code
        == 302
    )
    with app.app_context():
        path = db.session.scalar(select(Expense.receipt_image))
        assert path.endswith(".jpg")
    assert client.get("/uploads/" + path).status_code == 200
    client.post("/logout")
    assert client.get("/uploads/" + path).status_code == 403
    login(client, "other@test.edu")
    assert client.get("/uploads/" + path).status_code == 403
    r = client.post(
        "/user/expenses",
        data={
            "description": "Bad image",
            "amount": "100",
            "expense_date": "2026-10-16",
            "receipt_image": (io.BytesIO(b"<?php bad ?>"), "fake.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert b"not a valid" in r.data


def test_theme_and_settings(client, app):
    login(client, "admin@test.edu")
    with app.app_context():
        theme = db.session.scalar(select(Theme).where(Theme.slug == "midnight-pro"))
        id = theme.id
    client.post("/admin/themes", data={"id": id, "action": "activate"})
    with app.app_context():
        assert setting("theme_slug") == "midnight-pro"
    assert b"--bg:#0f172a" in client.get("/admin").data


def test_backup_roundtrip_and_validation(app):
    with app.app_context():
        set_setting("currency_symbol", "₱")
        set_setting("company_address", "San Fernando — Pampanga")
        db.session.commit()
        payload = snapshot_data()
        record = create_backup()
        assert (
            __import__("pathlib").Path(app.config["BACKUP_DIR"]) / record.filename
        ).is_file()
        set_setting("currency_symbol", "USD")
        db.session.commit()
        restore_payload(payload)
        assert setting("currency_symbol") == "₱" and "—" in setting("company_address")
        malicious = dict(payload)
        malicious["tables"] = {**payload["tables"], "not_a_table": []}
        with pytest.raises(ValueError):
            validate_payload(malicious)
        assert db.session.scalar(select(func.count()).select_from(User)) == 3


def test_backup_requires_admin_password(client):
    login(client, "admin@test.edu")
    r = client.post(
        "/admin/database", data={"action": "backup", "current_password": "wrong"}
    )
    assert b"current administrator password" in r.data


def test_last_admin_cannot_be_disabled(client, app):
    login(client, "admin@test.edu")
    client.post(
        "/admin/users",
        data={"action": "delete", "id": "1", "_admin_password": "TestPass123!"},
    )
    with app.app_context():
        assert db.session.get(User, 1).status == "active"


def test_csv_formula_safety():
    assert b"'=HYPERLINK" in csv_bytes(["x"], [['=HYPERLINK("bad")']])


def test_private_files_not_served(client):
    for path in [
        "/.env",
        "/instance/.secret-key",
        "/tracker/models.py",
        "/backups/test.json",
        "/uploads/../.secret-key",
    ]:
        assert client.get(path).status_code in (404, 403)


def test_crud_and_form_actions(client, app):
    login(client, "admin@test.edu")
    assert (
        client.post(
            "/admin/events",
            data={
                "title": "A campus event",
                "event_date": "2026-12-01",
                "event_time": "14:00",
                "status": "published",
                "animation": "fade-up",
                "style": "rounded",
            },
        ).status_code
        == 302
    )
    assert b"A campus event" in client.get("/").data
    with app.app_context():
        id = db.session.scalar(select(Event.id))
    client.post("/admin/events", data={"id": id, "action": "delete"})
    with app.app_context():
        assert db.session.get(Event, id) is None


@pytest.mark.parametrize(
    "path,data",
    [
        (
            "/user/expenses",
            {"description": "Bad", "amount": "NaN", "expense_date": "2026-10-16"},
        ),
        (
            "/user/expenses",
            {"description": "Bad", "amount": "-1", "expense_date": "2026-10-16"},
        ),
        (
            "/user/incomes",
            {"source": "Bad", "amount": "1", "income_date": "not-a-date"},
        ),
        (
            "/user/budgets",
            {
                "amount": "100",
                "period_type": "custom",
                "period_start": "2026-10-16",
                "period_end": "2026-10-15",
            },
        ),
    ],
)
def test_invalid_financial_input(client, app, path, data):
    login(client)
    response = client.post(path, data=data)
    assert response.status_code in (200, 400)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Expense)) == 0
        assert db.session.scalar(select(func.count()).select_from(Income)) == 0
        assert db.session.scalar(select(func.count()).select_from(Budget)) == 0


def test_all_hero_controls_persist(client, app):
    from tracker.services import DEFAULTS, config

    login(client, "admin@test.edu")
    with app.app_context():
        data = {k: str(v) for k, v in DEFAULTS["landing"]["hero"].items()}
    data.update(
        hero_title="Custom title",
        hero_subtitle="Custom subtitle",
        hero_cta="Enter",
        hero_cta_link="/login",
        title_color="#123456",
        text_x="41",
        media_y="-27",
        shadow_strength="125",
        anim_bg="ken-burns",
        media_scale="110",
    )
    response = client.post("/admin/landing", data=data)
    assert response.status_code == 302
    with app.app_context():
        cfg = config("landing")["hero"]
        assert (
            cfg["text_x"] == 41
            and cfg["media_y"] == -27
            and cfg["shadow_strength"] == 125
            and cfg["anim_bg"] == "ken-burns"
        )
    html = client.get("/").data
    assert b"Custom title" in html and b"#123456" in html


def test_theme_font_editor(client, app):
    login(client, "admin@test.edu")
    with app.app_context():
        theme = db.session.scalar(select(Theme).limit(1))
        data = json.loads(theme.config_json)
        id = theme.id
    data.update(id=str(id), name="Edited theme", font_choice="serif")
    assert client.post("/admin/themes", data=data).status_code == 302
    client.post("/admin/themes", data={"id": id, "action": "activate"})
    assert b"--font:Georgia, serif" in client.get("/admin").data


def test_restore_rejects_missing_active_admin_before_writing(app):
    with app.app_context():
        payload = snapshot_data()
        payload["tables"]["users"] = []
        with pytest.raises(ValueError):
            restore_payload(payload)
        assert db.session.scalar(select(func.count()).select_from(User)) == 3


def test_setup_and_csrf_errors_work_before_schema(tmp_path):
    from tracker import create_app

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-setup-secret-123456789012345678901234",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "empty.sqlite"),
            "DATA_DIR": str(tmp_path),
            "UPLOAD_DIR": str(tmp_path / "uploads"),
            "BACKUP_DIR": str(tmp_path / "backups"),
        }
    )
    c = app.test_client()
    assert c.get("/").status_code == 503
    assert c.post("/login", data={"email": "bad"}).status_code == 400


@pytest.mark.parametrize(
    "kind,ref,expected",
    [
        ("daily", date(2026, 10, 16), (date(2026, 10, 16), date(2026, 10, 16))),
        ("monthly", date(2028, 2, 14), (date(2028, 2, 1), date(2028, 2, 29))),
        ("monthly", date(2026, 12, 31), (date(2026, 12, 1), date(2026, 12, 31))),
    ],
)
def test_calendar_boundaries(kind, ref, expected):
    assert period_window(kind, ref) == expected


@pytest.mark.parametrize(
    "encoded_path", ["%2e%2freceipts/", "avatars/%2e%2e/receipts/", "receipts//"]
)
def test_receipt_canonical_path_cannot_bypass_auth(client, app, encoded_path):
    from pathlib import Path

    with app.app_context():
        path = Path(app.config["UPLOAD_DIR"]) / "receipts" / "private.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), "blue").save(path, "JPEG")
        db.session.add(
            Expense(
                user_id=2,
                description="Private",
                amount=Decimal("1"),
                expense_date=date(2026, 10, 16),
                receipt_image="receipts/private.jpg",
            )
        )
        db.session.commit()
    response = client.get("/uploads/" + encoded_path + "private.jpg")
    assert response.status_code in (403, 404)
    login(client, "other@test.edu")
    assert client.get("/uploads/" + encoded_path + "private.jpg").status_code in (
        403,
        404,
    )
