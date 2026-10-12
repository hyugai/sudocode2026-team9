import os
from datetime import date
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from telesale_agent.adapters.db.models import (
    Product, ProductVariant, Promotion, InventoryEvent, Customer, Order
)

class PostgresClient:
    """Client kết nối PostgreSQL và thực hiện query qua SQLAlchemy."""
    
    _instance = None
    
    def __new__(cls, db_url: str = None):
        if cls._instance is None:
            cls._instance = super(PostgresClient, cls).__new__(cls)
            cls._instance._initialize(db_url)
        return cls._instance
        
    def _initialize(self, db_url: str = None):
        from dotenv import load_dotenv
        load_dotenv()
        if not db_url:
            db_url = os.environ.get("DATABASE_URL")
            if not db_url:
                raise ValueError("DATABASE_URL is not set in .env")
            
        # Normalize common provider URL schemes for SQLAlchemy/psycopg2.
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
            
        self.engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
    def get_session(self):
        return self.SessionLocal()

    # =========================================================
    # CATALOG QUERIES
    # =========================================================
    
    def search_products(self, query: str = None, category: str = None, sku: str = None, max_price_vnd: int = None):
        with self.get_session() as session:
            stmt = session.query(Product).filter(Product.is_discontinued == False)
            
            if sku:
                variant = (
                    session.query(ProductVariant)
                    .filter(ProductVariant.variant_sku == sku)
                    .first()
                )
                stmt = stmt.filter(
                    Product.sku == (variant.product_sku if variant else sku)
                )
            if query:
                stmt = stmt.filter(Product.name.ilike(f"%{query}%"))
            if category:
                stmt = stmt.filter(Product.category.ilike(f"%{category}%"))
            if max_price_vnd:
                stmt = stmt.filter(Product.list_price_vnd <= max_price_vnd)
                
            products = stmt.all()
            results = []
            for p in products:
                results.append({
                    "sku": p.sku,
                    "name": p.name,
                    "list_price_vnd": float(p.list_price_vnd) if p.list_price_vnd else 0,
                    "attributes": p.attributes,
                    "variants": [
                        {
                            "variant_sku": v.variant_sku, 
                            "size": v.size, 
                            "color": v.color, 
                            "price_delta": float(v.price_delta_vnd) if v.price_delta_vnd else 0,
                        } for v in p.variants
                    ]
                })
            return {"items": results}

    def check_stock(self, sku: str, target_date: date) -> dict:
        with self.get_session() as session:
            # Check inventory_events
            event = session.query(InventoryEvent).filter(
                InventoryEvent.sku == sku,
                InventoryEvent.event_date <= target_date
            ).order_by(InventoryEvent.event_date.desc()).first()
            
            qty = 0
            if event:
                qty = event.qty
            else:
                # Fallback tĩnh
                variant = session.query(ProductVariant).filter_by(variant_sku=sku).first()
                if variant:
                    qty = variant.stock
                else:
                    product = session.query(Product).filter_by(sku=sku).first()
                    if product:
                        qty = product.stock
                        
            in_stock = qty > 0
            
            return {
                "sku": sku,
                "in_stock": in_stock,
                "qty": qty,
                "discontinued": False, # Tính năng này có thể join thêm product để check nếu cần
            }

    def get_active_promotions(self, cart_skus: list[str], cart_categories: list[str], region: str, current_date: date):
        with self.get_session() as session:
            promos = session.query(Promotion).filter(
                Promotion.start_date <= current_date,
                Promotion.end_date >= current_date
            ).all()
            
            applicable_promos = []
            for p in promos:
                applies_to = p.applies_to or []
                conditions = p.conditions or {}
                
                is_match = False
                if "*" in applies_to:
                    is_match = True
                else:
                    for item in applies_to:
                        if item in cart_skus:
                            is_match = True
                            break
                        if item.startswith("category:"):
                            cat = item.split(":", 1)[1]
                            if cat in cart_categories:
                                is_match = True
                                break
                                
                if not is_match:
                    continue
                    
                req_region = conditions.get("region")
                if req_region and region not in req_region:
                    continue
                    
                applicable_promos.append({
                    "promotion_id": p.promo_code,
                    "discount_percent": p.discount_percent,
                    "discount_vnd": float(p.discount_vnd) if p.discount_vnd else 0
                })
            return applicable_promos

    # =========================================================
    # CRM QUERIES
    # =========================================================

    @staticmethod
    def _serialize_customer(customer):
        orders_data = [{
            "order_id": order.order_id,
            "sku": order.sku,
            "status": order.status,
            "order_date": str(order.order_date),
        } for order in customer.orders]

        return {
            "found": True,
            "ambiguous": False,
            "customer_id": customer.customer_id,
            "name": customer.name,
            "honorific": customer.honorific,
            "phone": customer.phone,
            "region": customer.region,
            "attributes": customer.attributes or {},
            "orders": orders_data,
        }

    def get_customer_by_id(self, customer_id: str):
        """Retrieve one customer using the canonical CRM identifier."""
        with self.get_session() as session:
            customer = session.query(Customer).filter_by(customer_id=customer_id).first()
            if customer is None:
                return {"found": False, "orders": []}
            return self._serialize_customer(customer)

    def get_customer(self, phone: str = None, zalo_id: str = None, fb_id: str = None):
        with self.get_session() as session:
            stmt = session.query(Customer)
            
            if phone:
                stmt = stmt.filter_by(phone=phone)
            elif zalo_id:
                stmt = stmt.filter_by(zalo_id=zalo_id)
            elif fb_id:
                stmt = stmt.filter_by(fb_id=fb_id)
            else:
                return {"found": False, "orders": []}
                
            customers = stmt.all()
            
            if len(customers) == 0:
                return {"found": False, "orders": []}
                
            ambiguous = len(customers) > 1
            
            # Nếu ambiguous, trả về danh sách ứng viên
            if ambiguous:
                candidates = []
                for c in customers:
                    candidates.append({
                        "customer_id": c.customer_id,
                        "name": c.name,
                        "phone": c.phone
                    })
                return {"found": True, "ambiguous": True, "candidates": candidates, "orders": []}
            
            return self._serialize_customer(customers[0])

    def create_customer(self, phone: str) -> str:
        """Tạo khách hàng mới nếu chưa có, auto-generate mã CXXX."""
        with self.get_session() as session:
            # Tìm mã CXXX lớn nhất
            last_customer = session.query(Customer).filter(Customer.customer_id.like("C%")).order_by(Customer.customer_id.desc()).first()
            if last_customer and len(last_customer.customer_id) >= 4:
                try:
                    last_num = int(last_customer.customer_id[1:])
                    new_id = f"C{last_num + 1:03d}"
                except ValueError:
                    new_id = "C001"
            else:
                new_id = "C001"
                
            new_customer = Customer(
                customer_id=new_id,
                phone=phone,
                name="Khách hàng mới",
                honorific="Anh/Chị"
            )
            session.add(new_customer)
            session.commit()
            return new_id

    def update_customer_attributes(self, phone: str, deltas: dict):
        if not deltas:
            return
        with self.get_session() as session:
            c = session.query(Customer).filter_by(phone=phone).first()
            if c:
                current_attr = c.attributes or {}
                # Create a new dict because SQLAlchemy JSONB tracking can be tricky
                new_attr = dict(current_attr)
                new_attr.update(deltas)
                c.attributes = new_attr
                session.commit()
                return c.attributes

# Khởi tạo singleton instance
db_client = PostgresClient()

# Backward-compatible import for modules that still use the old class name.
SupabaseClient = PostgresClient
