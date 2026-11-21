# SmartPantry (घर की रसोई और बजट साथी)
### Dual-User Home Grocery Management & Price Intelligence System

Designed specifically to eliminate friction in dual-consumption households:
1. **Never forget who consumed what** — 1-tap quick actions for both **Vipin** and **Wife**.
2. **Never guess what is needed** — When stock drops low, it automatically queues into the live **Shared Shopping List**.
3. **Remember preferred brands** — ⭐ Star-mark preferred brands (e.g., Tata Sampann for Toor Dal, Amul for Butter) so nobody buys the wrong brand.
4. **AI Bill & Screenshot Scanner** — Upload or photograph receipts from Blinkit, Zepto, Swiggy Instamart, JioMart, BigBasket, DMart, or local kiranas; Gemini AI extracts all items, prices, and quantities automatically.
5. **Price & Vendor Intelligence** — Compares normalized unit prices (₹/kg or ₹/L) across stores to reveal where each grocery item is cheapest.

---

## 🚀 Quick Start

1. Double-click **`run.bat`** (or run `python server.py`).
2. Open your browser:
   - **On PC / Laptop:** [http://localhost:8000](http://localhost:8000)
   - **On Mobile Phones (Android / iPhone):** [http://10.26.205.136:8000](http://10.26.205.136:8000)
     *(Or click "Phone Sync" in the top bar to scan the QR code with your phone camera!)*

> **📱 Mobile Tip:** On Chrome or Safari, tap **"Add to Home Screen"** to install it as an app with full-screen experience and zero app store hassles.

---

## 🔑 Core Features & Workflow

### 1. Active User Switcher (👤 Vipin | 👩 Wife)
- Switch with 1 tap at the top right.
- Every action (consuming an item, adding to shopping list, importing bills, star-marking a brand) logs who did it in the **Family Activity Log**.

### 2. Zero-Friction Pantry Management (हमारा सामान)
- Visual cards with color-coded stock tags:
  - 🟢 **In Stock** (Plenty)
  - 🟡 **Running Low** (Triggers replenishment)
  - 🔴 **Empty / Out of Stock** (Urgent)
- **1-Tap Quick Action Buttons:**
  - `[-1 Unit]` : Used some
  - `[Mark Low]` : Automatically queues to Shopping List with recommended store!
  - `[Empty]` : Marks out of stock and queues to Shopping List immediately.
- **Smart AI Auto-Fill:** When adding a new item, just type e.g. "Fortune mustard oil" and click **AI Fill** — it automatically fills category, standard pack size (1L), estimated price, and brand!

### 3. Star-Marked Preferred Brands (⭐ Brand Preference)
- Click on any item's brand pill to star-mark your family's favorite brand.
- Add an optional reason (e.g. *"Wife's favorite taste"*, *"Cooks faster"*).
- The preferred brand badge is prominently shown on the shopping list so nobody accidentally buys an inferior substitute.

### 4. Live Shared Shopping List (खरीददारी सूची)
- Real-time list of what is needed.
- Shows:
  - Item name + Quantity needed
  - **Preferred Brand ⭐ badge**
  - **Price Radar Tip:** e.g., *"Cheapest at DMart: ₹175 vs Blinkit: ₹195"*
- Tap `✓` to mark bought: Automatically restocks the item in your pantry and clears it from the list.

### 5. AI Bill & Screenshot Scanner (बिल स्कैनर)
- Accepts photos, screenshots, and PDFs from:
  - **Blinkit**
  - **Zepto**
  - **Swiggy Instamart**
  - **JioMart**
  - **BigBasket**
  - **DMart / More / Supermarket printed receipts**
- Powered by Gemini AI Vision.
- Review extracted items, quantities, and prices in an interactive modal.
- Click **"Confirm & Sync Everything"**:
  1. Restocks pantry inventory
  2. Updates Price Radar intelligence records
  3. Clears matching items from the shopping list

### 6. Price Radar & Vendor Intelligence (कहाँ सबसे सस्ता?)
- Compares past purchases across stores.
- Automatically calculates **normalized unit prices** (₹/kg or ₹/L) to prevent misleading packaging tricks.
- Highlights the **Cheapest Store** and calculates household percentage savings.

---

## 🛠️ Technology Stack
- **Backend:** Python FastAPI + SQLite (`smart_pantry.db`)
- **AI Vision Engine:** Gemini Multimodal Flash Vision (`gemini-3.1-flash-lite`)
- **PDF Parser:** PyMuPDF (`fitz`)
- **Frontend:** Responsive Mobile-First Single-Page Application (Tailwind CSS + Lucide Icons + QRCode.js)
