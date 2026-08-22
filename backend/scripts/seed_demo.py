from decimal import Decimal

from sqlalchemy import select

from db.database import get_connected_database_name, get_session_factory
from db.models import Merchant, Product, StockMovement


PRODUCTS = [
    ("Coke 250ml", "beverages", 48, 18, 2, "14.00", "20.00"),
    ("Pepsi 250ml", "beverages", 42, 18, 2, "14.00", "20.00"),
    ("Lays Classic", "snacks", 36, 20, 3, "10.50", "20.00"),
    ("Parle-G Biscuits", "biscuits", 80, 30, 2, "4.25", "5.00"),
    ("Milk 500ml", "dairy", 24, 20, 1, "24.00", "28.00"),
    ("Bread", "bakery", 18, 12, 1, "28.00", "35.00"),
    ("Bottled Water", "beverages", 60, 24, 2, "7.50", "12.00"),
    ("Sugar", "groceries", 25, 10, 4, "39.00", "45.00"),
    ("Rice", "groceries", 32, 12, 5, "52.00", "60.00"),
    ("Eggs", "dairy", 90, 36, 1, "5.50", "7.00"),
]


def seed() -> None:
    database_name = get_connected_database_name()
    if database_name != "paytm_business_ai":
        raise RuntimeError("Refusing to seed any database except paytm_business_ai.")

    session_factory = get_session_factory()
    with session_factory() as db:
        existing = db.scalar(select(Merchant).where(Merchant.business_name == "Ravi General Store"))
        if existing:
            print("Demo seed already exists.")
            return

        merchant = Merchant(
            name="Ravi General Store",
            business_name="Ravi General Store",
            business_type="Kirana Store",
            city="Hyderabad",
        )
        db.add(merchant)
        db.flush()

        products = []
        for name, category, stock, reorder, lead_time, unit_cost, selling_price in PRODUCTS:
            product = Product(
                merchant_id=merchant.id,
                name=name,
                category=category,
                current_stock=stock,
                reorder_level=reorder,
                supplier_lead_time_days=lead_time,
                unit_cost=Decimal(unit_cost),
                selling_price=Decimal(selling_price),
            )
            db.add(product)
            products.append(product)

        db.flush()

        movements = [
            (products[0], "purchase", 48, "demo", "Opening demo stock"),
            (products[1], "purchase", 42, "demo", "Opening demo stock"),
            (products[2], "sale", 6, "demo", "Demo sale movement"),
            (products[4], "purchase", 24, "demo", "Morning dairy delivery"),
            (products[5], "sale", 4, "demo", "Demo sale movement"),
            (products[7], "adjustment", 2, "manual", "Shelf count correction"),
            (products[9], "purchase", 90, "demo", "Opening demo stock"),
        ]
        for product, movement_type, quantity, source, notes in movements:
            db.add(
                StockMovement(
                    merchant_id=merchant.id,
                    product_id=product.id,
                    movement_type=movement_type,
                    quantity=quantity,
                    source=source,
                    notes=notes,
                )
            )

        db.commit()
        print("Inserted demo seed for Ravi General Store.")


if __name__ == "__main__":
    seed()
