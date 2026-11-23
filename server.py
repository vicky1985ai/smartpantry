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
from sqlalchemy import text

import database
from database import engine, log_activity
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
    action: str  # "decrement", "increment", "mark_low", "mark_out"
    amount: Optional[float] = 1.0
    user_name: str = "Vipin"

class StarBrandRequest(BaseModel):
    preferred_brand: Optional[str] = None
    brand_reason: Optional[str] = ""
    user_name: str = "Vipin"

class CategoryCreate(BaseModel):
    name: str
    icon: Optional[str] = "📦"

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

# ----------------- Categories Endpoints -----------------
@app.get("/api/categories")
def list_categories():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name, icon FROM categories ORDER BY name ASC")).fetchall()
        return [{"id": r[0], "name": r[1], "icon": r[2] or "📦"} for r in rows]

@app.post("/api/categories")
def create_category(cat: CategoryCreate):
    name = cat.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        existing = conn.execute(text("SELECT id FROM categories WHERE LOWER(name) = LOWER(:name)"), {"name": name}).fetchone()
        if existing:
            return {"success": True, "id": existing[0], "name": name, "message": "Category already exists"}
        conn.execute(text("INSERT INTO categories (name, icon, created_at) VALUES (:name, :icon, :created_at)"),
                     {"name": name, "icon": cat.icon or "📦", "created_at": now})
    return {"success": True, "name": name}

@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM categories WHERE id = :id"), {"id": cat_id})
    return {"success": True}

# ----------------- Inventory Endpoints -----------------
@app.get("/api/inventory")
def list_inventory(category: Optional[str] = None, status: Optional[str] = None):
    with engine.connect() as conn:
        query = "SELECT * FROM inventory WHERE 1=1"
        params = {}
        if category and category != "All":
            query += " AND category = :category"
            params["category"] = category
        if status and status != "All":
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY status ASC, name ASC"

        rows = conn.execute(text(query), params).mappings().fetchall()
        items = [dict(r) for r in rows]

        for item in items:
            lowest = conn.execute(text("""
                SELECT store_name, price_paid, unit_price
                FROM price_history
                WHERE LOWER(item_name) LIKE LOWER(:term)
                ORDER BY unit_price ASC
                LIMIT 1
            """), {"term": f"%{item['name']}%"}).mappings().fetchone()

            if lowest:
                item["cheapest_store"] = lowest["store_name"]
                item["cheapest_price"] = lowest["price_paid"]
                item["cheapest_unit_price"] = lowest["unit_price"]
            else:
                item["cheapest_store"] = item.get("last_bought_store") or "-"
                item["cheapest_price"] = item.get("last_bought_price") or 0.0
                item["cheapest_unit_price"] = 0.0

        return items

@app.get("/api/inventory/empty-and-low")
def get_empty_and_low():
    """
    Returns empty or low items that are NOT yet in the active shopping list,
    so the user can choose which ones to add.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT i.* FROM inventory i
            WHERE i.status IN ('low', 'out_of_stock')
            AND i.name NOT IN (SELECT item_name FROM shopping_list WHERE is_bought = 0)
            ORDER BY i.status ASC, i.name ASC
        """)).mappings().fetchall()
        return [dict(r) for r in rows]

@app.post("/api/inventory")
def create_inventory_item(item: InventoryItemCreate):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        # Also auto-create category in categories table if it's new
        cat_name = item.category.strip()
        existing_cat = conn.execute(text("SELECT id FROM categories WHERE LOWER(name) = LOWER(:name)"), {"name": cat_name}).fetchone()
        if not existing_cat and cat_name:
            conn.execute(text("INSERT INTO categories (name, icon, created_at) VALUES (:name, '📦', :created_at)"),
                         {"name": cat_name, "created_at": now})

        conn.execute(text("""
        INSERT INTO inventory (name, category, brand, preferred_brand, brand_reason, quantity, unit, status, min_threshold, storage_location, last_bought_price, last_bought_store, updated_by, updated_at)
        VALUES (:name, :category, :brand, :preferred_brand, :brand_reason, :quantity, :unit, :status, :min_threshold, :storage_location, :last_bought_price, :last_bought_store, :updated_by, :updated_at)
        """), {
            "name": item.name, "category": item.category, "brand": item.brand,
            "preferred_brand": item.preferred_brand, "brand_reason": item.brand_reason,
            "quantity": item.quantity, "unit": item.unit, "status": item.status,
            "min_threshold": item.min_threshold, "storage_location": item.storage_location,
            "last_bought_price": item.last_bought_price, "last_bought_store": item.last_bought_store,
            "updated_by": item.updated_by, "updated_at": now
        })

        # RULE: ONLY auto-add to shopping list if item is STAR-MARKED (⭐ preferred staple)!
        is_starred = bool(item.preferred_brand and item.preferred_brand.strip())
        if is_starred and item.status in ("low", "out_of_stock"):
            conn.execute(text("""
            INSERT INTO shopping_list (item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
            VALUES (:item_name, :preferred_brand, :quantity_needed, :unit, :category, :store_recommendation, :lowest_price, :lowest_store, 0, :added_by, :created_at)
            """), {
                "item_name": item.name, "preferred_brand": item.preferred_brand,
                "quantity_needed": item.min_threshold, "unit": item.unit, "category": item.category,
                "store_recommendation": f"Buy from {item.last_bought_store or 'store'}",
                "lowest_price": item.last_bought_price, "lowest_store": item.last_bought_store,
                "added_by": f"{item.updated_by} (⭐ Staple)", "created_at": now
            })

        log_activity(conn, item.updated_by, "inventory_add", f"Added '{item.name}' ({item.quantity} {item.unit}) to {item.storage_location}.")
    return {"success": True}

@app.post("/api/inventory/{item_id}/consume")
def consume_inventory_item(item_id: int, req: ConsumeRequest):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        item = conn.execute(text("SELECT * FROM inventory WHERE id = :id"), {"id": item_id}).mappings().fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        new_qty = item["quantity"]
        new_status = item["status"]
        amt = req.amount or 1.0

        if req.action == "increment":
            # Increase quantity
            new_qty = item["quantity"] + amt
            if new_qty > item["min_threshold"]:
                new_status = "in_stock"
            action_desc = f"{req.user_name} increased '{item['name']}' by +{amt} {item['unit']} (Now {new_qty} {item['unit']})."
        elif req.action == "decrement":
            # Decrease quantity
            new_qty = max(0.0, round(item["quantity"] - amt, 2))
            if new_qty == 0:
                new_status = "out_of_stock"
            elif new_qty <= item["min_threshold"]:
                new_status = "low"
            else:
                new_status = "in_stock"
            action_desc = f"{req.user_name} used {amt} {item['unit']} of '{item['name']}' (Now {new_qty} {item['unit']})."
        elif req.action == "mark_low":
            new_status = "low"
            new_qty = min(item["quantity"], item["min_threshold"])
            action_desc = f"{req.user_name} marked '{item['name']}' as LOW stock."
        elif req.action == "mark_out":
            new_status = "out_of_stock"
            new_qty = 0.0
            action_desc = f"{req.user_name} marked '{item['name']}' as EMPTY."
        else:
            raise HTTPException(status_code=400, detail="Invalid action")

        conn.execute(text("""
        UPDATE inventory SET quantity = :quantity, status = :status, updated_by = :updated_by, updated_at = :updated_at
        WHERE id = :id
        """), {"quantity": new_qty, "status": new_status, "updated_by": req.user_name, "updated_at": now, "id": item_id})

        # CRITICAL USER RULE:
        # Only STAR-MARKED items (⭐ preferred staples) automatically enter the Shopping List!
        # Non-starred items wait for user to explicitly pick them from the "Empty & Low" list.
        is_starred = bool(item["preferred_brand"] and item["preferred_brand"].strip())
        if is_starred and new_status in ("low", "out_of_stock"):
            existing = conn.execute(text("SELECT id FROM shopping_list WHERE LOWER(item_name) = LOWER(:name) AND is_bought = 0"),
                                    {"name": item["name"]}).fetchone()
            if not existing:
                lowest = conn.execute(text("""
                    SELECT store_name, price_paid FROM price_history 
                    WHERE LOWER(item_name) LIKE LOWER(:term) ORDER BY unit_price ASC LIMIT 1
                """), {"term": f"%{item['name']}%"}).mappings().fetchone()
                l_store = lowest["store_name"] if lowest else item["last_bought_store"]
                l_price = lowest["price_paid"] if lowest else item["last_bought_price"]

                conn.execute(text("""
                INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
                VALUES (:inv_id, :name, :brand, :qty, :unit, :cat, :store_rec, :lowest_price, :lowest_store, 0, :added_by, :created_at)
                """), {
                    "inv_id": item_id, "name": item["name"], "brand": item["preferred_brand"],
                    "qty": item["min_threshold"], "unit": item["unit"], "cat": item["category"],
                    "store_rec": f"Buy from {l_store or 'store'}", "lowest_price": l_price,
                    "lowest_store": l_store, "added_by": f"{req.user_name} (⭐ Auto)", "created_at": now
                })

        log_activity(conn, req.user_name, "consumed", action_desc)

    return {"success": True, "new_quantity": new_qty, "new_status": new_status}

@app.post("/api/inventory/{item_id}/star-brand")
def star_brand(item_id: int, req: StarBrandRequest):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        item = conn.execute(text("SELECT * FROM inventory WHERE id = :id"), {"id": item_id}).mappings().fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        # Check if removing star mark
        pref = req.preferred_brand.strip() if req.preferred_brand else ""
        if not pref or pref.upper() == "UNSTAR":
            # Remove star mark
            conn.execute(text("""
            UPDATE inventory SET preferred_brand = NULL, brand_reason = NULL, updated_by = :user, updated_at = :now
            WHERE id = :id
            """), {"user": req.user_name, "now": now, "id": item_id})
            log_activity(conn, req.user_name, "unstar_brand", f"{req.user_name} removed star mark ⭐ from '{item['name']}'.")
            return {"success": True, "action": "unstarred"}

        # Set or update star mark
        conn.execute(text("""
        UPDATE inventory SET preferred_brand = :pref, brand_reason = :reason, updated_by = :user, updated_at = :now
        WHERE id = :id
        """), {"pref": pref, "reason": req.brand_reason or "", "user": req.user_name, "now": now, "id": item_id})

        # Update in active shopping list as well
        conn.execute(text("""
        UPDATE shopping_list SET preferred_brand = :pref
        WHERE (inventory_id = :id OR LOWER(item_name) = LOWER(:name)) AND is_bought = 0
        """), {"pref": pref, "id": item_id, "name": item["name"]})

        # If item is currently low or out_of_stock, now that it is starred, add to shopping list!
        if item["status"] in ("low", "out_of_stock"):
            existing = conn.execute(text("SELECT id FROM shopping_list WHERE LOWER(item_name) = LOWER(:name) AND is_bought = 0"),
                                    {"name": item["name"]}).fetchone()
            if not existing:
                conn.execute(text("""
                INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, is_bought, added_by, created_at)
                VALUES (:id, :name, :pref, :qty, :unit, :cat, 0, :user, :now)
                """), {
                    "id": item_id, "name": item["name"], "pref": pref,
                    "qty": item["min_threshold"], "unit": item["unit"], "cat": item["category"],
                    "user": f"{req.user_name} (⭐ Starred)", "now": now
                })

        log_activity(conn, req.user_name, "star_brand", f"{req.user_name} set preferred brand for '{item['name']}' to ⭐ {pref}.")

    return {"success": True, "action": "starred"}

@app.delete("/api/inventory/{item_id}")
def delete_inventory_item(item_id: int):
    with engine.begin() as conn:
        item = conn.execute(text("SELECT name FROM inventory WHERE id = :id"), {"id": item_id}).fetchone()
        if item:
            conn.execute(text("DELETE FROM inventory WHERE id = :id"), {"id": item_id})
            conn.execute(text("DELETE FROM shopping_list WHERE inventory_id = :id"), {"id": item_id})
            log_activity(conn, "User", "inventory_delete", f"Removed '{item[0]}' from pantry.")
    return {"success": True}

# ----------------- Shopping List Endpoints -----------------
@app.get("/api/shopping-list")
def get_shopping_list():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM shopping_list WHERE is_bought = 0 ORDER BY created_at DESC")).mappings().fetchall()
        items = [dict(r) for r in rows]

        for item in items:
            cheapest = conn.execute(text("""
                SELECT store_name, price_paid, unit_price
                FROM price_history
                WHERE LOWER(item_name) LIKE LOWER(:term)
                ORDER BY unit_price ASC
                LIMIT 1
            """), {"term": f"%{item['item_name']}%"}).mappings().fetchone()
            if cheapest:
                item["lowest_store"] = cheapest["store_name"]
                item["lowest_price"] = cheapest["price_paid"]

        return items

@app.post("/api/shopping-list")
def add_to_shopping_list(item: ShoppingItemCreate):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        lowest = conn.execute(text("""
            SELECT store_name, price_paid FROM price_history 
            WHERE LOWER(item_name) LIKE LOWER(:term) ORDER BY unit_price ASC LIMIT 1
        """), {"term": f"%{item.item_name}%"}).mappings().fetchone()
        l_store = lowest["store_name"] if lowest else None
        l_price = lowest["price_paid"] if lowest else None

        conn.execute(text("""
        INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
        VALUES (:inv_id, :name, :pref, :qty, :unit, :cat, :store_rec, :lowest_price, :lowest_store, 0, :user, :now)
        """), {
            "inv_id": item.inventory_id, "name": item.item_name, "pref": item.preferred_brand or "",
            "qty": item.quantity_needed, "unit": item.unit, "cat": item.category or "Other",
            "store_rec": f"Buy from {l_store}" if l_store else "", "lowest_price": l_price,
            "lowest_store": l_store, "user": item.added_by, "now": now
        })
        log_activity(conn, item.added_by, "shopping_add", f"{item.added_by} added '{item.item_name}' to shopping list.")
    return {"success": True}

@app.post("/api/shopping-list/add-from-inventory/{item_id}")
def add_from_inventory_to_shopping(item_id: int, user_name: str = Query("Vipin")):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        item = conn.execute(text("SELECT * FROM inventory WHERE id = :id"), {"id": item_id}).mappings().fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Inventory item not found")

        # Check if already in shopping list
        existing = conn.execute(text("SELECT id FROM shopping_list WHERE LOWER(item_name) = LOWER(:name) AND is_bought = 0"),
                                {"name": item["name"]}).fetchone()
        if existing:
            return {"success": True, "message": "Already in shopping list"}

        lowest = conn.execute(text("""
            SELECT store_name, price_paid FROM price_history 
            WHERE LOWER(item_name) LIKE LOWER(:term) ORDER BY unit_price ASC LIMIT 1
        """), {"term": f"%{item['name']}%"}).mappings().fetchone()
        l_store = lowest["store_name"] if lowest else item["last_bought_store"]
        l_price = lowest["price_paid"] if lowest else item["last_bought_price"]

        conn.execute(text("""
        INSERT INTO shopping_list (inventory_id, item_name, preferred_brand, quantity_needed, unit, category, store_recommendation, lowest_price, lowest_store, is_bought, added_by, created_at)
        VALUES (:inv_id, :name, :pref, :qty, :unit, :cat, :store_rec, :lowest_price, :lowest_store, 0, :user, :now)
        """), {
            "inv_id": item_id, "name": item["name"], "pref": item["preferred_brand"] or "",
            "qty": item["min_threshold"], "unit": item["unit"], "cat": item["category"],
            "store_rec": f"Buy from {l_store or 'store'}", "lowest_price": l_price,
            "lowest_store": l_store, "user": user_name, "now": now
        })
        log_activity(conn, user_name, "shopping_add", f"{user_name} added '{item['name']}' from pantry to shopping list.")
    return {"success": True}

@app.post("/api/shopping-list/{item_id}/toggle-bought")
def toggle_bought(item_id: int, user_name: str = Query("Vipin")):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        shop_item = conn.execute(text("SELECT * FROM shopping_list WHERE id = :id"), {"id": item_id}).mappings().fetchone()
        if not shop_item:
            raise HTTPException(status_code=404, detail="Item not found")

        conn.execute(text("UPDATE shopping_list SET is_bought = 1 WHERE id = :id"), {"id": item_id})

        # Restock matching inventory item
        if shop_item["inventory_id"]:
            conn.execute(text("""
            UPDATE inventory 
            SET quantity = quantity + :qty, status = 'in_stock', updated_by = :user, updated_at = :now
            WHERE id = :id
            """), {"qty": shop_item["quantity_needed"], "user": user_name, "now": now, "id": shop_item["inventory_id"]})
        else:
            conn.execute(text("""
            UPDATE inventory 
            SET quantity = quantity + :qty, status = 'in_stock', updated_by = :user, updated_at = :now
            WHERE LOWER(name) = LOWER(:name)
            """), {"qty": shop_item["quantity_needed"], "user": user_name, "now": now, "name": shop_item["item_name"]})

        log_activity(conn, user_name, "shopping_bought", f"{user_name} purchased '{shop_item['item_name']}' -> restocked in pantry.")
    return {"success": True}

@app.delete("/api/shopping-list/{item_id}")
def delete_shopping_item(item_id: int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM shopping_list WHERE id = :id"), {"id": item_id})
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
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        # Save bill record
        conn.execute(text("""
        INSERT INTO bills (store_name, bill_date, total_amount, item_count, image_filename, raw_json, uploaded_by, created_at)
        VALUES (:store, :date, :amount, :count, :img, '', :user, :now)
        """), {
            "store": payload.store_name, "date": payload.bill_date, "amount": payload.total_amount,
            "count": len(payload.items), "img": payload.image_filename, "user": payload.uploaded_by, "now": now
        })

        updated_items = []
        created_items = []

        for item in payload.items:
            unit_price = item.unit_price
            if not unit_price or unit_price == 0:
                unit_price = round(item.price_paid / item.quantity, 2) if item.quantity > 0 else item.price_paid

            # Add to price history
            conn.execute(text("""
            INSERT INTO price_history (item_name, brand, store_name, quantity, unit, price_paid, unit_price, bill_date, created_at)
            VALUES (:name, :brand, :store, :qty, :unit, :price, :u_price, :date, :now)
            """), {
                "name": item.name, "brand": item.brand or "", "store": payload.store_name,
                "qty": item.quantity, "unit": item.unit, "price": item.price_paid,
                "u_price": unit_price, "date": payload.bill_date, "now": now
            })

            # Check if exists in inventory
            inv = conn.execute(text("SELECT * FROM inventory WHERE LOWER(name) = LOWER(:name) OR LOWER(name) LIKE LOWER(:term) LIMIT 1"),
                               {"name": item.name, "term": f"%{item.name}%"}).mappings().fetchone()

            if inv:
                new_qty = inv["quantity"] + item.quantity
                conn.execute(text("""
                UPDATE inventory 
                SET quantity = :qty, status = 'in_stock', last_bought_price = :price, last_bought_store = :store, last_bought_date = :date, updated_by = :user, updated_at = :now
                WHERE id = :id
                """), {
                    "qty": new_qty, "price": item.price_paid, "store": payload.store_name,
                    "date": payload.bill_date, "user": payload.uploaded_by, "now": now, "id": inv["id"]
                })
                updated_items.append(inv["name"])
                conn.execute(text("UPDATE shopping_list SET is_bought = 1 WHERE inventory_id = :id AND is_bought = 0"), {"id": inv["id"]})
            else:
                conn.execute(text("""
                INSERT INTO inventory (name, category, brand, preferred_brand, quantity, unit, status, min_threshold, storage_location, last_bought_price, last_bought_store, last_bought_date, updated_by, updated_at)
                VALUES (:name, :cat, :brand, :pref, :qty, :unit, 'in_stock', 1.0, 'Kitchen Pantry', :price, :store, :date, :user, :now)
                """), {
                    "name": item.name, "cat": item.category or "Other", "brand": item.brand or "",
                    "pref": item.brand or "", "qty": item.quantity, "unit": item.unit,
                    "price": item.price_paid, "store": payload.store_name, "date": payload.bill_date,
                    "user": payload.uploaded_by, "now": now
                })
                created_items.append(item.name)
                conn.execute(text("UPDATE shopping_list SET is_bought = 1 WHERE LOWER(item_name) = LOWER(:name) AND is_bought = 0"), {"name": item.name})

        log_activity(conn, payload.uploaded_by, "bill_uploaded",
                     f"{payload.uploaded_by} imported {payload.store_name} bill (₹{payload.total_amount:.1f}): {len(payload.items)} items logged & restocked.")

    return {
        "success": True,
        "items_updated": updated_items,
        "items_created": created_items
    }

# ----------------- Price Intelligence Endpoints -----------------
@app.get("/api/prices/compare")
def compare_prices(search: Optional[str] = None):
    with engine.connect() as conn:
        query = "SELECT item_name, brand, store_name, quantity, unit, price_paid, unit_price, bill_date FROM price_history"
        params = {}
        if search:
            query += " WHERE LOWER(item_name) LIKE LOWER(:term) OR LOWER(brand) LIKE LOWER(:term)"
            params["term"] = f"%{search}%"
        query += " ORDER BY item_name ASC, unit_price ASC"

        rows = conn.execute(text(query), params).mappings().fetchall()

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
            grouped[key]["records"].append(dict(r))
            if r["unit_price"] and r["unit_price"] < grouped[key]["lowest_price"]:
                grouped[key]["lowest_price"] = r["unit_price"]
                grouped[key]["lowest_store"] = r["store_name"]
            if r["unit_price"] and r["unit_price"] > grouped[key]["highest_price"]:
                grouped[key]["highest_price"] = r["unit_price"]
                grouped[key]["highest_store"] = r["store_name"]

        result = list(grouped.values())
        for item in result:
            if item["lowest_price"] == float("inf"):
                item["lowest_price"] = 0.0
            if item["highest_price"] > item["lowest_price"] and item["lowest_price"] > 0:
                item["savings_percent"] = round(((item["highest_price"] - item["lowest_price"]) / item["highest_price"]) * 100, 1)
            else:
                item["savings_percent"] = 0.0

        return result

# ----------------- Product Enrichment -----------------
@app.get("/api/enrich-product")
def enrich_product(query: str = Query(..., min_length=2)):
    return bill_parser.enrich_product_details(query)

# ----------------- Activity Log -----------------
@app.get("/api/activity")
def get_activity():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM activity_log ORDER BY id DESC LIMIT 50")).mappings().fetchall()
        return [dict(r) for r in rows]

# ----------------- Backup Export & Import -----------------
@app.get("/api/backup/export")
def export_backup():
    with engine.connect() as conn:
        inv = [dict(r) for r in conn.execute(text("SELECT * FROM inventory")).mappings().fetchall()]
        shop = [dict(r) for r in conn.execute(text("SELECT * FROM shopping_list")).mappings().fetchall()]
        prices = [dict(r) for r in conn.execute(text("SELECT * FROM price_history")).mappings().fetchall()]
        cats = [dict(r) for r in conn.execute(text("SELECT * FROM categories")).mappings().fetchall()]
        return {
            "version": "1.0",
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "inventory": inv,
            "shopping_list": shop,
            "price_history": prices,
            "categories": cats
        }

@app.post("/api/backup/import")
def import_backup(data: dict):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        # Import categories
        for c in data.get("categories", []):
            conn.execute(text("INSERT OR IGNORE INTO categories (name, icon, created_at) VALUES (:name, :icon, :created_at)"),
                         {"name": c["name"], "icon": c.get("icon", "📦"), "created_at": now})

        # Import inventory
        for item in data.get("inventory", []):
            conn.execute(text("""
            INSERT INTO inventory (name, category, brand, preferred_brand, brand_reason, quantity, unit, status, min_threshold, storage_location, last_bought_price, last_bought_store, last_bought_date, updated_by, updated_at)
            VALUES (:name, :category, :brand, :preferred_brand, :brand_reason, :quantity, :unit, :status, :min_threshold, :storage_location, :last_bought_price, :last_bought_store, :last_bought_date, :updated_by, :updated_at)
            """), {
                "name": item["name"], "category": item.get("category", "Other"),
                "brand": item.get("brand", ""), "preferred_brand": item.get("preferred_brand"),
                "brand_reason": item.get("brand_reason"), "quantity": item.get("quantity", 1.0),
                "unit": item.get("unit", "kg"), "status": item.get("status", "in_stock"),
                "min_threshold": item.get("min_threshold", 1.0),
                "storage_location": item.get("storage_location", "Kitchen Pantry"),
                "last_bought_price": item.get("last_bought_price"),
                "last_bought_store": item.get("last_bought_store"),
                "last_bought_date": item.get("last_bought_date"),
                "updated_by": item.get("updated_by", "Backup"), "updated_at": now
            })

        log_activity(conn, "User", "backup_import", "Restored data from backup file.")
    return {"success": True, "message": "Backup restored successfully"}

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
