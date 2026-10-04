import os
from datetime import datetime
from sqlalchemy import Column, String, Integer, Numeric, Boolean, Date, DateTime, ForeignKey, CheckConstraint, Index, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB

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
    attributes = Column(JSONB, default=dict)
    
    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan")
    sessions = relationship("CustomerSession", back_populates="customer", cascade="all, delete-orphan")

class Order(Base):
    __tablename__ = 'orders'
    order_id = Column(String(50), primary_key=True)
    customer_id = Column(String(50), ForeignKey('customers.customer_id', ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(50))
    price_vnd = Column(Numeric(15, 2))
    order_date = Column(Date)
    status = Column(String(50))
    tracking = Column(String(100))
    
    customer = relationship("Customer", back_populates="orders")

class CustomerSession(Base):
    __tablename__ = 'customer_sessions'
    session_id = Column(String(50), primary_key=True)
    customer_id = Column(String(50), ForeignKey('customers.customer_id', ondelete="CASCADE"), nullable=False, index=True)
    session_date = Column(Date)
    channel = Column(String(50))
    summary = Column(String)
    outcome = Column(String(50))
    
    customer = relationship("Customer", back_populates="sessions")
