import os
from datetime import date, datetime
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
    
    def search_products(
        self,
        query: str = None,
        category: str = None,
        sku: str = None,
        max_price_vnd: int = None,
        *,
        include_discontinued: bool = False,
    ):
        with self.get_session() as session:
            stmt = session.query(Product)
            if not include_discontinued:
                stmt = stmt.filter(Product.is_discontinued == False)
            
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
                    "category": p.category,
                    "brand": p.brand,
                    "list_price_vnd": float(p.list_price_vnd) if p.list_price_vnd else 0,
                    "discontinued": bool(p.is_discontinued),
                    "successor_sku": p.successor_sku,
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
            variant = session.query(ProductVariant).filter_by(variant_sku=sku).first()
            product_sku = variant.product_sku if variant else sku
            product = session.query(Product).filter_by(sku=product_sku).first()

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
                if variant:
                    qty = variant.stock
                elif product:
                    qty = product.stock

            next_restock = (
                session.query(InventoryEvent)
                .filter(
                    InventoryEvent.sku == sku,
                    InventoryEvent.event_date > target_date,
                    InventoryEvent.qty > 0,
                )
                .order_by(InventoryEvent.event_date.asc())
                .first()
            )
                        
            in_stock = qty > 0
            
            result = {
                "sku": sku,
                "found": product is not None,
                "in_stock": in_stock,
                "qty": qty,
                "discontinued": bool(product.is_discontinued) if product else False,
            }
            if product and product.successor_sku:
                result["successor_sku"] = product.successor_sku
            if not in_stock and next_restock:
                result["restock_expected"] = next_restock.event_date.isoformat()
            return result

    def get_promotions(self) -> list[dict]:
        """Return canonical promotion rules for deterministic quote calculation."""
        with self.get_session() as session:
            promotions = session.query(Promotion).all()
            return [
                {
                    "promo_code": promo.promo_code,
                    "name": promo.name,
                    "type": promo.type,
                    "discount_vnd": int(promo.discount_vnd or 0),
                    "discount_percent": int(promo.discount_percent or 0),
                    "gift_sku": promo.gift_sku,
                    "min_order_vnd": int(promo.min_order_vnd or 0),
                    "start_date": promo.start_date,
                    "end_date": promo.end_date,
                    "stackable": bool(promo.stackable),
                    "applies_to": promo.applies_to or [],
                    "conditions": promo.conditions or {},
                }
                for promo in promotions
            ]

    def get_pricing_customer_context(
        self,
        *,
        customer_phone: str | None = None,
        customer_id: str | None = None,
    ) -> dict:
        """Return only verified CRM fields needed to evaluate promotions."""
        if customer_id:
            customer = self.get_customer_by_id(customer_id)
        elif customer_phone:
            customer = self.get_customer(phone=customer_phone)
        else:
            return {"found": False, "owned_skus": [], "used_promos": []}
        if not customer.get("found") or customer.get("ambiguous"):
            return {
                "found": False,
                "ambiguous": bool(customer.get("ambiguous")),
                "owned_skus": [],
                "used_promos": [],
            }
        orders = customer.get("orders") or []
        return {
            "found": True,
            "customer_id": customer.get("customer_id"),
            "region": customer.get("region"),
            "owned_skus": [
                order.get("sku")
                for order in orders
                if order.get("sku") and order.get("status") == "delivered"
            ],
            "used_promos": [
                order.get("promo_code")
                for order in orders
                if order.get("promo_code")
            ],
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
    def _serialize_order(order, *, customer_phone: str | None = None):
        return {
            "order_id": order.order_id,
            "customer_id": order.customer_id,
            "customer_phone": customer_phone,
            "sku": order.sku,
            "qty": order.qty,
            "price_vnd": int(order.price_vnd) if order.price_vnd is not None else None,
            "promo_code": order.promo_code,
            "payment": order.payment,
            "address": order.address,
            "status": order.status,
            "created_on": order.order_date.isoformat() if order.order_date else None,
            "exchange_count": order.exchange_count or 0,
        }

    @staticmethod
    def _serialize_customer(customer):
        orders_data = [
            PostgresClient._serialize_order(
                order,
                customer_phone=customer.phone,
            )
            for order in customer.orders
        ]

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

    # =========================================================
    # ORDER QUERIES
    # =========================================================

    def create_order(
        self,
        *,
        order_id: str,
        customer_phone: str,
        customer_id: str | None = None,
        sku: str,
        qty: int,
        price_vnd: int,
        promo_code: str | None,
        payment: str,
        address: str,
        order_date: date,
    ) -> dict:
        """Persist one order transaction and return its canonical payload."""
        with self.get_session() as session:
            if customer_id:
                customer = session.query(Customer).filter_by(customer_id=customer_id).first()
                if customer is None:
                    return {"error": "customer_not_found"}
                if customer.phone != customer_phone:
                    return {"error": "customer_identity_mismatch"}
            else:
                customers = session.query(Customer).filter_by(phone=customer_phone).all()
                if not customers:
                    return {"error": "customer_not_found"}
                if len(customers) != 1:
                    return {"error": "ambiguous_customer_phone"}
                customer = customers[0]
            if session.query(Order).filter_by(order_id=order_id).first():
                return {"error": "order_id_conflict"}
            order = Order(
                order_id=order_id,
                customer_id=customer.customer_id,
                sku=sku,
                qty=qty,
                price_vnd=price_vnd,
                promo_code=promo_code,
                payment=payment,
                address=address,
                order_date=order_date,
                status="created",
                exchange_count=0,
            )
            session.add(order)
            session.commit()
            session.refresh(order)
            return self._serialize_order(order, customer_phone=customer_phone)

    def find_orders(
        self,
        *,
        order_id: str | None = None,
        customer_phone: str | None = None,
    ) -> list[dict]:
        with self.get_session() as session:
            query = session.query(Order, Customer.phone).join(Customer)
            if order_id:
                query = query.filter(Order.order_id == order_id)
            elif customer_phone:
                query = query.filter(Customer.phone == customer_phone)
            else:
                return []
            return [
                self._serialize_order(order, customer_phone=phone)
                for order, phone in query.order_by(Order.order_date.desc()).all()
            ]

    def delete_orders(self, order_ids: list[str] | set[str]) -> int:
        """Delete only explicitly identified orders created by an eval run."""
        normalized = {str(order_id) for order_id in order_ids if order_id}
        if not normalized:
            return 0
        with self.get_session() as session:
            deleted = (
                session.query(Order)
                .filter(Order.order_id.in_(normalized))
                .delete(synchronize_session=False)
            )
            session.commit()
            return int(deleted)

    def update_order(
        self,
        *,
        order_id: str,
        status: str,
        new_variant_sku: str | None = None,
        increment_exchange: bool = False,
    ) -> dict:
        with self.get_session() as session:
            row = (
                session.query(Order, Customer.phone)
                .join(Customer)
                .filter(Order.order_id == order_id)
                .with_for_update()
                .first()
            )
            if row is None:
                return {"error": "order_not_found"}
            order, phone = row
            order.status = status
            if new_variant_sku:
                order.sku = new_variant_sku
            if increment_exchange:
                order.exchange_count = (order.exchange_count or 0) + 1
            order.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(order)
            return self._serialize_order(order, customer_phone=phone)

# Khởi tạo singleton instance
db_client = PostgresClient()

# Backward-compatible import for modules that still use the old class name.
SupabaseClient = PostgresClient
