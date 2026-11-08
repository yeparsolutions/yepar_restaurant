"""Devoluciones de dinero al cliente (reembolsos).

Revisión: 0008
Anterior: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'devoluciones',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('sucursal_id', sa.Integer(), nullable=False),
        sa.Column('pedido_id', sa.String(length=36), nullable=False),
        sa.Column('medio', sa.Enum('efectivo', 'tarjeta', 'transferencia', name='mediopago', native_enum=False, length=30), nullable=False),
        sa.Column('monto', sa.Numeric(16, 2), nullable=False),
        sa.Column('motivo', sa.String(length=200), nullable=False),
        sa.Column('numero_operacion', sa.String(length=60), nullable=True),
        sa.Column('terminal_id', sa.Integer(), nullable=True),
        sa.Column('turno_id', sa.Integer(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('autorizado_por_id', sa.Integer(), nullable=True),
        sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('monto > 0', name='ck_devolucion_monto_positivo'),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sucursal_id'], ['sucursales.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id']),
        sa.ForeignKeyConstraint(['terminal_id'], ['terminales_pago.id']),
        sa.ForeignKeyConstraint(['turno_id'], ['turnos_caja.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['autorizado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_devolucion_pedido', 'devoluciones', ['pedido_id'])
    for col in ('empresa_id', 'sucursal_id', 'terminal_id', 'turno_id'):
        op.create_index(f'ix_devoluciones_{col}', 'devoluciones', [col])


def downgrade() -> None:
    op.drop_table('devoluciones')
