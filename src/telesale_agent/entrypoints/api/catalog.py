"""Public, read-only product catalog backed by the configured PostgreSQL database."""

import logging
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from telesale_agent.adapters.db.client import db_client
from telesale_agent.adapters.db.models import InventoryEvent, Product

router = APIRouter(prefix="/api/catalog", tags=["catalog"])
logger = logging.getLogger(__name__)


def read_products(sku: str | None = None) -> list[dict]:
    """Return product, variant and effective stock fields needed by the web UI."""
    with db_client.get_session() as session:
        statement = select(Product).options(selectinload(Product.variants)).order_by(Product.sku)
        if sku is not None:
            statement = statement.where(Product.sku == sku)
        products = session.scalars(statement).all()
        if not products:
            return []

        skus = {product.sku for product in products}
        skus.update(variant.variant_sku for product in products for variant in product.variants)
        events = session.scalars(
            select(InventoryEvent)
            .where(InventoryEvent.sku.in_(skus), InventoryEvent.event_date <= date.today())
            .order_by(InventoryEvent.event_date.desc(), InventoryEvent.id.desc())
        ).all()
        latest_stock: dict[str, int] = {}
        for event in events:
            latest_stock.setdefault(event.sku, event.qty)

        result = []
        for product in products:
            attributes = dict(product.attributes or {})
            attributes.pop("discontinued", None)
            attributes.pop("successor_sku", None)
            if product.is_discontinued:
                attributes["discontinued"] = True
            if product.successor_sku:
                attributes["successor_sku"] = product.successor_sku
            result.append({
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "brand": product.brand or "",
                "list_price_vnd": int(product.list_price_vnd or 0),
                "attributes": attributes,
                "stock": latest_stock.get(product.sku, product.stock or 0),
                "variants": [
                    {
                        "variant_sku": variant.variant_sku,
                        "size": variant.size or "",
                        "color": variant.color or "",
                        "price_delta_vnd": int(variant.price_delta_vnd or 0),
                        "stock": latest_stock.get(variant.variant_sku, variant.stock or 0),
                    }
                    for variant in sorted(product.variants, key=lambda item: item.variant_sku)
                ],
            })
        return result


@router.get("/products")
def list_products():
    try:
        return {"items": read_products()}
    except SQLAlchemyError as exc:
        logger.exception("Catalog query failed")
        raise HTTPException(status_code=503, detail="Catalog is unavailable") from exc


@router.get("/products/{sku}")
def get_product(sku: str):
    try:
        products = read_products(sku)
    except SQLAlchemyError as exc:
        logger.exception("Catalog query failed")
        raise HTTPException(status_code=503, detail="Catalog is unavailable") from exc
    if not products:
        raise HTTPException(status_code=404, detail="Product not found")
    return products[0]
