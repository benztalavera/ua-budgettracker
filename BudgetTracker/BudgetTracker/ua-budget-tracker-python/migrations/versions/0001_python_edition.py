"""Initial Python-edition schema, separate from PHP's migration history."""

from alembic import op
from tracker.models import db, Migration

revision = "0001_python"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    db.metadata.create_all(bind=connection)
    connection.execute(
        Migration.__table__.insert().values(version=1, name="Initial Python edition")
    )


def downgrade():
    raise RuntimeError(
        "Automatic destructive downgrade is disabled. Restore a verified backup into a separate database instead."
    )
