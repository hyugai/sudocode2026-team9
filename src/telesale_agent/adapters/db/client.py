import os
from datetime import date
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from telesale_agent.adapters.db.models import (
    Product, ProductVariant, Promotion, InventoryEvent, Customer, Order, CustomerSession
)

class SupabaseClient:
    """Client kết nối và thực hiện các query database qua SQLAlchemy."""
    
    _instance = None
    
    def __new__(cls, db_url: str = None):
        if cls._instance is None:
            cls._instance = super(SupabaseClient, cls).__new__(cls)
            cls._instance._initialize(db_url)
        return cls._instance
        
    def _initialize(self, db_url: str = None):
        if not db_url:
            encoded_password = quote_plus("2+#TpJd3RgT2WW/")
            default_url = f"postgresql+psycopg2://postgres:{encoded_password}@db.bgglqoxddueswfzjmpkh.supabase.co:5432/postgres"
            db_url = os.environ.get("DATABASE_URL", default_url)
            
        # Ensure that if environment variable uses postgresql:// it is replaced by postgresql+psycopg2://
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
            
        self.engine = create_engine(db_url)
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
                stmt = stmt.filter(Product.sku == sku)
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
                            "stock": v.stock
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
                return {"found": False, "orders": [], "sessions": []}
                
            customers = stmt.all()
            
            if len(customers) == 0:
                return {"found": False, "orders": [], "sessions": []}
                
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
                return {"found": True, "ambiguous": True, "candidates": candidates, "orders": [], "sessions": []}
            
            # Trả về chi tiết customer duy nhất
            c = customers[0]
            orders_data = [{
                "order_id": o.order_id,
                "sku": o.sku,
                "status": o.status,
                "order_date": str(o.order_date)
            } for o in c.orders]
            
            sessions_data = [{
                "session_id": s.session_id,
                "date": str(s.session_date),
                "summary": s.summary,
                "outcome": s.outcome
            } for s in c.sessions]
            
            return {
                "found": True,
                "ambiguous": False,
                "customer_id": c.customer_id,
                "name": c.name,
                "honorific": c.honorific,
                "phone": c.phone,
                "region": c.region,
                "attributes": c.attributes or {},
                "orders": orders_data,
                "sessions": sessions_data
            }

    def add_customer_session(self, phone: str, summary: str, outcome: str = "completed"):
        import uuid
        from datetime import date
        with self.get_session() as session:
            c = session.query(Customer).filter_by(phone=phone).first()
            if not c:
                return None
            new_session = CustomerSession(
                session_id=str(uuid.uuid4()),
                customer_id=c.customer_id,
                session_date=date.today(),
                channel="voice",
                summary=summary,
                outcome=outcome
            )
            session.add(new_session)
            session.commit()
            return new_session.session_id

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
db_client = SupabaseClient()
