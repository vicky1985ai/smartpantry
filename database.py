import os
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

RAW_DB_URL = os.environ.get("DATABASE_URL", "")

if RAW_DB_URL:
    # Render provides postgres://, SQLAlchemy requires postgresql://
    if RAW_DB_URL.startswith("postgres://"):
        DB_URL = RAW_DB_URL.replace("postgres://", "postgresql://", 1)
    else:
        DB_URL = RAW_DB_URL
else:
    db_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(db_dir, exist_ok=True)
    DB_PATH = os.path.join(db_dir, "smart_pantry.db")
    DB_URL = f"sqlite:///{DB_PATH}"

# Connect args (needed for SQLite multi-thread)
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}

engine = create_engine(DB_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_connection():
    return engine.connect()

def is_postgres():
    return DB_URL.startswith("postgresql")

def init_db():
    with engine.begin() as conn:
        id_col = "SERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"

        # Categories table
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS categories (
            id {id_col},
            name VARCHAR(100) UNIQUE NOT NULL,
            icon VARCHAR(20) DEFAULT '📦',
            created_at VARCHAR(50)
        )
        """))

        # Inventory table
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS inventory (
            id {id_col},
            name VARCHAR(255) NOT NULL,
            category VARCHAR(100) NOT NULL,
            brand VARCHAR(255),
            preferred_brand VARCHAR(255),
            brand_reason VARCHAR(255),
            quantity FLOAT DEFAULT 1.0,
            unit VARCHAR(20) DEFAULT 'kg',
            status VARCHAR(50) DEFAULT 'in_stock',
            min_threshold FLOAT DEFAULT 1.0,
            storage_location VARCHAR(100) DEFAULT 'Kitchen Pantry',
            last_bought_price FLOAT,
            last_bought_store VARCHAR(100),
            last_bought_date VARCHAR(50),
            updated_by VARCHAR(100) DEFAULT 'Vipin',
            updated_at VARCHAR(50)
        )
        """))

        # Shopping List table
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS shopping_list (
            id {id_col},
            inventory_id INTEGER,
            item_name VARCHAR(255) NOT NULL,
            preferred_brand VARCHAR(255),
            quantity_needed FLOAT DEFAULT 1.0,
            unit VARCHAR(20) DEFAULT 'kg',
            category VARCHAR(100),
            store_recommendation VARCHAR(255),
            lowest_price FLOAT,
            lowest_store VARCHAR(100),
            is_bought INTEGER DEFAULT 0,
            added_by VARCHAR(100) DEFAULT 'Vipin',
            created_at VARCHAR(50)
        )
        """))

        # Price History table
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS price_history (
            id {id_col},
            item_name VARCHAR(255) NOT NULL,
            brand VARCHAR(255),
            store_name VARCHAR(100) NOT NULL,
            quantity FLOAT DEFAULT 1.0,
            unit VARCHAR(20) DEFAULT 'kg',
            price_paid FLOAT NOT NULL,
            unit_price FLOAT,
            bill_date VARCHAR(50),
            bill_id INTEGER,
            notes VARCHAR(255),
            created_at VARCHAR(50)
        )
        """))

        # Bills table
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS bills (
            id {id_col},
            store_name VARCHAR(100),
            bill_date VARCHAR(50),
            total_amount FLOAT,
            item_count INTEGER,
            image_filename VARCHAR(255),
            raw_json TEXT,
            uploaded_by VARCHAR(100) DEFAULT 'Vipin',
            created_at VARCHAR(50)
        )
        """))

        # Activity Log table
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS activity_log (
            id {id_col},
            user_name VARCHAR(100) NOT NULL,
            action_type VARCHAR(100) NOT NULL,
            description TEXT NOT NULL,
            created_at VARCHAR(50)
        )
        """))

        # Seed categories if empty
        cat_count = conn.execute(text("SELECT COUNT(*) FROM categories")).scalar()
        if cat_count == 0:
            seed_categories(conn)

        # Seed initial data if inventory empty
        inv_count = conn.execute(text("SELECT COUNT(*) FROM inventory")).scalar()
        if inv_count == 0:
            seed_initial_data(conn)

def seed_categories(conn):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    defaults = [
        ("Grains & Dals", "🌾"),
        ("Dairy & Bakery", "🥛"),
        ("Spices & Cooking Oils", "🛢️"),
        ("Fresh Produce", "🥦"),
        ("Snacks & Beverages", "☕"),
        ("Cleaning & Personal Care", "🧼"),
        ("Stationery", "✏️"),
        ("Medicines & First Aid", "💊"),
        ("Toiletries & Hygiene", "🪥"),
        ("Other", "📦"),
    ]
    for name, icon in defaults:
        conn.execute(
            text("INSERT INTO categories (name, icon, created_at) VALUES (:name, :icon, :created_at)"),
            {"name": name, "icon": icon, "created_at": now}
        )

def log_activity(conn, user_name, action_type, description):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        text("INSERT INTO activity_log (user_name, action_type, description, created_at) VALUES (:user_name, :action_type, :description, :created_at)"),
        {"user_name": user_name, "action_type": action_type, "description": description, "created_at": now}
    )

def seed_initial_data(conn):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sample_items = [
        # (name, category, brand, preferred_brand, brand_reason, qty, unit, status, min_th, location, price, store, date)
        ("Aashirvaad Sharbati Atta", "Grains & Dals", "Aashirvaad", "Aashirvaad", "Consistently soft rotis", 10.0, "kg", "in_stock", 2.0, "Kitchen Pantry", 425.0, "DMart", "2026-11-10"),
        ("Tata Sampann Toor Dal", "Grains & Dals", "Tata Sampann", "Tata Sampann", "Unpolished, quick cooking", 0.5, "kg", "low", 1.0, "Kitchen Pantry", 175.0, "DMart", "2026-11-05"),
        ("Daawat Rozana Gold Basmati Rice", "Grains & Dals", "Daawat", "Daawat", "Long grain, great aroma", 5.0, "kg", "in_stock", 2.0, "Kitchen Pantry", 380.0, "BigBasket", "2026-11-02"),
        ("Amul Butter", "Dairy & Bakery", "Amul", "Amul", "Best taste, family favorite", 0.1, "kg", "low", 0.5, "Fridge", 56.0, "Blinkit", "2026-11-18"),
        ("Amul Taaza Toned Milk", "Dairy & Bakery", "Amul", "Amul", "Daily tea & milk", 0.0, "L", "out_of_stock", 1.0, "Fridge", 54.0, "Blinkit", "2026-11-19"),
        ("Fortune Kachi Ghani Mustard Oil", "Spices & Cooking Oils", "Fortune", "Fortune", "Authentic pungency", 2.0, "L", "in_stock", 1.0, "Kitchen Pantry", 145.0, "DMart", "2026-11-08"),
        ("Amul Pure Ghee", "Spices & Cooking Oils", "Amul", "Amul", "Pure cow ghee taste", 1.0, "L", "in_stock", 0.5, "Kitchen Pantry", 620.0, "JioMart", "2026-11-01"),
        ("Tata Salt (Vacuum Evaporated)", "Spices & Cooking Oils", "Tata Salt", "Tata Salt", "Standard iodine", 1.0, "kg", "in_stock", 0.5, "Kitchen Pantry", 28.0, "Zepto", "2026-11-12"),
        ("Red Label Tea", "Snacks & Beverages", "Brooke Bond", "Brooke Bond Red Label", "Strong kadak chai", 0.25, "kg", "low", 0.5, "Kitchen Pantry", 140.0, "Instamart", "2026-11-14"),
        ("Surf Excel Matic Liquid Detergent", "Cleaning & Personal Care", "Surf Excel", "Surf Excel", "Safe on washing machine", 2.0, "L", "in_stock", 1.0, "Store Room", 365.0, "DMart", "2026-10-28"),
        ("Vim Dishwash Gel (Lemon)", "Cleaning & Personal Care", "Vim", "Vim", "Cuts grease easily", 0.75, "L", "in_stock", 0.5, "Kitchen Pantry", 155.0, "BigBasket", "2026-11-06"),
    ]

    for item in sample_items:
        conn.execute(text("""
        INSERT INTO inventory (name, category, brand, preferred_brand, brand_reason, quantity, unit, status, min_threshold, storage_location, last_bought_price, last_bought_store, last_bought_date, updated_by, updated_at)
        VALUES (:name, :category, :brand, :preferred_brand, :brand_reason, :quantity, :unit, :status, :min_threshold, :storage_location, :last_bought_price, :last_bought_store, :last_bought_date, 'System', :updated_at)
        """), {
            "name": item[0], "category": item[1], "brand": item[2], "preferred_brand": item[3],
            "brand_reason": item[4], "quantity": item[5], "unit": item[6], "status": item[7],
            "min_threshold": item[8], "storage_location": item[9], "last_bought_price": item[10],
            "last_bought_store": item[11], "last_bought_date": item[12], "updated_at": now
        })

    # Only add STARRED items that are low/empty to shopping list!
    # Tata Sampann Toor Dal (low + starred) & Amul Butter (low + starred) & Amul Milk (out + starred)
    starred_low_items = [
        ("Tata Sampann Toor Dal", "Tata Sampann", 1.0, "kg", "Grains & Dals", "Recommended store: DMart (last ₹175)", 175.0, "DMart"),
        ("Amul Butter", "Amul", 0.5, "kg", "Dairy & Bakery", "Recommended store: Blinkit (last ₹56)", 56.0, "Blinkit"),
        ("Amul Taaza Toned Milk", "Amul", 1.0, "L", "Dairy & Bakery", "Recommended store: Blinkit (last ₹54)", 54.0, "Blinkit"),
    ]
    for s in starred_low_items:
        conn.execute(text("""
        INSERT INTO shopping_list (item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
        VALUES (:name, :brand, :qty, :unit, :cat, :store_rec, :lowest_price, :lowest_store, 0, 'Auto-Sync (⭐ Staple)', :created_at)
        """), {
            "name": s[0], "brand": s[1], "qty": s[2], "unit": s[3], "cat": s[4],
            "store_rec": s[5], "lowest_price": s[6], "lowest_store": s[7], "created_at": now
        })

    # Sample price history
    sample_prices = [
        ("Tata Sampann Toor Dal", "Tata Sampann", "DMart", 1.0, "kg", 175.0, 175.0, "2026-11-05"),
        ("Tata Sampann Toor Dal", "Tata Sampann", "Blinkit", 1.0, "kg", 195.0, 195.0, "2026-11-12"),
        ("Tata Sampann Toor Dal", "Tata Sampann", "Zepto", 1.0, "kg", 198.0, 198.0, "2026-11-15"),
        ("Aashirvaad Sharbati Atta", "Aashirvaad", "DMart", 10.0, "kg", 425.0, 42.5, "2026-11-10"),
        ("Aashirvaad Sharbati Atta", "Aashirvaad", "Blinkit", 10.0, "kg", 475.0, 47.5, "2026-11-14"),
        ("Amul Butter", "Amul", "DMart", 0.5, "kg", 265.0, 530.0, "2026-10-25"),
        ("Amul Butter", "Amul", "Blinkit", 0.5, "kg", 285.0, 570.0, "2026-11-18"),
        ("Fortune Kachi Ghani Mustard Oil", "Fortune", "DMart", 1.0, "L", 145.0, 145.0, "2026-11-08"),
        ("Fortune Kachi Ghani Mustard Oil", "Fortune", "Blinkit", 1.0, "L", 168.0, 168.0, "2026-11-16"),
        ("Surf Excel Matic Liquid Detergent", "Surf Excel", "DMart", 2.0, "L", 365.0, 182.5, "2026-10-28"),
    ]
    for p in sample_prices:
        conn.execute(text("""
        INSERT INTO price_history (item_name, brand, store_name, quantity, unit, price_paid, unit_price, bill_date, created_at)
        VALUES (:name, :brand, :store, :qty, :unit, :price, :unit_price, :bill_date, :created_at)
        """), {
            "name": p[0], "brand": p[1], "store": p[2], "qty": p[3], "unit": p[4],
            "price": p[5], "unit_price": p[6], "bill_date": p[7], "created_at": now
        })

    log_activity(conn, "System", "init", "SmartPantry database initialized.")
