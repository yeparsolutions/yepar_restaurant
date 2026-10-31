"""PIN de supervisor (usuarios) y quién autorizó el descuento (pedidos).

Revisión: 0005
Anterior: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('pedidos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('descuento_autorizado_por_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_pedidos_descuento_autorizado_por', 'usuarios', ['descuento_autorizado_por_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pin_hash', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('pin_fallos', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('pin_bloqueado_hasta', sa.DateTime(timezone=True), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_column('pin_bloqueado_hasta')
        batch_op.drop_column('pin_fallos')
        batch_op.drop_column('pin_hash')

    with op.batch_alter_table('pedidos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pedidos_descuento_autorizado_por', type_='foreignkey')
        batch_op.drop_column('descuento_autorizado_por_id')

