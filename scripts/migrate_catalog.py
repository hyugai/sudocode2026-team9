import os
import json
import argparse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, Integer, Numeric, Boolean, Date, DateTime, ForeignKey, CheckConstraint, Index, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.dialects.postgresql import JSONB

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "catalog"

ORDER_COLUMNS = {
    "qty": "INTEGER NOT NULL DEFAULT 1",
    "promo_code": "VARCHAR(50)",
    "payment": "VARCHAR(50) NOT NULL DEFAULT 'COD'",
    "address": "TEXT",
    "exchange_count": "INTEGER NOT NULL DEFAULT 0",
    "updated_at": "TIMESTAMP WITHOUT TIME ZONE",
}

Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'
    sku = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100), index=True)
    brand = Column(String(100), index=True)
    list_price_vnd = Column(Numeric(15, 2))
    stock = Column(Integer, default=0)
    is_discontinued = Column(Boolean, default=False, index=True)
    successor_sku = Column(String(50))
    attributes = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)

    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")

class ProductVariant(Base):
    __tablename__ = 'product_variants'
    variant_sku = Column(String(50), primary_key=True)
    product_sku = Column(String(50), ForeignKey('products.sku', ondelete="CASCADE"), nullable=False, index=True)
    size = Column(String(20))
    color = Column(String(50))
    price_delta_vnd = Column(Numeric(15, 2), default=0)
    stock = Column(Integer, default=0)
    
    product = relationship("Product", back_populates="variants")

class Promotion(Base):
    __tablename__ = 'promotions'
    promo_code = Column(String(50), primary_key=True)
    name = Column(String(255))
    type = Column(String(50))
    discount_vnd = Column(Numeric(15, 2), default=0)
    discount_percent = Column(Integer, default=0)
    gift_sku = Column(String(50))
    min_order_vnd = Column(Numeric(15, 2), default=0)
    start_date = Column(Date)
    end_date = Column(Date)
    stackable = Column(Boolean, default=False)
    applies_to = Column(JSONB, nullable=False)
    conditions = Column(JSONB)

Index('idx_promotions_date', Promotion.start_date, Promotion.end_date)

class InventoryEvent(Base):
    __tablename__ = 'inventory_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(50), nullable=False)
    sku_type = Column(String(20), nullable=False)
    event_date = Column(Date, nullable=False)
    qty = Column(Integer, nullable=False)
    note = Column(String)

    __table_args__ = (
        CheckConstraint(sku_type.in_(['product', 'variant']), name='check_sku_type'),
        Index('idx_inventory_sku_date', 'sku', 'event_date') 
    )

class Customer(Base):
    __tablename__ = 'customers'
    customer_id = Column(String(50), primary_key=True)
    name = Column(String(100))
    honorific = Column(String(20))
    phone = Column(String(20), nullable=False, index=True)
    zalo_id = Column(String(100))
    fb_id = Column(String(100))
    region = Column(String(50))
    shared_phone_with = Column(String(50))
    attributes = Column(JSONB)
    
    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan")

class Order(Base):
    __tablename__ = 'orders'
    order_id = Column(String(50), primary_key=True)
    customer_id = Column(String(50), ForeignKey('customers.customer_id', ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(50))
    qty = Column(Integer, nullable=False, default=1)
    price_vnd = Column(Numeric(15, 2))
    promo_code = Column(String(50))
    payment = Column(String(50), nullable=False, default="COD")
    address = Column(String)
    order_date = Column(Date)
    status = Column(String(50))
    tracking = Column(String(100))
    exchange_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    customer = relationship("Customer", back_populates="orders")


def insert_data(session):
    print("1. Đọc dữ liệu từ file...")
    with open(os.path.join(CATALOG_DIR, "products.json"), "r", encoding="utf-8") as f:
        products_data = json.load(f).get("products", [])
    with open(os.path.join(CATALOG_DIR, "promotions.json"), "r", encoding="utf-8") as f:
        promotions_data = json.load(f).get("promotions", [])
    with open(os.path.join(CATALOG_DIR, "inventory_timeline.json"), "r", encoding="utf-8") as f:
        inventory_data = json.load(f).get("events", [])
    with open(os.path.join(CATALOG_DIR, "crm_seed.json"), "r", encoding="utf-8") as f:
        crm_data = json.load(f).get("customers", [])

    print("2. Đang insert products and variants...")
    variant_skus = set()
    for p in products_data:
        attributes = p.get("attributes", {})
        is_discontinued = attributes.pop("discontinued", False)
        successor_sku = attributes.pop("successor_sku", None)
        
        product_obj = Product(
            sku=p.get("sku"),
            name=p.get("name"),
            category=p.get("category"),
            brand=p.get("brand"),
            list_price_vnd=p.get("list_price_vnd"),
            stock=p.get("stock", 0),
            is_discontinued=is_discontinued,
            successor_sku=successor_sku,
            attributes=attributes if attributes else None
        )
        
        for v in p.get("variants", []):
            variant_skus.add(v.get("variant_sku"))
            variant_obj = ProductVariant(
                variant_sku=v.get("variant_sku"),
                size=str(v.get("size")) if v.get("size") else None,
                color=v.get("color"),
                price_delta_vnd=v.get("price_delta_vnd", 0),
                stock=v.get("stock", 0)
            )
            product_obj.variants.append(variant_obj)
        session.add(product_obj)

    print("3. Đang insert promotions...")
    for p in promotions_data:
        promo_obj = Promotion(
            promo_code=p.get("promo_code"),
            name=p.get("name"),
            type=p.get("type"),
            discount_vnd=p.get("discount_vnd", 0),
            discount_percent=p.get("discount_percent", 0),
            gift_sku=p.get("gift_sku"),
            min_order_vnd=p.get("min_order_vnd", 0),
            start_date=p.get("start"),
            end_date=p.get("end"),
            stackable=p.get("stackable", False),
            applies_to=p.get("applies_to", []),
            conditions=p.get("conditions") if p.get("conditions") else None
        )
        session.add(promo_obj)

    print("4. Đang insert inventory events...")
    for e in inventory_data:
        sku = e.get("sku")
        sku_type = 'variant' if sku in variant_skus else 'product'
        inv_obj = InventoryEvent(
            sku=sku,
            sku_type=sku_type,
            event_date=e.get("date"),
            qty=e.get("qty"),
            note=e.get("note")
        )
        session.add(inv_obj)

    print("5. Đang insert CRM data...")
    for c in crm_data:
        cust_obj = Customer(
            customer_id=c.get("customer_id"),
            name=c.get("name"),
            honorific=c.get("honorific"),
            phone=c.get("phone"),
            zalo_id=c.get("zalo_id"),
            fb_id=c.get("fb_id"),
            region=c.get("region"),
            shared_phone_with=c.get("shared_phone_with")
        )
        
        for o in c.get("orders", []):
            order_obj = Order(
                order_id=o.get("order_id"),
                sku=o.get("sku"),
                qty=o.get("qty", 1),
                price_vnd=o.get("price_vnd"),
                promo_code=o.get("promo_code"),
                payment=o.get("payment", "COD"),
                address=o.get("address"),
                order_date=o.get("date"),
                status=o.get("status"),
                tracking=o.get("tracking"),
                exchange_count=o.get("exchange_count", 0),
            )
            cust_obj.orders.append(order_obj)
            
        session.add(cust_obj)

    # Commit toàn bộ transaction
    session.commit()
    print("=> Insert thành công vào Database!")

def migrate_orders(engine):
    """Add missing order columns without changing existing rows."""
    Base.metadata.create_all(engine)
    existing = {column["name"] for column in inspect(engine).get_columns("orders")}
    with engine.begin() as connection:
        for name, definition in ORDER_COLUMNS.items():
            if name not in existing:
                connection.execute(text(f'ALTER TABLE orders ADD COLUMN "{name}" {definition}'))
                print(f"added orders.{name}")
    print("orders schema ready")


def main():
    parser = argparse.ArgumentParser(description="Seed a new PostgreSQL database or upgrade an existing orders table.")
    parser.add_argument(
        "--orders-only",
        action="store_true",
        help="Only add missing orders columns; do not import catalog/CRM JSON.",
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set; configure .env first")
    print("Connecting to PostgreSQL using SQLAlchemy...")
    engine = create_engine(database_url)

    if args.orders_only:
        migrate_orders(engine)
        return
    
    existing_tables = set(inspect(engine).get_table_names())
    app_tables = existing_tables.intersection(Base.metadata.tables)
    if app_tables:
        raise RuntimeError(
            "Chỉ seed vào database mới, chưa có bảng ứng dụng. "
            f"Các bảng đã tồn tại: {', '.join(sorted(app_tables))}"
        )

    print("Tạo các bảng (Schema)...")
    Base.metadata.create_all(engine)
    print("Schema ready.")
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        insert_data(session)
        migrate_orders(engine)
        print("Migration hoàn tất thành công trên PostgreSQL!")
    except Exception as e:
        session.rollback()
        raise RuntimeError("Không thể nạp dữ liệu catalog/CRM") from e
    finally:
        session.close()

if __name__ == "__main__":
    main()
