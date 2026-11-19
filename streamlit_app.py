import hashlib
import hmac
import secrets
import sqlite3
from datetime import date, datetime
from pathlib import Path

import streamlit as st

DB_PATH = Path(__file__).with_name("shabiki.db")
ROLES = ["admin", "manager", "cashier", "shopkeeper", "delivery", "accountant"]
ROLE_LABELS = {
    "admin": "Administrator",
    "manager": "Manager",
    "cashier": "Cashier",
    "shopkeeper": "Shopkeeper / Storekeeper",
    "delivery": "Delivery person",
    "accountant": "Accountant",
}
ROLE_PAGES = {
    "admin": ["Dashboard", "New order", "Orders & receipts", "Picking desk", "Deliveries", "Inventory", "Suppliers", "Accounts", "Workers", "User accounts"],
    "manager": ["Dashboard", "New order", "Orders & receipts", "Picking desk", "Deliveries", "Inventory", "Suppliers", "Accounts", "Workers"],
    "cashier": ["Dashboard", "New order", "Orders & receipts"],
    "shopkeeper": ["Dashboard", "Picking desk", "Inventory"],
    "delivery": ["Dashboard", "Deliveries"],
    "accountant": ["Dashboard", "Orders & receipts", "Accounts"],
}
HASH_ROUNDS = 310_000

st.set_page_config(page_title="ShabikiHardware", page_icon="🛠️", layout="wide")
st.markdown("""
<style>
:root { --ink:#172a35; --gold:#f2b705; }
[data-testid="stSidebar"] { background:#172a35; }
[data-testid="stSidebar"] * { color:#f5f7f8; }
[data-testid="stMetric"] { background:#fff; border:1px solid #e3e8ea; padding:16px; border-radius:12px; }
.stButton > button[kind="primary"] { background:#eeb500; border-color:#d6a300; color:#172a35; font-weight:700; }
</style>
""", unsafe_allow_html=True)


def connect():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            unit TEXT, cost REAL DEFAULT 0, price REAL DEFAULT 0,
            reorder_level INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT
        );
        CREATE TABLE IF NOT EXISTS stock_in (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, supplier_id INTEGER,
            item_id INTEGER, qty REAL, cost REAL
        );
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, customer TEXT,
            item_id INTEGER, qty REAL, price REAL, paid REAL
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT,
            description TEXT, amount REAL
        );
        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT,
            description TEXT, amount REAL
        );
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, role TEXT,
            phone TEXT, salary REAL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT UNIQUE,
            created_at TEXT NOT NULL, customer TEXT NOT NULL, phone TEXT,
            created_by INTEGER, status TEXT NOT NULL DEFAULT 'awaiting_payment',
            delivery_required INTEGER NOT NULL DEFAULT 0, delivery_address TEXT,
            picked_by INTEGER, picked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL, item_name TEXT NOT NULL, unit TEXT,
            qty REAL NOT NULL, unit_price REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
            amount REAL NOT NULL, method TEXT NOT NULL, reference TEXT,
            received_by INTEGER, paid_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        );
        CREATE TABLE IF NOT EXISTS delivery_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL UNIQUE,
            assigned_to INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'assigned',
            assigned_at TEXT NOT NULL, collected_at TEXT, delivered_at TEXT,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            order_id INTEGER NOT NULL, message TEXT NOT NULL,
            created_at TEXT NOT NULL, read_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(order_id) REFERENCES orders(id)
        );
        """)
        if con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO items(name,unit,cost,price,reorder_level) VALUES(?,?,?,?,?)",
                [("Cement 50kg", "bags", 640, 780, 40),
                 ("Roofing sheet 3m", "pcs", 930, 1150, 30),
                 ("Nails 3 inch", "kg", 150, 210, 25),
                 ("Paint 4L", "tins", 1100, 1450, 12),
                 ("PVC pipe 4 inch", "pcs", 720, 950, 15)],
            )
        if con.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0:
            con.executemany("INSERT INTO suppliers(name,phone) VALUES(?,?)", [
                ("Bamburi Distributors", "0711 000 111"),
                ("Mabati Depot", "0722 000 222"),
                ("Nairobi Tools & Paints", "0733 000 333"),
            ])


init_db()


def query(sql, params=()):
    with connect() as con:
        return con.execute(sql, params).fetchall()


def execute(sql, params=()):
    with connect() as con:
        cur = con.execute(sql, params)
        return cur.lastrowid


def ksh(value):
    return f"KSh {float(value or 0):,.2f}"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), HASH_ROUNDS).hex()
    return salt, digest


def verify_password(password, salt, expected):
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected)


def stock_qty(item_id):
    row = query("""
        SELECT
          COALESCE((SELECT SUM(qty) FROM stock_in WHERE item_id=?),0)
          - COALESCE((SELECT SUM(qty) FROM sales WHERE item_id=?),0)
          - COALESCE((SELECT SUM(oi.qty) FROM order_items oi JOIN orders o ON o.id=oi.order_id
                      WHERE oi.item_id=? AND o.status IN ('picked','ready_for_pickup','ready_for_delivery','out_for_delivery','delivered')),0)
        AS available
    """, (item_id, item_id, item_id))[0]
    return float(row["available"] or 0)


def order_total(order_id):
    return sum(float(r["qty"]) * float(r["unit_price"]) for r in query("SELECT qty,unit_price FROM order_items WHERE order_id=?", (order_id,)))


def paid_total(order_id):
    return sum(float(r["amount"]) for r in query("SELECT amount FROM payments WHERE order_id=?", (order_id,)))


def order_label(row):
    return f"{row['order_no']} · {row['customer']} · {row['status'].replace('_',' ').title()}"


def login_screen():
    users_count = query("SELECT COUNT(*) AS n FROM users")[0]["n"]
    st.markdown("# 🛠️ ShabikiHardware")
    st.caption("Stock, orders, payments and delivery coordination")
    if users_count == 0:
        st.info("Create the first Administrator account. Do not share this account; the Administrator can create individual staff accounts with role-based access.")
        with st.form("first_admin"):
            full_name = st.text_input("Administrator full name")
            username = st.text_input("Username (work email recommended)").strip().lower()
            password = st.text_input("Password (at least 12 characters)", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create administrator", type="primary")
        if submitted:
            if not full_name.strip() or "@" not in username:
                st.error("Enter a name and a valid email-style username.")
            elif len(password) < 12:
                st.error("Use a password with at least 12 characters.")
            elif password != confirm:
                st.error("The passwords do not match.")
            else:
                salt, digest = hash_password(password)
                execute("INSERT INTO users(username,full_name,salt,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",
                        (username, full_name.strip(), salt, digest, "admin", now_iso()))
                st.success("Administrator created. Sign in with the account you just made.")
                st.rerun()
    else:
        with st.form("login"):
            username = st.text_input("Username").strip().lower()
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            user = query("SELECT * FROM users WHERE username=? AND active=1", (username,))
            if user and verify_password(password, user[0]["salt"], user[0]["password_hash"]):
                st.session_state.user_id = user[0]["id"]
                st.rerun()
            st.error("Incorrect username or password, or this account is inactive.")


def add_user_page(user):
    st.title("User accounts & role access")
    st.caption("Create a separate login for each staff member. Never share passwords or accounts.")
    with st.expander("Create staff login", expanded=True):
        with st.form("create_user"):
            full_name = st.text_input("Staff member's name")
            username = st.text_input("Username / email").strip().lower()
            role = st.selectbox("Company role", ROLES[1:], format_func=lambda value: ROLE_LABELS[value])
            password = st.text_input("Temporary password (12+ characters)", type="password")
            confirm = st.text_input("Confirm temporary password", type="password")
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            if not full_name.strip() or "@" not in username:
                st.error("Enter the staff member's name and a valid email-style username.")
            elif len(password) < 12:
                st.error("Use a temporary password with at least 12 characters.")
            elif password != confirm:
                st.error("The passwords do not match.")
            else:
                salt, digest = hash_password(password)
                try:
                    execute("INSERT INTO users(username,full_name,salt,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",
                            (username, full_name.strip(), salt, digest, role, now_iso()))
                    st.success(f"Created {ROLE_LABELS[role]} account for {full_name.strip()}.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That username already exists.")
    st.subheader("Staff access")
    users = query("SELECT id,username,full_name,role,active FROM users ORDER BY full_name")
    for account in users:
        cols = st.columns([2, 2, 2, 1, 1])
        cols[0].write(account["full_name"])
        cols[1].write(account["username"])
        cols[2].write(ROLE_LABELS.get(account["role"], account["role"]))
        cols[3].write("Active" if account["active"] else "Disabled")
        if account["id"] == user["id"]:
            cols[4].caption("You")
        else:
            label = "Disable" if account["active"] else "Enable"
            if cols[4].button(label, key=f"toggle_user_{account['id']}"):
                execute("UPDATE users SET active=? WHERE id=?", (0 if account["active"] else 1, account["id"]))
                st.rerun()
    with st.expander("What each role can access"):
        for role, pages in ROLE_PAGES.items():
            st.write(f"**{ROLE_LABELS[role]}:** {', '.join(pages)}")


def show_dashboard(user):
    st.title(f"Welcome, {user['full_name']}")
    pending = query("SELECT COUNT(*) AS n FROM orders WHERE status='awaiting_payment'")[0]["n"]
    picking = query("SELECT COUNT(*) AS n FROM orders WHERE status='paid_awaiting_pick'")[0]["n"]
    assigned = query("SELECT COUNT(*) AS n FROM delivery_tasks WHERE status IN ('assigned','collected')")[0]["n"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Invoices awaiting payment", pending)
    c2.metric("Paid orders to pick", picking)
    c3.metric("Active deliveries", assigned)
    if user["role"] == "delivery":
        unread = query("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND read_at IS NULL", (user["id"],))[0]["n"]
        st.info(f"You have {unread} new delivery notification(s). Open **Deliveries** to review your assignments.")
    st.subheader("Current stock")
    items = query("SELECT id,name,unit,reorder_level FROM items ORDER BY name")
    st.dataframe([{"Item": r["name"], "In stock": stock_qty(r["id"]), "Unit": r["unit"], "Reorder at": r["reorder_level"]} for r in items], use_container_width=True, hide_index=True)
    if user["role"] in ("admin", "manager", "accountant"):
        today_sales = query("SELECT COALESCE(SUM(oi.qty*oi.unit_price),0) AS total FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE date(o.created_at)=?", (date.today().isoformat(),))[0]["total"]
        st.metric("Today's order value", ksh(today_sales))


def new_order_page(user):
    st.title("New customer order")
    st.caption("Create an invoice first. Record payment separately; a paid receipt is then available for the customer and the picking desk.")
    items = query("SELECT id,name,unit,price FROM items ORDER BY name")
    if not items:
        st.warning("Add stock items before creating an order.")
        return
    st.session_state.setdefault("cart", [])
    with st.form("add_to_cart"):
        item = st.selectbox("Item", items, format_func=lambda r: f"{r['name']} — {ksh(r['price'])} per {r['unit']}")
        qty = st.number_input("Quantity", min_value=0.01, step=1.0, value=1.0)
        add = st.form_submit_button("Add item to order")
    if add:
        already = sum(line["qty"] for line in st.session_state.cart if line["item_id"] == item["id"])
        if qty + already > stock_qty(item["id"]):
            st.error(f"Only {stock_qty(item['id'])} {item['unit']} currently available.")
        else:
            st.session_state.cart.append({"item_id": item["id"], "item_name": item["name"], "unit": item["unit"], "qty": qty, "unit_price": float(item["price"])})
            st.rerun()
    if st.session_state.cart:
        st.subheader("Order items")
        st.dataframe([{"Item": line["item_name"], "Quantity": line["qty"], "Unit price": ksh(line["unit_price"]), "Line total": ksh(line["qty"] * line["unit_price"])} for line in st.session_state.cart], use_container_width=True, hide_index=True)
        st.markdown(f"**Total: {ksh(sum(x['qty'] * x['unit_price'] for x in st.session_state.cart))}**")
        if st.button("Clear order", key="clear_cart"):
            st.session_state.cart = []
            st.rerun()
        st.divider()
        with st.form("checkout"):
            customer = st.text_input("Customer name")
            phone = st.text_input("Customer phone")
            delivery = st.checkbox("Customer needs delivery")
            address = st.text_input("Delivery address (required for delivery)", disabled=not delivery)
            submit = st.form_submit_button("Create invoice", type="primary")
        if submit:
            if not customer.strip():
                st.error("Enter the customer's name.")
            elif delivery and not address.strip():
                st.error("Enter the delivery address.")
            else:
                # Recheck available quantities at checkout to avoid overselling after the cart was started.
                insufficient = [line["item_name"] for line in st.session_state.cart if line["qty"] > stock_qty(line["item_id"])]
                if insufficient:
                    st.error("Insufficient stock for: " + ", ".join(insufficient))
                else:
                    with connect() as con:
                        cur = con.execute("INSERT INTO orders(order_no,created_at,customer,phone,created_by,status,delivery_required,delivery_address) VALUES(NULL,?,?,?,?,?,?,?)",
                                          (now_iso(), customer.strip(), phone.strip(), user["id"], "awaiting_payment", int(delivery), address.strip()))
                        order_id = cur.lastrowid
                        order_no = f"INV-{date.today():%y%m%d}-{order_id:05d}"
                        con.execute("UPDATE orders SET order_no=? WHERE id=?", (order_no, order_id))
                        con.executemany("INSERT INTO order_items(order_id,item_id,item_name,unit,qty,unit_price) VALUES(?,?,?,?,?,?)",
                                        [(order_id, line["item_id"], line["item_name"], line["unit"], line["qty"], line["unit_price"]) for line in st.session_state.cart])
                    st.session_state.cart = []
                    st.session_state.last_order_id = order_id
                    st.success(f"Invoice {order_no} created. Record the customer's payment under Orders & receipts.")
                    st.rerun()
    elif not add:
        st.info("Add one or more items to start an order.")


def receipt_text(order, lines, payments, copy_name):
    total = sum(float(x["qty"]) * float(x["unit_price"]) for x in lines)
    paid = sum(float(p["amount"]) for p in payments)
    result = ["SHABIKIHARDWARE", copy_name, f"Invoice: {order['order_no']}", f"Customer: {order['customer']}", f"Date: {order['created_at']}", "", "ITEMS"]
    result.extend(f"{x['item_name']} | {x['qty']:g} {x['unit'] or ''} x {ksh(x['unit_price'])} = {ksh(x['qty']*x['unit_price'])}" for x in lines)
    result += ["", f"Total: {ksh(total)}", f"Paid: {ksh(paid)}", f"Balance: {ksh(total-paid)}"]
    if payments:
        result += ["", "PAYMENTS"]
        result.extend(f"{p['paid_at']} | {ksh(p['amount'])} | {p['method']} | {p['reference'] or '—'}" for p in payments)
    result.append("Thank you for your business.")
    return "\n".join(result)


def order_details(order, user):
    items = query("SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order["id"],))
    payments = query("SELECT p.*,u.full_name AS received_name FROM payments p LEFT JOIN users u ON u.id=p.received_by WHERE p.order_id=? ORDER BY p.id", (order["id"],))
    total = sum(float(i["qty"]) * float(i["unit_price"]) for i in items)
    paid = sum(float(p["amount"]) for p in payments)
    st.markdown(f"### {order['order_no']} · {order['customer']}")
    a, b, c = st.columns(3)
    a.metric("Order total", ksh(total))
    b.metric("Paid", ksh(paid))
    c.metric("Balance", ksh(max(total-paid, 0)))
    st.caption(f"Status: **{order['status'].replace('_',' ').title()}** · Created {order['created_at']}")
    st.dataframe([{"Item": i["item_name"], "Qty": i["qty"], "Unit price": ksh(i["unit_price"]), "Total": ksh(i["qty"]*i["unit_price"])} for i in items], use_container_width=True, hide_index=True)
    invoice = receipt_text(order, items, payments, "CUSTOMER INVOICE")
    st.download_button("Download invoice", invoice, file_name=f"{order['order_no']}-invoice.txt", mime="text/plain", key=f"invoice_{order['id']}")

    if user["role"] in ("admin", "manager", "cashier") and order["status"] in ("awaiting_payment", "part_paid") and total-paid > 0:
        st.subheader("Receive customer payment")
        with st.form(f"payment_{order['id']}"):
            amount = st.number_input("Amount received", min_value=0.01, max_value=float(total-paid), value=float(total-paid), step=100.0)
            method = st.selectbox("Payment method", ["Cash", "M-Pesa", "Bank transfer", "Card", "Other"])
            reference = st.text_input("Transaction reference (optional)")
            submit = st.form_submit_button("Record payment & issue receipt", type="primary")
        if submit:
            with connect() as con:
                con.execute("INSERT INTO payments(order_id,amount,method,reference,received_by,paid_at) VALUES(?,?,?,?,?,?)",
                            (order["id"], amount, method, reference.strip(), user["id"], now_iso()))
                new_paid = paid + amount
                new_status = "paid_awaiting_pick" if new_paid >= total - 0.001 else "part_paid"
                con.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order["id"]))
                if new_status == "paid_awaiting_pick":
                    shopkeepers = con.execute("SELECT id FROM users WHERE role='shopkeeper' AND active=1").fetchall()
                    for shopkeeper in shopkeepers:
                        con.execute("INSERT INTO notifications(user_id,order_id,message,created_at) VALUES(?,?,?,?)",
                                    (shopkeeper["id"], order["id"], f"Paid order {order['order_no']} is ready for picking.", now_iso()))
            st.success("Payment recorded. The receipt is ready below; a paid order has been sent to the shopkeeper picking queue.")
            st.rerun()

    if payments:
        st.subheader("Payment receipts")
        for p in payments:
            st.write(f"{p['paid_at']} · {ksh(p['amount'])} · {p['method']} · received by {p['received_name'] or 'staff'}")
            customer_receipt = receipt_text(order, items, [p], "CUSTOMER PAYMENT RECEIPT")
            pick_receipt = receipt_text(order, items, [p], "SHOPKEEPER PAYMENT / PICKING COPY")
            left, right = st.columns(2)
            left.download_button("Download customer receipt", customer_receipt, file_name=f"{order['order_no']}-receipt-{p['id']}.txt", mime="text/plain", key=f"cust_receipt_{p['id']}")
            right.download_button("Download shopkeeper copy", pick_receipt, file_name=f"{order['order_no']}-pick-slip-{p['id']}.txt", mime="text/plain", key=f"pick_receipt_{p['id']}")


def orders_page(user):
    st.title("Orders, invoices & receipts")
    orders = query("SELECT * FROM orders ORDER BY id DESC LIMIT 300")
    if not orders:
        st.info("No orders yet. Create the first order from New order.")
        return
    st.dataframe([{"Invoice": o["order_no"], "Date": o["created_at"][:10], "Customer": o["customer"], "Status": o["status"].replace("_", " ").title(), "Total": ksh(order_total(o["id"])), "Paid": ksh(paid_total(o["id"]))} for o in orders], use_container_width=True, hide_index=True)
    selected = st.selectbox("Open an invoice / receipt", orders, format_func=order_label)
    order_details(selected, user)


def picking_page(user):
    st.title("Shopkeeper picking desk")
    notices = query("SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC", (user["id"],))
    if notices:
        st.info(f"{len(notices)} new paid order notification(s).")
    orders = query("SELECT * FROM orders WHERE status IN ('paid_awaiting_pick','picking') ORDER BY id")
    if not orders:
        st.success("No paid orders are waiting to be picked.")
        return
    for order in orders:
        with st.container(border=True):
            st.markdown(f"### {order['order_no']} — {order['customer']}")
            if order["delivery_required"]:
                st.caption(f"Delivery requested · {order['delivery_address']}")
            lines = query("SELECT * FROM order_items WHERE order_id=?", (order["id"],))
            payments = query("SELECT * FROM payments WHERE order_id=? ORDER BY id", (order["id"],))
            st.dataframe([{"Pick item": r["item_name"], "Quantity": r["qty"], "Unit": r["unit"]} for r in lines], use_container_width=True, hide_index=True)
            total = order_total(order["id"])
            paid = paid_total(order["id"])
            st.write(f"Payment verified: **{ksh(paid)} / {ksh(total)}**")
            receipt = receipt_text(order, lines, payments, "SHOPKEEPER PICKING COPY")
            st.download_button("Download shopkeeper receipt / pick slip", receipt, file_name=f"{order['order_no']}-pick-slip.txt", mime="text/plain", key=f"shop_pick_{order['id']}")
            if order["status"] == "paid_awaiting_pick":
                st.warning("Pick the items against this receipt. Stock is deducted when you confirm picking.")
                if order["delivery_required"]:
                    delivery_users = query("SELECT id,full_name FROM users WHERE role='delivery' AND active=1 ORDER BY full_name")
                    if delivery_users:
                        assigned = st.selectbox("Notify delivery person", delivery_users, format_func=lambda r: r["full_name"], key=f"delivery_user_{order['id']}")
                        if st.button("Confirm picked & notify delivery", type="primary", key=f"picked_delivery_{order['id']}"):
                            insufficient = [r["item_name"] for r in lines if r["qty"] > stock_qty(r["item_id"])]
                            if insufficient:
                                st.error("Not enough stock to complete this pick: " + ", ".join(insufficient))
                            else:
                                with connect() as con:
                                    con.execute("UPDATE orders SET status='ready_for_delivery',picked_by=?,picked_at=? WHERE id=?", (user["id"], now_iso(), order["id"]))
                                    con.execute("INSERT INTO delivery_tasks(order_id,assigned_to,status,assigned_at) VALUES(?,?,?,?)", (order["id"], assigned["id"], "assigned", now_iso()))
                                    con.execute("INSERT INTO notifications(user_id,order_id,message,created_at) VALUES(?,?,?,?)", (assigned["id"], order["id"], f"Order {order['order_no']} is picked and ready for delivery to {order['delivery_address']}.", now_iso()))
                                    con.execute("UPDATE notifications SET read_at=? WHERE order_id=? AND user_id=? AND read_at IS NULL", (now_iso(), order["id"], user["id"]))
                                st.success(f"Picked and assigned to {assigned['full_name']}; delivery notification created.")
                                st.rerun()
                    else:
                        st.error("There are no active delivery-person accounts. Ask an Administrator to create one before confirming this delivery pick.")
                elif st.button("Confirm picked — ready for customer collection", type="primary", key=f"picked_collect_{order['id']}"):
                    insufficient = [r["item_name"] for r in lines if r["qty"] > stock_qty(r["item_id"])]
                    if insufficient:
                        st.error("Not enough stock to complete this pick: " + ", ".join(insufficient))
                    else:
                        execute("UPDATE orders SET status='ready_for_pickup',picked_by=?,picked_at=? WHERE id=?", (user["id"], now_iso(), order["id"]))
                        st.success("Items picked. Stock has been updated and the order is ready for collection.")
                        st.rerun()


def deliveries_page(user):
    st.title("Delivery notifications & assignments")
    notices = query("SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC", (user["id"],))
    for notice in notices:
        st.info(notice["message"])
    tasks = query("""
        SELECT d.*,o.order_no,o.customer,o.phone,o.delivery_address,o.status AS order_status
        FROM delivery_tasks d JOIN orders o ON o.id=d.order_id
        WHERE d.assigned_to=? ORDER BY d.id DESC
    """, (user["id"],))
    if not tasks:
        st.info("No delivery assignments yet.")
        return
    for task in tasks:
        with st.container(border=True):
            st.markdown(f"### {task['order_no']} — {task['customer']}")
            st.write(f"**Address:** {task['delivery_address'] or 'Not provided'}  ·  **Phone:** {task['phone'] or 'Not provided'}")
            lines = query("SELECT * FROM order_items WHERE order_id=?", (task["order_id"],))
            st.dataframe([{"Item": r["item_name"], "Quantity": r["qty"], "Unit": r["unit"]} for r in lines], use_container_width=True, hide_index=True)
            if task["status"] == "assigned":
                if st.button("Acknowledge & collect items", type="primary", key=f"collect_{task['id']}"):
                    with connect() as con:
                        con.execute("UPDATE delivery_tasks SET status='collected',collected_at=? WHERE id=?", (now_iso(), task["id"]))
                        con.execute("UPDATE orders SET status='out_for_delivery' WHERE id=?", (task["order_id"],))
                        con.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND order_id=? AND read_at IS NULL", (now_iso(), user["id"], task["order_id"]))
                    st.success("Assignment acknowledged. Mark it delivered when complete.")
                    st.rerun()
            elif task["status"] == "collected":
                st.warning("In transit")
                if st.button("Mark delivered", type="primary", key=f"delivered_{task['id']}"):
                    with connect() as con:
                        con.execute("UPDATE delivery_tasks SET status='delivered',delivered_at=? WHERE id=?", (now_iso(), task["id"]))
                        con.execute("UPDATE orders SET status='delivered' WHERE id=?", (task["order_id"],))
                    st.success("Delivery completed.")
                    st.rerun()
            else:
                st.success("Delivered")


def inventory_page():
    st.title("Inventory & stock")
    tab_stock, tab_receive, tab_new = st.tabs(["Stock levels", "Receive stock", "Add item"])
    with tab_stock:
        items = query("SELECT * FROM items ORDER BY name")
        st.dataframe([{"Item": i["name"], "Unit": i["unit"], "Available": stock_qty(i["id"]), "Reorder level": i["reorder_level"], "Buying price": ksh(i["cost"]), "Selling price": ksh(i["price"])} for i in items], use_container_width=True, hide_index=True)
        low = [i for i in items if stock_qty(i["id"]) <= i["reorder_level"]]
        if low:
            st.warning("Reorder alert: " + ", ".join(i["name"] for i in low))
    with tab_receive:
        suppliers = query("SELECT id,name FROM suppliers ORDER BY name")
        items = query("SELECT id,name,cost FROM items ORDER BY name")
        if not suppliers or not items:
            st.info("Add a supplier and stock item first.")
        else:
            with st.form("receive_stock"):
                received_date = st.date_input("Date", value=date.today())
                supplier = st.selectbox("Supplier", suppliers, format_func=lambda r: r["name"])
                item = st.selectbox("Item", items, format_func=lambda r: r["name"])
                qty = st.number_input("Quantity received", min_value=0.01, step=1.0, value=1.0)
                cost = st.number_input("Unit cost", min_value=0.0, value=float(item["cost"] or 0), step=10.0)
                submit = st.form_submit_button("Record received stock", type="primary")
            if submit:
                execute("INSERT INTO stock_in(date,supplier_id,item_id,qty,cost) VALUES(?,?,?,?,?)", (received_date.isoformat(), supplier["id"], item["id"], qty, cost))
                st.success("Stock receipt recorded.")
                st.rerun()
        data = query("SELECT si.date,s.name AS supplier,i.name AS item,si.qty,si.cost FROM stock_in si JOIN suppliers s ON s.id=si.supplier_id JOIN items i ON i.id=si.item_id ORDER BY si.id DESC")
        st.dataframe([{"Date": r["date"], "Supplier": r["supplier"], "Item": r["item"], "Quantity": r["qty"], "Unit cost": ksh(r["cost"])} for r in data], use_container_width=True, hide_index=True)
    with tab_new:
        with st.form("add_item"):
            name = st.text_input("Item name")
            unit = st.text_input("Unit", value="pcs")
            cost = st.number_input("Buying price", min_value=0.0, step=10.0)
            price = st.number_input("Selling price", min_value=0.0, step=10.0)
            reorder = st.number_input("Reorder level", min_value=0, step=1)
            submit = st.form_submit_button("Add item")
        if submit:
            if not name.strip():
                st.error("Enter an item name.")
            else:
                try:
                    execute("INSERT INTO items(name,unit,cost,price,reorder_level) VALUES(?,?,?,?,?)", (name.strip(), unit.strip(), cost, price, reorder))
                    st.success("Item added.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("An item with that name already exists.")


def suppliers_page():
    st.title("Suppliers")
    with st.form("supplier"):
        name = st.text_input("Supplier name")
        phone = st.text_input("Phone")
        submit = st.form_submit_button("Add supplier")
    if submit:
        if name.strip():
            execute("INSERT INTO suppliers(name,phone) VALUES(?,?)", (name.strip(), phone.strip()))
            st.success("Supplier added.")
            st.rerun()
        else:
            st.error("Enter a supplier name.")
    st.dataframe([dict(r) for r in query("SELECT name AS Supplier,phone AS Phone FROM suppliers ORDER BY name")], use_container_width=True, hide_index=True)


def accounts_page():
    st.title("Accounts")
    tab_expense, tab_income, tab_ledger = st.tabs(["Expenses", "Other income", "Payments received"])
    with tab_expense:
        with st.form("expense"):
            exp_date = st.date_input("Date", value=date.today(), key="expense_date")
            category = st.selectbox("Category", ["Rent", "Electricity", "Transport", "Salaries", "Licences", "Repairs", "Other"])
            desc = st.text_input("Description", key="expense_desc")
            amount = st.number_input("Amount", min_value=0.0, step=100.0, key="expense_amount")
            submit = st.form_submit_button("Record expense")
        if submit:
            execute("INSERT INTO expenses(date,category,description,amount) VALUES(?,?,?,?)", (exp_date.isoformat(), category, desc, amount))
            st.success("Expense recorded.")
            st.rerun()
        data = query("SELECT date,category,description,amount FROM expenses ORDER BY id DESC")
        st.dataframe([{"Date": r["date"], "Category": r["category"], "Description": r["description"], "Amount": ksh(r["amount"])} for r in data], use_container_width=True, hide_index=True)
    with tab_income:
        with st.form("income"):
            inc_date = st.date_input("Date", value=date.today(), key="income_date")
            desc = st.text_input("Income source")
            amount = st.number_input("Amount", min_value=0.0, step=100.0, key="income_amount")
            submit = st.form_submit_button("Record income")
        if submit:
            execute("INSERT INTO income(date,description,amount) VALUES(?,?,?)", (inc_date.isoformat(), desc, amount))
            st.success("Income recorded.")
            st.rerun()
        data = query("SELECT date,description,amount FROM income ORDER BY id DESC")
        st.dataframe([{"Date": r["date"], "Source": r["description"], "Amount": ksh(r["amount"])} for r in data], use_container_width=True, hide_index=True)
    with tab_ledger:
        payments = query("SELECT p.paid_at,o.order_no,o.customer,p.amount,p.method,p.reference,u.full_name FROM payments p JOIN orders o ON o.id=p.order_id LEFT JOIN users u ON u.id=p.received_by ORDER BY p.id DESC")
        st.dataframe([{"Date": p["paid_at"], "Invoice": p["order_no"], "Customer": p["customer"], "Amount": ksh(p["amount"]), "Method": p["method"], "Reference": p["reference"], "Received by": p["full_name"]} for p in payments], use_container_width=True, hide_index=True)


def workers_page():
    st.title("Workers")
    with st.form("worker"):
        name = st.text_input("Full name")
        role = st.text_input("Job title")
        phone = st.text_input("Phone")
        salary = st.number_input("Monthly salary", min_value=0.0, step=1000.0)
        submit = st.form_submit_button("Add worker")
    if submit:
        if name.strip():
            execute("INSERT INTO workers(name,role,phone,salary) VALUES(?,?,?,?)", (name.strip(), role.strip(), phone.strip(), salary))
            st.success("Worker added.")
            st.rerun()
        else:
            st.error("Enter the worker's name.")
    data = query("SELECT name,role,phone,salary FROM workers ORDER BY name")
    st.dataframe([{"Name": r["name"], "Job title": r["role"], "Phone": r["phone"], "Monthly salary": ksh(r["salary"])} for r in data], use_container_width=True, hide_index=True)


if "user_id" not in st.session_state:
    st.session_state.user_id = None
current = query("SELECT * FROM users WHERE id=? AND active=1", (st.session_state.user_id,)) if st.session_state.user_id else []
if not current:
    st.session_state.user_id = None
    login_screen()
    st.stop()

user = current[0]
with st.sidebar:
    st.markdown("## 🛠️ ShabikiHardware")
    st.caption(f"{user['full_name']} · {ROLE_LABELS[user['role']]}")
    if st.button("Sign out", use_container_width=True):
        st.session_state.user_id = None
        st.session_state.cart = []
        st.rerun()
    page = st.radio("Workspace", ROLE_PAGES.get(user["role"], ["Dashboard"]))

if page == "Dashboard":
    show_dashboard(user)
elif page == "New order":
    new_order_page(user)
elif page == "Orders & receipts":
    orders_page(user)
elif page == "Picking desk":
    picking_page(user)
elif page == "Deliveries":
    deliveries_page(user)
elif page == "Inventory":
    inventory_page()
elif page == "Suppliers":
    suppliers_page()
elif page == "Accounts":
    accounts_page()
elif page == "Workers":
    workers_page()
elif page == "User accounts" and user["role"] == "admin":
    add_user_page(user)
else:
    st.error("You do not have permission to access this section.")
