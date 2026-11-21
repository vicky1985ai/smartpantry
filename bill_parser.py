import os
import json
import base64
import re
from datetime import datetime
import httpx
import fitz  # PyMuPDF

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

def clean_json_response(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    return json.loads(text)

def parse_bill_image(file_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Parses a grocery bill image (Blinkit, Zepto, Instamart, JioMart, BigBasket, DMart, receipt)
    using Gemini 3.1 Flash Lite Vision.
    """
    b64_data = base64.b64encode(file_bytes).decode("utf-8")
    
    prompt = """
You are an expert Indian grocery bill & invoice analyzer.
Analyze this grocery bill / order screenshot / receipt (could be from Blinkit, Zepto, Swiggy Instamart, JioMart, BigBasket, DMart, More, or a local store).

Extract all details into a clean, strictly valid JSON object with the following schema:
{
  "store_name": "Store/App Name (e.g., Blinkit, Zepto, Instamart, JioMart, BigBasket, DMart, Local Kirana)",
  "bill_date": "YYYY-MM-DD or estimated recent date",
  "total_amount": 0.0,
  "currency": "INR",
  "items": [
    {
      "name": "Full Product Name (e.g., Tata Sampann Unpolished Toor Dal 1kg)",
      "brand": "Detected Brand (e.g., Tata Sampann, Amul, Fortune, Aashirvaad)",
      "category": "One of: Grains & Dals, Dairy & Bakery, Spices & Cooking Oils, Fresh Produce, Snacks & Beverages, Cleaning & Personal Care, Other",
      "quantity": 1.0,
      "unit": "One of: kg, g, L, ml, pcs, pack",
      "price_paid": 0.0,
      "mrp": 0.0,
      "unit_price": 0.0
    }
  ]
}

Guidelines:
1. Normalize units: 1000g -> 1kg, 500ml -> 0.5L (or keep 500g with unit 'g').
2. Calculate unit_price per 1 kg or 1 L or 1 piece whenever feasible.
3. If brand is not explicitly mentioned, infer from common Indian grocery brands (Amul, Mother Dairy, Fortune, Tata, Surf Excel, Vim, Maggi, Aashirvaad, etc.).
4. Return ONLY valid JSON, no conversational markdown.
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }

    try:
        with httpx.Client(timeout=40.0) as client:
            resp = client.post(GEMINI_URL, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                return clean_json_response(raw_text)
            else:
                return {
                    "error": f"Gemini API returned status {resp.status_code}: {resp.text[:200]}",
                    "store_name": "Unknown",
                    "bill_date": datetime.now().strftime("%Y-%m-%d"),
                    "total_amount": 0.0,
                    "items": []
                }
    except Exception as e:
        return {
            "error": str(e),
            "store_name": "Unknown",
            "bill_date": datetime.now().strftime("%Y-%m-%d"),
            "total_amount": 0.0,
            "items": []
        }

def parse_bill_pdf(file_bytes: bytes) -> dict:
    """
    Handles PDF bills (such as invoices downloaded from BigBasket, Blinkit, or JioMart).
    Extracts text first; if text is rich, parses with Gemini text; else renders page 1 to image.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"

    # If PDF contains extractable text:
    if len(full_text.strip()) > 50:
        prompt = f"""
Analyze this Indian grocery invoice text:
---
{full_text[:4000]}
---

Extract the invoice into JSON:
{{
  "store_name": "Store/App Name",
  "bill_date": "YYYY-MM-DD",
  "total_amount": 0.0,
  "currency": "INR",
  "items": [
    {{
      "name": "Full Product Name",
      "brand": "Detected Brand",
      "category": "Grains & Dals | Dairy & Bakery | Spices & Cooking Oils | Fresh Produce | Snacks & Beverages | Cleaning & Personal Care | Other",
      "quantity": 1.0,
      "unit": "kg | g | L | ml | pcs | pack",
      "price_paid": 0.0,
      "mrp": 0.0,
      "unit_price": 0.0
    }}
  ]
}}
Return ONLY valid JSON.
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        }
        try:
            with httpx.Client(timeout=35.0) as client:
                resp = client.post(GEMINI_URL, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return clean_json_response(raw_text)
        except Exception:
            pass

    # Fallback: render first page as PNG image and pass to image parser
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=150)
    img_bytes = pix.tobytes("png")
    return parse_bill_image(img_bytes, mime_type="image/png")

def enrich_product_details(query: str) -> dict:
    """
    Takes a short user query (e.g. 'Fortune mustard oil' or 'Aashirvaad atta')
    and returns rich standardized metadata (brand, category, typical pack size, unit, estimated price).
    """
    prompt = f"""
Standardize this Indian grocery item query: "{query}"

Return a strictly valid JSON object with:
{{
  "name": "Proper standard name (e.g., Fortune Kachi Ghani Mustard Oil)",
  "brand": "Identified brand (e.g., Fortune)",
  "category": "One of: Grains & Dals, Dairy & Bakery, Spices & Cooking Oils, Fresh Produce, Snacks & Beverages, Cleaning & Personal Care, Other",
  "default_quantity": 1.0,
  "default_unit": "kg or L or g or ml or pcs or pack",
  "storage_location": "Kitchen Pantry or Fridge or Store Room",
  "estimated_price": 0.0,
  "icon_emoji": "a suitable emoji like 🌾, 🥛, 🧈, 🛢️, 🧂, ☕, 🧼"
}}
Return ONLY JSON.
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"}
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(GEMINI_URL, json=payload)
            if resp.status_code == 200:
                raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                return clean_json_response(raw_text)
    except Exception as e:
        pass

    # Simple fallback heuristic if offline
    return {
        "name": query.strip().title(),
        "brand": query.split()[0].title() if " " in query else "",
        "category": "Grains & Dals",
        "default_quantity": 1.0,
        "default_unit": "kg",
        "storage_location": "Kitchen Pantry",
        "estimated_price": 100.0,
        "icon_emoji": "🛒"
    }
