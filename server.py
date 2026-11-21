import os
import shutil
import socket
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database
from database import get_db, log_activity
import bill_parser

app = FastAPI(title="SmartPantry API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
database.init_db()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ----------------- Models -----------------
class InventoryItemCreate(BaseModel):
    name: str
    category: str
    brand: Optional[str] = ""
    preferred_brand: Optional[str] = ""
    brand_reason: Optional[str] = ""
    quantity: float = 1.0
    unit: str = "kg"
    status: str = "in_stock"
    min_threshold: float = 1.0
    storage_location: str = "Kitchen Pantry"
    last_bought_price: Optional[float] = None
    last_bought_store: Optional[str] = None
    updated_by: str = "Vipin"

class InventoryItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    preferred_brand: Optional[str] = None
    brand_reason: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    status: Optional[str] = None
    min_threshold: Optional[float] = None
    storage_location: Optional[str] = None
    last_bought_price: Optional[float] = None
    last_bought_store: Optional[str] = None
    updated_by: str = "Vipin"

class ConsumeRequest(BaseModel):
    action: str  # "decrement", "mark_low", "mark_out"
    amount: Optional[float] = 1.0
    user_name: str = "Vipin"

class StarBrandRequest(BaseModel):
    preferred_brand: str
    brand_reason: Optional[str] = ""
    user_name: str = "Vipin"

class ShoppingItemCreate(BaseModel):
    inventory_id: Optional[int] = None
    item_name: str
    preferred_brand: Optional[str] = ""
    quantity_needed: float = 1.0
    unit: str = "kg"
    category: Optional[str] = "Other"
    added_by: str = "Vipin"

class BillItem(BaseModel):
    name: str
    brand: Optional[str] = ""
    category: Optional[str] = "Other"
    quantity: float = 1.0
    unit: str = "kg"
    price_paid: float
    mrp: Optional[float] = 0.0
    unit_price: Optional[float] = None

class BillConfirmImport(BaseModel):
    store_name: str
    bill_date: str
    total_amount: float
    image_filename: Optional[str] = ""
    items: List[BillItem]
    uploaded_by: str = "Vipin"

# ----------------- Helpers -----------------
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ----------------- Inventory Endpoints -----------------
@app.get("/api/inventory")
def list_inventory(category: Optional[str] = None, status: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM inventory WHERE 1=1"
    params = []
    if category and category != "All":
        query += " AND category = ?"
        params.append(category)
    if status and status != "All":
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY status ASC, name ASC"
    
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]

    # Attach lowest historical price for each item if available
    for row in rows:
        cursor.execute("""
            SELECT store_name, price_paid, unit_price, quantity, unit
            FROM price_history
            WHERE LOWER(item_name) LIKE LOWER(?) OR LOWER(?) LIKE '%' || LOWER(item_name) || '%'
            ORDER BY unit_price ASC, price_paid ASC
            LIMIT 1
        """, (f"%{row['name']}%", row['name']))
        lowest = cursor.fetchone()
        if lowest:
            row["cheapest_store"] = lowest["store_name"]
            row["cheapest_price"] = lowest["price_paid"]
            row["cheapest_unit_price"] = lowest["unit_price"]
        else:
            row["cheapest_store"] = row.get("last_bought_store") or "-"
            row["cheapest_price"] = row.get("last_bought_price") or 0.0
            row["cheapest_unit_price"] = 0.0

    conn.close()
    return rows

@app.post("/api/inventory")
def create_inventory_item(item: InventoryItemCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO inventory (name, category, brand, preferred_brand, brand_reason, quantity, unit, status, min_threshold, storage_location, last_bought_price, last_bought_store, updated_by, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (item.name, item.category, item.brand, item.preferred_brand or item.brand, item.brand_reason, item.quantity, item.unit, item.status, item.min_threshold, item.storage_location, item.last_bought_price, item.last_bought_store, item.updated_by, now))
    item_id = cursor.lastrowid

    # If created as low or out of stock, add to shopping list
    if item.status in ("low", "out_of_stock"):
        cursor.execute("""
        INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (item_id, item.name, item.preferred_brand or item.brand, item.min_threshold, item.unit, item.category, f"Last bought at {item.last_bought_store or 'store'}", item.last_bought_price, item.last_bought_store, item.updated_by, now))

    log_activity(cursor, item.updated_by, "inventory_add", f"Added '{item.name}' ({item.quantity} {item.unit}) to {item.storage_location}.")
    conn.commit()
    conn.close()
    return {"success": True, "id": item_id}

@app.put("/api/inventory/{item_id}")
def update_inventory_item(item_id: int, item: InventoryItemUpdate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
    current = cursor.fetchone()
    if not current:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fields = []
    values = []

    for k, v in item.dict(exclude_unset=True).items():
        if k != "updated_by":
            fields.append(f"{k} = ?")
            values.append(v)

    fields.append("updated_by = ?")
    values.append(item.updated_by)
    fields.append("updated_at = ?")
    values.append(now)
    values.append(item_id)

    query = f"UPDATE inventory SET {', '.join(fields)} WHERE id = ?"
    cursor.execute(query, values)

    # Sync with shopping list if status changed to low or out_of_stock
    if item.status in ("low", "out_of_stock"):
        cursor.execute("SELECT id FROM shopping_list WHERE inventory_id = ? AND is_bought = 0", (item_id,))
        if not cursor.fetchone():
            cursor.execute("""
            INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, added_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (item_id, current["name"], item.preferred_brand or current["preferred_brand"], current["min_threshold"], current["unit"], current["category"], item.updated_by, now))

    log_activity(cursor, item.updated_by, "inventory_update", f"Updated details for '{current['name']}'.")
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/inventory/{item_id}/consume")
def consume_inventory_item(item_id: int, req: ConsumeRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    if not item:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_qty = item["quantity"]
    new_status = item["status"]

    if req.action == "decrement":
        new_qty = max(0.0, item["quantity"] - req.amount)
        if new_qty == 0:
            new_status = "out_of_stock"
        elif new_qty <= item["min_threshold"]:
            new_status = "low"
        else:
            new_status = "in_stock"
    elif req.action == "mark_low":
        new_status = "low"
        new_qty = min(item["quantity"], item["min_threshold"])
    elif req.action == "mark_out":
        new_status = "out_of_stock"
        new_qty = 0.0

    cursor.execute("""
    UPDATE inventory SET quantity = ?, status = ?, updated_by = ?, updated_at = ? WHERE id = ?
    """, (new_qty, new_status, req.user_name, now, item_id))

    # Auto queue to shopping list if Low or Out of Stock!
    if new_status in ("low", "out_of_stock"):
        cursor.execute("SELECT id FROM shopping_list WHERE inventory_id = ? AND is_bought = 0", (item_id,))
        existing_shop = cursor.fetchone()
        if not existing_shop:
            # Find cheapest store from price_history
            cursor.execute("""
            SELECT store_name, price_paid FROM price_history 
            WHERE LOWER(item_name) LIKE LOWER(?) ORDER BY unit_price ASC LIMIT 1
            """, (f"%{item['name']}%",))
            lowest = cursor.fetchone()
            lowest_store = lowest["store_name"] if lowest else item["last_bought_store"]
            lowest_price = lowest["price_paid"] if lowest else item["last_bought_price"]

            cursor.execute("""
            INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (item_id, item["name"], item["preferred_brand"], item["min_threshold"], item["unit"], item["category"], f"Buy from {lowest_store or 'store'}", lowest_price, lowest_store, req.user_name, now))

    action_label = "used some" if req.action == "decrement" else ("marked as LOW" if req.action == "mark_low" else "marked as EMPTY")
    log_activity(cursor, req.user_name, "consumed", f"{req.user_name} {action_label} '{item['name']}' -> now {new_status.replace('_', ' ').title()}.")

    conn.commit()
    conn.close()
    return {"success": True, "new_quantity": new_qty, "new_status": new_status}

@app.post("/api/inventory/{item_id}/star-brand")
def star_brand(item_id: int, req: StarBrandRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM inventory WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    if not item:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE inventory SET preferred_brand = ?, brand_reason = ?, updated_by = ?, updated_at = ? WHERE id = ?
    """, (req.preferred_brand, req.brand_reason, req.user_name, now, item_id))

    # Also update in active shopping list
    cursor.execute("""
    UPDATE shopping_list SET preferred_brand = ? WHERE inventory_id = ? AND is_bought = 0
    """, (req.preferred_brand, item_id))

    log_activity(cursor, req.user_name, "star_brand", f"{req.user_name} set preferred brand for '{item['name']}' to ⭐ {req.preferred_brand}.")
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/inventory/{item_id}")
def delete_inventory_item(item_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM inventory WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    if item:
        cursor.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
        cursor.execute("DELETE FROM shopping_list WHERE inventory_id = ?", (item_id,))
        log_activity(cursor, "User", "inventory_delete", f"Removed '{item['name']}' from pantry.")
        conn.commit()
    conn.close()
    return {"success": True}

# ----------------- Shopping List Endpoints -----------------
@app.get("/api/shopping-list")
def get_shopping_list():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shopping_list WHERE is_bought = 0 ORDER BY created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]

    for r in rows:
        # Check current price intelligence for this item
        cursor.execute("""
            SELECT store_name, price_paid, unit_price
            FROM price_history
            WHERE LOWER(item_name) LIKE LOWER(?) OR LOWER(?) LIKE '%' || LOWER(item_name) || '%'
            ORDER BY unit_price ASC
            LIMIT 1
        """, (f"%{r['item_name']}%", r['item_name']))
        cheapest = cursor.fetchone()
        if cheapest:
            r["lowest_store"] = cheapest["store_name"]
            r["lowest_price"] = cheapest["price_paid"]

    conn.close()
    return rows

@app.post("/api/shopping-list")
def add_to_shopping_list(item: ShoppingItemCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Check price history for store suggestion
    cursor.execute("""
    SELECT store_name, price_paid FROM price_history 
    WHERE LOWER(item_name) LIKE LOWER(?) ORDER BY unit_price ASC LIMIT 1
    """, (f"%{item.item_name}%",))
    lowest = cursor.fetchone()
    lowest_store = lowest["store_name"] if lowest else None
    lowest_price = lowest["price_paid"] if lowest else None

    cursor.execute("""
    INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
    """, (item.inventory_id, item.item_name, item.preferred_brand, item.quantity_needed, item.unit, item.category, f"Buy from {lowest_store}" if lowest_store else "", lowest_price, lowest_store, item.added_by, now))

    log_activity(cursor, item.added_by, "shopping_add", f"{item.added_by} added '{item.item_name}' to shopping list.")
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/shopping-list/{item_id}/toggle-bought")
def toggle_bought(item_id: int, user_name: str = Query("Vipin")):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shopping_list WHERE id = ?", (item_id,))
    shop_item = cursor.fetchone()
    if not shop_item:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE shopping_list SET is_bought = 1 WHERE id = ?", (item_id,))

    # Restock matching inventory item if exists
    if shop_item["inventory_id"]:
        cursor.execute("""
        UPDATE inventory 
        SET quantity = quantity + ?, status = 'in_stock', updated_by = ?, updated_at = ?
        WHERE id = ?
        """, (shop_item["quantity_needed"], user_name, now, shop_item["inventory_id"]))

    log_activity(cursor, user_name, "shopping_bought", f"{user_name} purchased '{shop_item['item_name']}' -> restocked in pantry.")
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/shopping-list/{item_id}")
def delete_shopping_item(item_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"success": True}

# ----------------- Bill Scanner & OCR Endpoints -----------------
@app.post("/api/bills/upload-and-scan")
async def upload_and_scan_bill(file: UploadFile = File(...), user_name: str = Form("Vipin")):
    ext = os.path.splitext(file.filename)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_filename = f"bill_{timestamp}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, saved_filename)

    file_bytes = await file.read()
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Determine parser
    if ext == ".pdf":
        parsed_data = bill_parser.parse_bill_pdf(file_bytes)
    else:
        mime = file.content_type or ("image/png" if ext == ".png" else "image/jpeg")
        parsed_data = bill_parser.parse_bill_image(file_bytes, mime_type=mime)

    parsed_data["image_filename"] = saved_filename
    parsed_data["uploaded_by"] = user_name

    return parsed_data

@app.post("/api/bills/confirm-import")
def confirm_bill_import(payload: BillConfirmImport):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Save to bills table
    cursor.execute("""
    INSERT INTO bills (store_name, bill_date, total_amount, item_count, image_filename, raw_json, uploaded_by, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (payload.store_name, payload.bill_date, payload.total_amount, len(payload.items), payload.image_filename, "", payload.uploaded_by, now))
    bill_id = cursor.lastrowid

    updated_items = []
    created_items = []

    for item in payload.items:
        # Calculate unit price (per 1 kg or 1 L or 1 pc)
        unit_price = item.unit_price
        if not unit_price or unit_price == 0:
            if item.quantity > 0:
                unit_price = round(item.price_paid / item.quantity, 2)
            else:
                unit_price = item.price_paid

        # Insert into price_history
        cursor.execute("""
        INSERT INTO price_history (item_name, brand, store_name, quantity, unit, price_paid, unit_price, bill_date, bill_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item.name, item.brand, payload.store_name, item.quantity, item.unit, item.price_paid, unit_price, payload.bill_date, bill_id, now))

        # Check if item exists in inventory (matching name or brand)
        cursor.execute("""
        SELECT * FROM inventory 
        WHERE LOWER(name) = LOWER(?) OR LOWER(name) LIKE LOWER(?)
        LIMIT 1
        """, (item.name, f"%{item.name}%"))
        inv_item = cursor.fetchone()

        if inv_item:
            # Update existing inventory
            new_qty = inv_item["quantity"] + item.quantity
            cursor.execute("""
            UPDATE inventory 
            SET quantity = ?, status = 'in_stock', last_bought_price = ?, last_bought_store = ?, last_bought_date = ?, updated_by = ?, updated_at = ?
            WHERE id = ?
            """, (new_qty, item.price_paid, payload.store_name, payload.bill_date, payload.uploaded_by, now, inv_item["id"]))
            updated_items.append(inv_item["name"])

            # Check off from shopping list
            cursor.execute("""
            UPDATE shopping_list SET is_bought = 1 WHERE inventory_id = ? AND is_bought = 0
            """, (inv_item["id"],))
        else:
            # Create new inventory item
            cursor.execute("""
            INSERT INTO inventory (name, category, brand, preferred_brand, quantity, unit, status, min_threshold, storage_location, last_bought_price, last_bought_store, last_bought_date, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'in_stock', ?, 'Kitchen Pantry', ?, ?, ?, ?, ?)
            """, (item.name, item.category or "Other", item.brand, item.brand, item.quantity, item.unit, 1.0, item.price_paid, payload.store_name, payload.bill_date, payload.uploaded_by, now))
            new_id = cursor.lastrowid
            created_items.append(item.name)

            # Check off from shopping list by name
            cursor.execute("""
            UPDATE shopping_list SET is_bought = 1 WHERE LOWER(item_name) = LOWER(?) AND is_bought = 0
            """, (item.name,))

    log_activity(cursor, payload.uploaded_by, "bill_uploaded", 
                 f"{payload.uploaded_by} imported {payload.store_name} bill (₹{payload.total_amount:.1f}): {len(payload.items)} items logged & restocked.")

    conn.commit()
    conn.close()
    return {
        "success": True,
        "bill_id": bill_id,
        "items_updated": updated_items,
        "items_created": created_items
    }

# ----------------- Price Intelligence Endpoints -----------------
@app.get("/api/prices/compare")
def compare_prices(search: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()

    query = """
    SELECT item_name, brand, store_name, quantity, unit, price_paid, unit_price, bill_date
    FROM price_history
    """
    params = []
    if search:
        query += " WHERE LOWER(item_name) LIKE LOWER(?) OR LOWER(brand) LIKE LOWER(?)"
        params.append(f"%{search}%")
        params.append(f"%{search}%")
    query += " ORDER BY item_name ASC, unit_price ASC"

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]

    # Group by product/item_name
    grouped = {}
    for r in rows:
        key = r["item_name"]
        if key not in grouped:
            grouped[key] = {
                "item_name": key,
                "brand": r["brand"],
                "unit": r["unit"],
                "records": [],
                "lowest_price": float("inf"),
                "lowest_store": None,
                "highest_price": 0.0,
                "highest_store": None,
            }
        grouped[key]["records"].append(r)
        if r["unit_price"] and r["unit_price"] < grouped[key]["lowest_price"]:
            grouped[key]["lowest_price"] = r["unit_price"]
            grouped[key]["lowest_store"] = r["store_name"]
        if r["unit_price"] and r["unit_price"] > grouped[key]["highest_price"]:
            grouped[key]["highest_price"] = r["unit_price"]
            grouped[key]["highest_store"] = r["store_name"]

    # Calculate savings potential
    result = list(grouped.values())
    for item in result:
        if item["lowest_price"] == float("inf"):
            item["lowest_price"] = 0.0
        if item["highest_price"] > item["lowest_price"] and item["lowest_price"] > 0:
            item["savings_percent"] = round(((item["highest_price"] - item["lowest_price"]) / item["highest_price"]) * 100, 1)
        else:
            item["savings_percent"] = 0.0

    conn.close()
    return result

# ----------------- Product Enrichment -----------------
@app.get("/api/enrich-product")
def enrich_product(query: str = Query(..., min_length=2)):
    details = bill_parser.enrich_product_details(query)
    return details

# ----------------- Activity Log -----------------
@app.get("/api/activity")
def get_activity():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 50")
    logs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return logs

# ----------------- Network & Phone Connection Info -----------------
@app.get("/api/network-info")
def get_network_info():
    ip = get_local_ip()
    port = 8000
    return {
        "local_ip": ip,
        "port": port,
        "mobile_url": f"http://{ip}:{port}",
        "device_name": socket.gethostname()
    }

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Serve static frontend
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"status": "Frontend building..."})

if __name__ == "__main__":
    import uvicorn
    print("\n==========================================")
    print(" 🚀 SmartPantry is running!")
    print(f" 💻 Open on PC:     http://localhost:8000")
    print(f" 📱 Open on Mobile: http://{get_local_ip()}:8000")
    print("==========================================\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
