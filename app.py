from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sqlite3
import hashlib
import os
import re

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'))
CORS(app)  # Allow requests from admin.html and customer.html opened as local files

DB_PATH = "trendtees.db"

# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT,
            price       REAL NOT NULL,
            stock       INTEGER NOT NULL DEFAULT 0,
            img_src     TEXT,
            orders_placed INTEGER NOT NULL DEFAULT 0,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  TEXT NOT NULL,
            customer_name TEXT,
            customer_mobile TEXT,
            qty         INTEGER NOT NULL DEFAULT 1,
            status      TEXT NOT NULL DEFAULT 'Pending',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  TEXT NOT NULL,
            customer_name TEXT,
            rating      INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment     TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            mobile      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def product_row_to_dict(row, conn):
    d = dict(row)
    c = conn.cursor()
    # avg rating + review count
    c.execute("SELECT COUNT(*) as cnt, AVG(rating) as avg FROM reviews WHERE product_id = ?", (d["id"],))
    r = c.fetchone()
    d["review_count"] = r["cnt"]
    d["avg_rating"] = round(r["avg"] or 0, 1)
    return d

def valid_mobile(m):
    return bool(re.match(r'^[6-9]\d{9}$', m.strip()))

# ─────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────

@app.route("/api/products", methods=["GET"])
def get_products():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM products ORDER BY created_at DESC")
    rows = c.fetchall()
    products = [product_row_to_dict(row, conn) for row in rows]
    conn.close()
    return jsonify(products)


@app.route("/api/products", methods=["POST"])
def add_product():
    data = request.get_json(force=True)
    required = ["id", "name", "price", "stock"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO products (id, name, description, price, stock, img_src)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data["id"],
            data["name"],
            data.get("desc", ""),
            float(data["price"]),
            int(data["stock"]),
            data.get("imgSrc", "")
        ))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "id": data["id"]}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Product ID already exists"}), 409


@app.route("/api/products/<product_id>/stock", methods=["PATCH"])
def update_stock(product_id):
    data = request.get_json(force=True)
    delta = data.get("delta", 0)  # +1 or -1

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT stock FROM products WHERE id = ?", (product_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Product not found"}), 404

    new_stock = max(0, row["stock"] + delta)
    c.execute("UPDATE products SET stock = ? WHERE id = ?", (new_stock, product_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "new_stock": new_stock})

# ─────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────

@app.route("/api/orders", methods=["POST"])
def place_order():
    data = request.get_json(force=True)
    product_id = data.get("product_id")
    qty = int(data.get("qty", 1))
    customer_name = data.get("customer_name", "Guest")
    customer_mobile = data.get("customer_mobile", "")

    if not product_id:
        return jsonify({"error": "product_id required"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()

    if not product:
        conn.close()
        return jsonify({"error": "Product not found"}), 404

    if product["stock"] < qty:
        conn.close()
        return jsonify({"error": "Insufficient stock"}), 409

    # Deduct stock, increment orders_placed
    c.execute("""
        UPDATE products
        SET stock = stock - ?, orders_placed = orders_placed + ?
        WHERE id = ?
    """, (qty, qty, product_id))

    c.execute("""
        INSERT INTO orders (product_id, customer_name, customer_mobile, qty)
        VALUES (?, ?, ?, ?)
    """, (product_id, customer_name, customer_mobile, qty))

    order_id = c.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "order_id": order_id,
        "message": f"Order placed successfully for Dehradun delivery!"
    }), 201


@app.route("/api/orders", methods=["GET"])
def get_orders():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT o.*, p.name as product_name
        FROM orders o
        LEFT JOIN products p ON o.product_id = p.id
        ORDER BY o.created_at DESC
    """)
    orders = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(orders)


@app.route("/api/orders/<int:order_id>/ship", methods=["PATCH"])
def ship_order(order_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE orders SET status = 'Shipped' WHERE id = ?", (order_id,))
    if c.rowcount == 0:
        conn.close()
        return jsonify({"error": "Order not found"}), 404
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ─────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────

@app.route("/api/reviews", methods=["POST"])
def add_review():
    data = request.get_json(force=True)
    product_id = data.get("product_id")
    rating = data.get("rating")
    comment = data.get("comment", "")
    customer_name = data.get("customer_name", "Anonymous")

    if not product_id or rating is None:
        return jsonify({"error": "product_id and rating required"}), 400

    try:
        rating = int(rating)
        if not (1 <= rating <= 5):
            raise ValueError
    except ValueError:
        return jsonify({"error": "Rating must be 1–5"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM products WHERE id = ?", (product_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({"error": "Product not found"}), 404

    c.execute("""
        INSERT INTO reviews (product_id, customer_name, rating, comment)
        VALUES (?, ?, ?, ?)
    """, (product_id, customer_name, rating, comment))
    conn.commit()

    # Return updated stats
    c.execute("SELECT COUNT(*) as cnt, AVG(rating) as avg FROM reviews WHERE product_id = ?", (product_id,))
    r = c.fetchone()
    conn.close()

    return jsonify({
        "success": True,
        "review_count": r["cnt"],
        "avg_rating": round(r["avg"] or 0, 1)
    }), 201


@app.route("/api/reviews/<product_id>", methods=["GET"])
def get_reviews(product_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT customer_name, rating, comment, created_at
        FROM reviews WHERE product_id = ?
        ORDER BY created_at DESC
    """, (product_id,))
    reviews = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(reviews)

# ─────────────────────────────────────────────
# AUTH (Customer registration / login)
# ─────────────────────────────────────────────

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    mobile = data.get("mobile", "").strip()
    password = data.get("password", "")

    if not name or not mobile or not password:
        return jsonify({"error": "name, mobile and password are required"}), 400
    if not valid_mobile(mobile):
        return jsonify({"error": "Invalid mobile number"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO customers (name, mobile, password_hash)
            VALUES (?, ?, ?)
        """, (name, mobile, hash_password(password)))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "name": name, "mobile": mobile}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Mobile number already registered"}), 409


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    mobile = data.get("mobile", "").strip()
    password = data.get("password", "")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM customers WHERE mobile = ?", (mobile,))
    customer = c.fetchone()
    conn.close()

    if not customer or customer["password_hash"] != hash_password(password):
        return jsonify({"error": "Invalid mobile or password"}), 401

    return jsonify({
        "success": True,
        "name": customer["name"],
        "mobile": customer["mobile"]
    })

@app.route('/')
def customer_home():
    return render_template('customer.html') # customer page load karega

@app.route('/admin')
def admin_home():
    return render_template('index.html') # admin page load karega
# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    # Render dynamic port provide karta hai, isliye os.environ use kiya
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)