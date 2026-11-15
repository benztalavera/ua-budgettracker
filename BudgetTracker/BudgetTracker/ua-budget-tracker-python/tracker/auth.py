"""Authentication, approval, database-backed throttling and one-use TOTP."""

import base64, hashlib, re, secrets, time
from datetime import timedelta
from functools import wraps
import bcrypt, pyotp
from cryptography.fernet import Fernet, InvalidToken
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from .models import db, User, AuthState, AuthAttempt, utcnow
from .services import text, parse_date, save_image, setting, audit, LEVELS

auth = Blueprint("auth", __name__)


def cipher():
    return Fernet(
        base64.urlsafe_b64encode(
            hashlib.sha256(current_app.config["SECRET_KEY"].encode()).digest()
        )
    )


def encrypt(v):
    return "enc:" + cipher().encrypt(v.encode()).decode() if v else None


def decrypt(v):
    if not v:
        return ""
    if not v.startswith("enc:"):
        return v  # Transitional PHP import, encrypted on import/save.
    try:
        return cipher().decrypt(v[4:].encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def password_ok(stored, raw):
    try:
        if stored.startswith(("$2y$", "$2b$", "$2a$")):
            return bcrypt.checkpw(
                raw.encode()[:72], stored.replace("$2y$", "$2b$", 1).encode()
            )
        return check_password_hash(stored, raw)
    except (ValueError, TypeError):
        return False


def new_password(raw):
    if (
        len(raw) < 8
        or len(raw) > 256
        or not re.search(r"[A-Za-z]", raw)
        or not re.search(r"\d", raw)
    ):
        raise ValueError(
            "Password must have 8–256 characters with both letters and numbers."
        )
    return generate_password_hash(raw, method="scrypt")


def state_for(uid):
    state = db.session.get(AuthState, uid)
    if state is None:
        state = AuthState(user_id=uid, version=1, last_otp_step=-1)
        db.session.add(state)
        db.session.flush()
    return state


def bump_auth(user):
    state_for(user.id).version += 1


def login_required(fn):
    @wraps(fn)
    def guarded(*a, **kw):
        if not g.user:
            return redirect(url_for("auth.login"))
        return fn(*a, **kw)

    return guarded


def admin_required(fn):
    @wraps(fn)
    @login_required
    def guarded(*a, **kw):
        if g.user.role != "admin":
            abort(403)
        if setting("force_2fa_admin") == "1" and not g.user.two_fa_enabled:
            return redirect(url_for("auth.profile"))
        return fn(*a, **kw)

    return guarded


def throttle_bucket(stage, identity=""):
    return hashlib.sha256(
        f"{stage}:{request.remote_addr}:{identity.lower()}".encode()
    ).hexdigest()


def throttled(bucket):
    since = utcnow() - timedelta(minutes=15)
    return (
        db.session.scalar(
            select(func.count())
            .select_from(AuthAttempt)
            .where(AuthAttempt.bucket == bucket, AuthAttempt.created_at >= since)
        )
        >= 5
    )


def fail_attempt(bucket):
    db.session.add(AuthAttempt(bucket=bucket))
    db.session.commit()


def consume_otp(user, code, secret=None):
    secret = secret or decrypt(user.two_fa_secret)
    if not secret or not re.fullmatch(r"\d{6}", code):
        return False
    totp = pyotp.TOTP(secret)
    step = int(time.time()) // 30
    matched = None
    for delta in (-1, 0, 1):
        if secrets.compare_digest(totp.at((step + delta) * 30), code):
            matched = step + delta
            break
    if matched is None:
        return False
    state_for(user.id)
    result = db.session.execute(
        update(AuthState)
        .where(AuthState.user_id == user.id, AuthState.last_otp_step < matched)
        .values(last_otp_step=matched)
    )
    db.session.commit()
    return result.rowcount == 1


def complete(user):
    state = state_for(user.id)
    session.clear()
    session["uid"] = user.id
    session["auth_version"] = state.version
    session["epoch"] = setting("session_epoch")
    user.last_login = utcnow()
    audit("login", "Successful sign-in", user.id)
    db.session.commit()
    if (
        user.role == "admin"
        and setting("force_2fa_admin") == "1"
        and not user.two_fa_enabled
    ):
        return url_for("auth.profile")
    if user.role == "student" and not user.onboarded_at:
        return url_for("web.onboarding")
    return url_for("web.admin_dashboard" if user.role == "admin" else "web.dashboard")


@auth.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(
            url_for(
                "web.admin_dashboard" if g.user.role == "admin" else "web.dashboard"
            )
        )
    if request.method == "POST":
        email = text("email", 190).lower()
        bucket = throttle_bucket("password", email)
        if throttled(bucket):
            flash("Too many attempts. Wait 15 minutes before trying again.", "error")
            return render_template("login.html"), 429
        user = db.session.scalar(select(User).where(func.lower(User.email) == email))
        raw = request.form.get("password", "")
        if not user or not password_ok(user.password, raw):
            fail_attempt(bucket)
            flash("Invalid email or password.", "error")
        elif user.status != "active":
            fail_attempt(bucket)
            flash(
                "Registration is pending approval."
                if user.status == "pending"
                else "This account is not approved or is disabled. Contact the office.",
                "warning",
            )
        else:
            if user.password.startswith("$2"):
                user.password = generate_password_hash(raw)
                db.session.commit()
            if user.two_fa_enabled:
                session.clear()
                session["pending_2fa"] = user.id
                session["pending_at"] = int(time.time())
                session["pending_version"] = state_for(user.id).version
                db.session.commit()
                return redirect(url_for("auth.otp"))
            return redirect(complete(user))
    return render_template("login.html")


@auth.route("/login/otp", methods=["GET", "POST"])
def otp():
    uid = session.get("pending_2fa")
    user = db.session.get(User, uid) if uid else None
    if (
        not user
        or time.time() - session.get("pending_at", 0) > 300
        or user.status != "active"
        or not user.two_fa_enabled
        or state_for(user.id).version != session.get("pending_version")
    ):
        session.clear()
        flash("Verification session expired. Sign in again.", "warning")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        bucket = throttle_bucket("otp", str(user.id))
        if throttled(bucket):
            flash("Too many code attempts. Try again in 15 minutes.", "error")
            return render_template("otp.html"), 429
        if consume_otp(user, text("otp_code", 6)):
            return redirect(complete(user))
        fail_attempt(bucket)
        flash("Invalid or already-used code. Use a new authenticator code.", "error")
    return render_template("otp.html")


@auth.post("/logout")
def logout():
    session.clear()
    flash("You have signed out.", "success")
    return redirect(url_for("auth.login"))


@auth.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("web.dashboard"))
    if request.method == "POST":
        try:
            bucket = throttle_bucket("register")
            if throttled(bucket):
                abort(429)
            name = text("name", 120, True)
            email = text("email", 190, True).lower()
            number = text("student_number", 40, True)
            grade = text("grade_level", 40, True)
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                raise ValueError("Enter a valid email address.")
            if grade not in LEVELS:
                raise ValueError("Choose your grade / year level.")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/ \-]{2,39}", number):
                raise ValueError(
                    "Student number must be 3–40 letters, digits, spaces, / or -."
                )
            if db.session.scalar(
                select(User.id).where(
                    (User.email == email) | (User.student_number == number)
                )
            ):
                raise ValueError("That email or student number is already registered.")
            raw = request.form.get("password", "")
            if raw != request.form.get("password2"):
                raise ValueError("Passwords do not match.")
            if request.form.get("agree") != "1":
                raise ValueError("Confirm that the registration details are correct.")
            birth = parse_date(request.form.get("birth_date"), False)
            if birth and birth > date_today():
                raise ValueError("Birth date cannot be in the future.")
            user = User(
                name=name,
                email=email,
                student_number=number,
                grade_level=grade,
                password=new_password(raw),
                status="pending",
                role="student",
                birth_date=birth,
                course=text("course", 120),
                section=text("section", 60),
                contact_number=text("contact_number", 40),
                gender=text("gender", 20),
                address=text("address", 190),
            )
            avatar = save_image(request.files.get("avatar"), "avatars")
            user.avatar = avatar
            db.session.add(user)
            db.session.flush()
            audit("register_pending", email, user.id)
            db.session.add(AuthAttempt(bucket=bucket))
            db.session.commit()
            return render_template("registered.html")
        except (ValueError, IntegrityError) as ex:
            db.session.rollback()
            flash(
                str(ex)
                if isinstance(ex, ValueError)
                else "Email or student number is already registered.",
                "error",
            )
    return render_template("register.html", levels=LEVELS)


def date_today():
    from .services import today

    return today()


@auth.route("/user/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = g.user
    state = state_for(user.id)
    if request.method == "POST":
        try:
            action = request.form.get("action", "profile")
            if action == "profile":
                user.name = text("name", 120, True)
                user.contact_number = text("contact_number", 40)
                user.address = text("address", 190)
                user.course = text("course", 120)
                user.section = text("section", 60)
                user.gender = text("gender", 20)
                user.birth_date = parse_date(request.form.get("birth_date"), False)
                if user.birth_date and user.birth_date > date_today():
                    raise ValueError("Birth date cannot be in the future.")
                image = save_image(request.files.get("avatar"), "avatars")
                if image:
                    user.avatar = image
                if request.form.get("remove_avatar"):
                    user.avatar = None
            else:
                if not password_ok(
                    user.password, request.form.get("current_password", "")
                ):
                    raise ValueError("Your current password is incorrect.")
                if action == "password":
                    raw = request.form.get("password", "")
                    if raw != request.form.get("password2"):
                        raise ValueError("New passwords do not match.")
                    user.password = new_password(raw)
                    bump_auth(user)
                elif action == "begin_2fa":
                    state.enroll_secret = encrypt(pyotp.random_base32())
                elif action == "enable_2fa":
                    secret = decrypt(state.enroll_secret)
                    if not secret or not consume_otp(user, text("otp_code", 6), secret):
                        raise ValueError("Invalid or already-used authenticator code.")
                    user.two_fa_secret = encrypt(secret)
                    user.two_fa_enabled = True
                    state.enroll_secret = None
                    bump_auth(user)
                elif action == "disable_2fa":
                    if user.two_fa_enabled and not consume_otp(
                        user, text("otp_code", 6)
                    ):
                        raise ValueError("Enter a fresh authenticator code.")
                    if user.role == "admin" and setting("force_2fa_admin") == "1":
                        raise ValueError(
                            "Administrator policy requires 2FA; it cannot be disabled."
                        )
                    user.two_fa_enabled = False
                    user.two_fa_secret = None
                    state.enroll_secret = None
                    state.last_otp_step = -1
                    bump_auth(user)
                else:
                    abort(400)
            audit("profile_" + action)
            db.session.commit()
            session["auth_version"] = state.version
            flash("Profile and security settings saved.", "success")
            return redirect(url_for("auth.profile"))
        except (ValueError, IntegrityError) as ex:
            db.session.rollback()
            flash(
                str(ex) if isinstance(ex, ValueError) else "Unable to save profile.",
                "error",
            )
    secret = decrypt(state.enroll_secret)
    uri = (
        pyotp.TOTP(secret).provisioning_uri(
            user.email, issuer_name=setting("site_name")
        )
        if secret
        else ""
    )
    return render_template("profile.html", enroll_secret=secret, enroll_uri=uri)
