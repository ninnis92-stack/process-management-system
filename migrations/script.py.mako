<%!
from alembic import op
%>
"""Generic Alembic script template placeholder.

This ***REMOVED***le exists as a minimal template for generated revisions.
"""

revision = '${up_revision}'
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

def upgrade():
    pass


def downgrade():
    pass
