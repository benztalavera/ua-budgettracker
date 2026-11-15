from alembic import context
from tracker.models import db

config = context.config
with db.engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=db.metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
