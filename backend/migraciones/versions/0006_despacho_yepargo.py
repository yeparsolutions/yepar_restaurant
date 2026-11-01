"""Delivery con Yepar Go: conexión por restaurante y despachos de cuentas.

Revisión: 0006
Anterior: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('integraciones_despacho',
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('api_key_cifrada', sa.Text(), nullable=False),
    sa.Column('activo', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('direccion_retiro', sa.String(length=300), nullable=True),
    sa.Column('centro_retiro_id', sa.String(length=40), nullable=True),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('empresa_id')
    )
    op.create_table('despachos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('sucursal_id', sa.Integer(), nullable=False),
    sa.Column('pedido_id', sa.String(length=36), nullable=False),
    sa.Column('estado', sa.Enum('pendiente', 'creado', 'rechazado', name='estadodespacho', native_enum=False, length=30), nullable=False),
    sa.Column('destinatario', sa.String(length=150), nullable=False),
    sa.Column('telefono', sa.String(length=40), nullable=True),
    sa.Column('email', sa.String(length=150), nullable=True),
    sa.Column('direccion', sa.String(length=300), nullable=False),
    sa.Column('ciudad', sa.String(length=100), nullable=True),
    sa.Column('region', sa.String(length=100), nullable=True),
    sa.Column('latitud', sa.Numeric(precision=10, scale=7), nullable=True),
    sa.Column('longitud', sa.Numeric(precision=10, scale=7), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('go_orden_id', sa.String(length=40), nullable=True),
    sa.Column('go_numero', sa.String(length=40), nullable=True),
    sa.Column('estado_go', sa.String(length=20), nullable=True),
    sa.Column('seguimiento_url', sa.String(length=500), nullable=True),
    sa.Column('intentos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('ultimo_error', sa.Text(), nullable=True),
    sa.Column('creado_por_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['creado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.ForeignKeyConstraint(['sucursal_id'], ['sucursales.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('pedido_id', name='uq_despacho_pedido')
    )
    with op.batch_alter_table('despachos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_despachos_empresa_id'), ['empresa_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_despachos_sucursal_id'), ['sucursal_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('despachos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_despachos_sucursal_id'))
        batch_op.drop_index(batch_op.f('ix_despachos_empresa_id'))

    op.drop_table('despachos')
    op.drop_table('integraciones_despacho')
