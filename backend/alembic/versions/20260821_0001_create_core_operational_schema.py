"""create core operational schema

Revision ID: 20260821_0001
Revises:
Create Date: 2026-08-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260821_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("business_name", sa.String(length=255), nullable=False),
        sa.Column("business_type", sa.String(length=120), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("current_stock", sa.Integer(), nullable=False),
        sa.Column("reorder_level", sa.Integer(), nullable=False),
        sa.Column("supplier_lead_time_days", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("selling_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("current_stock >= 0", name="ck_products_current_stock_non_negative"),
        sa.CheckConstraint("reorder_level >= 0", name="ck_products_reorder_level_non_negative"),
        sa.CheckConstraint("supplier_lead_time_days >= 0", name="ck_products_supplier_lead_time_non_negative"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_products_unit_cost_non_negative"),
        sa.CheckConstraint("selling_price >= 0", name="ck_products_selling_price_non_negative"),
    )
    op.create_index("ix_products_merchant_id", "products", ["merchant_id"])
    op.create_index("ix_products_created_at", "products", ["created_at"])

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("movement_type", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("movement_type in ('purchase', 'sale', 'adjustment', 'return')", name="ck_stock_movements_type"),
        sa.CheckConstraint("source in ('manual', 'invoice', 'voice', 'billing_data', 'demo')", name="ck_stock_movements_source"),
        sa.CheckConstraint("quantity > 0", name="ck_stock_movements_quantity_positive"),
    )
    op.create_index("ix_stock_movements_merchant_id", "stock_movements", ["merchant_id"])
    op.create_index("ix_stock_movements_product_id", "stock_movements", ["product_id"])
    op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"])

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_reference", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_customers_merchant_id", "customers", ["merchant_id"])
    op.create_index("ix_customers_created_at", "customers", ["created_at"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("extraction_status", sa.String(length=40), nullable=False),
        sa.Column("extracted_data", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("extraction_status in ('pending', 'processing', 'completed', 'failed')", name="ck_invoices_extraction_status"),
    )
    op.create_index("ix_invoices_merchant_id", "invoices", ["merchant_id"])
    op.create_index("ix_invoices_created_at", "invoices", ["created_at"])

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommendation_type", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("supporting_metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("priority between 1 and 5", name="ck_recommendations_priority_range"),
        sa.CheckConstraint("status in ('open', 'accepted', 'dismissed', 'completed')", name="ck_recommendations_status"),
    )
    op.create_index("ix_recommendations_merchant_id", "recommendations", ["merchant_id"])
    op.create_index("ix_recommendations_created_at", "recommendations", ["created_at"])

    op.create_table(
        "ai_interactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("supporting_metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_interactions_merchant_id", "ai_interactions", ["merchant_id"])
    op.create_index("ix_ai_interactions_created_at", "ai_interactions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_interactions_created_at", table_name="ai_interactions")
    op.drop_index("ix_ai_interactions_merchant_id", table_name="ai_interactions")
    op.drop_table("ai_interactions")
    op.drop_index("ix_recommendations_created_at", table_name="recommendations")
    op.drop_index("ix_recommendations_merchant_id", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_invoices_created_at", table_name="invoices")
    op.drop_index("ix_invoices_merchant_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_customers_created_at", table_name="customers")
    op.drop_index("ix_customers_merchant_id", table_name="customers")
    op.drop_table("customers")
    op.drop_index("ix_stock_movements_created_at", table_name="stock_movements")
    op.drop_index("ix_stock_movements_product_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_merchant_id", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index("ix_products_created_at", table_name="products")
    op.drop_index("ix_products_merchant_id", table_name="products")
    op.drop_table("products")
    op.drop_table("merchants")
