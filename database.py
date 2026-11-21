import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "smart_pantry.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        brand TEXT,
        preferred_brand TEXT,
        brand_reason TEXT,
        quantity REAL DEFAULT 1.0,
        unit TEXT DEFAULT 'kg',
        status TEXT DEFAULT 'in_stock',
        min_threshold REAL DEFAULT 1.0,
        storage_location TEXT DEFAULT 'Kitchen Pantry',
        last_bought_price REAL,
        last_bought_store TEXT,
        last_bought_date TEXT,
        updated_by TEXT DEFAULT 'Vipin',
        updated_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shopping_list (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inventory_id INTEGER,
        item_name TEXT NOT NULL,
        preferred_brand TEXT,
        quantity_needed REAL DEFAULT 1.0,
        unit TEXT DEFAULT 'kg',
        category TEXT,
        store_recommendation TEXT,
        lowest_price REAL,
        lowest_store TEXT,
        is_bought INTEGER DEFAULT 0,
        added_by TEXT DEFAULT 'Vipin',
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT NOT NULL,
        brand TEXT,
        store_name TEXT NOT NULL,
        quantity REAL DEFAULT 1.0,
        unit TEXT DEFAULT 'kg',
        price_paid REAL NOT NULL,
        unit_price REAL,
        bill_date TEXT,
        bill_id INTEGER,
        notes TEXT,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_name TEXT,
        bill_date TEXT,
        total_amount REAL,
        item_count INTEGER,
        image_filename TEXT,
        raw_json TEXT,
        uploaded_by TEXT DEFAULT 'Vipin',
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT NOT NULL,
        action_type TEXT NOT NULL,
        description TEXT NOT NULL,
        created_at TEXT
    )
    """)

    conn.commit()

    # Seed initial realistic household data if table is empty
    cursor.execute("SELECT COUNT(*) FROM inventory")
    count = cursor.fetchone()[0]
    if count == 0:
        seed_initial_data(cursor)
        conn.commit()

    conn.close()

def log_activity(cursor, user_name, action_type, description):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO activity_log (user_name, action_type, description, created_at) VALUES (?, ?, ?, ?)",
        (user_name, action_type, description, now)
    )

def seed_initial_data(cursor):
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
        cursor.execute("""
        INSERT INTO inventory (name, category, brand, preferred_brand, brand_reason, quantity, unit, status, min_threshold, storage_location, last_bought_price, last_bought_store, last_bought_date, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'System', ?)
        """, (item[0], item[1], item[2], item[3], item[4], item[5], item[6], item[7], item[8], item[9], item[10], item[11], item[12], now))
        inv_id = cursor.lastrowid

        # If low or out_of_stock, automatically seed into shopping list!
        if item[7] in ("low", "out_of_stock"):
            cursor.execute("""
            INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'Auto-Sync', ?)
            """, (inv_id, item[0], item[3], item[8], item[6], item[1], f"Recommended store: {item[11]} (last ₹{item[10]})", item[10], item[11], now))

    # Seed sample price comparison history across stores
    sample_prices = [
        # Toor Dal 1kg
        ("Tata Sampann Toor Dal", "Tata Sampann", "DMart", 1.0, "kg", 175.0, 175.0, "2026-11-05"),
        ("Tata Sampann Toor Dal", "Tata Sampann", "Blinkit", 1.0, "kg", 195.0, 195.0, "2026-11-12"),
        ("Tata Sampann Toor Dal", "Tata Sampann", "Zepto", 1.0, "kg", 198.0, 198.0, "2026-11-15"),
        ("Tata Sampann Toor Dal", "Tata Sampann", "JioMart", 1.0, "kg", 182.0, 182.0, "2026-11-08"),
        ("Tata Sampann Toor Dal", "Tata Sampann", "BigBasket", 1.0, "kg", 185.0, 185.0, "2026-11-01"),

        # Aashirvaad Atta 10kg
        ("Aashirvaad Sharbati Atta", "Aashirvaad", "DMart", 10.0, "kg", 425.0, 42.5, "2026-11-10"),
        ("Aashirvaad Sharbati Atta", "Aashirvaad", "Blinkit", 10.0, "kg", 475.0, 47.5, "2026-11-14"),
        ("Aashirvaad Sharbati Atta", "Aashirvaad", "BigBasket", 10.0, "kg", 445.0, 44.5, "2026-11-03"),
        ("Aashirvaad Sharbati Atta", "Aashirvaad", "JioMart", 10.0, "kg", 435.0, 43.5, "2026-11-07"),

        # Amul Butter 500g
        ("Amul Butter", "Amul", "DMart", 0.5, "kg", 265.0, 530.0, "2026-10-25"),
        ("Amul Butter", "Amul", "Blinkit", 0.5, "kg", 285.0, 570.0, "2026-11-18"),
        ("Amul Butter", "Amul", "Zepto", 0.5, "kg", 285.0, 570.0, "2026-11-16"),
        ("Amul Butter", "Amul", "Instamart", 0.5, "kg", 282.0, 564.0, "2026-11-14"),

        # Fortune Mustard Oil 1L
        ("Fortune Kachi Ghani Mustard Oil", "Fortune", "DMart", 1.0, "L", 145.0, 145.0, "2026-11-08"),
        ("Fortune Kachi Ghani Mustard Oil", "Fortune", "Blinkit", 1.0, "L", 168.0, 168.0, "2026-11-16"),
        ("Fortune Kachi Ghani Mustard Oil", "Fortune", "Zepto", 1.0, "L", 165.0, 165.0, "2026-11-17"),
        ("Fortune Kachi Ghani Mustard Oil", "Fortune", "Instamart", 1.0, "L", 169.0, 169.0, "2026-11-19"),
        ("Fortune Kachi Ghani Mustard Oil", "Fortune", "BigBasket", 1.0, "L", 152.0, 152.0, "2026-11-04"),

        # Surf Excel Matic 2L
        ("Surf Excel Matic Liquid Detergent", "Surf Excel", "DMart", 2.0, "L", 365.0, 182.5, "2026-10-28"),
        ("Surf Excel Matic Liquid Detergent", "Surf Excel", "Blinkit", 2.0, "L", 420.0, 210.0, "2026-11-11"),
        ("Surf Excel Matic Liquid Detergent", "Surf Excel", "JioMart", 2.0, "L", 380.0, 190.0, "2026-11-05"),
    ]

    for p in sample_prices:
        cursor.execute("""
        INSERT INTO price_history (item_name, brand, store_name, quantity, unit, price_paid, unit_price, bill_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], now))

    log_activity(cursor, "System", "init", "SmartPantry database initialized with starter household items & price intelligence.")
