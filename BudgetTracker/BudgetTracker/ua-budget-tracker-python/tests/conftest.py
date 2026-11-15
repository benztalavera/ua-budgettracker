import pytest
from tracker import create_app
from tracker.models import db, User, AuthState, Migration, utcnow
from tracker.auth import new_password
from tracker.services import seed_defaults


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-long-enough-for-encrypted-totp-secrets",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "test.sqlite"),
            "DATA_DIR": str(tmp_path),
            "UPLOAD_DIR": str(tmp_path / "uploads"),
            "BACKUP_DIR": str(tmp_path / "backups"),
            "WTF_CSRF_ENABLED": False,
            "_SCHEMA_READY": True,
        }
    )
    with app.app_context():
        db.create_all()
        seed_defaults()
        db.session.add(Migration(version=1, name="Test schema"))
        for id, role, email in [
            (1, "admin", "admin@test.edu"),
            (2, "student", "student@test.edu"),
            (3, "student", "other@test.edu"),
        ]:
            u = User(
                id=id,
                name=role.title() + str(id),
                email=email,
                password=new_password("TestPass123!"),
                role=role,
                status="active",
                student_number=("S-00" + str(id)) if role == "student" else None,
                onboarded_at=utcnow(),
            )
            db.session.add(u)
            db.session.flush()
            db.session.add(AuthState(user_id=id))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email="student@test.edu", password="TestPass123!"):
    return client.post("/login", data={"email": email, "password": password})
