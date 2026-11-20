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
    "admin": "Administrator", "manager": "Manager", "cashier": "Cashier",
    "shopkeeper": "Shopkeeper / Storekeeper", "delivery": "Delivery person",
    "accountant": "Accountant",
}
ROLE_PAGES = {
    "admin": ["Dashboard", "New order", "Orders & receipts", "Payment approvals", "Picking desk", "Deliveries", "Inventory", "Suppliers", "Accounts", "Workers", "User accounts"],
    "manager": ["Dashboard", "New order", "Orders & receipts", "Payment approvals", "Picking desk", "Deliveries", "Inventory", "Suppliers", "Accounts", "Workers"],
    "cashier": ["Dashboard", "New order", "Orders & receipts"],
    "shopkeeper": ["Dashboard", "Picking desk", "Inventory"],
    "delivery": ["Dashboard", "Deliveries"],
    "accountant": ["Dashboard", "Orders & receipts", "Payment approvals", "Accounts"],
}
HASH_ROUNDS = 310_000

st.set_page_config(page_title="ShabikiHardware", page_icon="🛠️", layout="wide")
st.markdown("""
<style>
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


def ensure_column(con, table, column, declaration):
    existing = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, unit TEXT, cost REAL DEFAULT 0, price REAL DEFAULT 0, reorder_level INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT);
        CREATE TABLE IF NOT EXISTS stock_in (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, supplier_id INTEGER, item_id INTEGER, qty REAL, cost REAL);
        CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, customer TEXT, item_id INTEGER, qty REAL, price REAL, paid REAL);
        CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT, description TEXT, amount REAL);
        CREATE TABLE IF NOT EXISTS income (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, description TEXT, amount REAL);
        CREATE TABLE IF NOT EXISTS workers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, role TEXT, phone TEXT, salary REAL);
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT UNIQUE, created_at TEXT NOT NULL, customer TEXT NOT NULL, phone TEXT, created_by INTEGER, status TEXT NOT NULL DEFAULT 'awaiting_payment', delivery_required INTEGER NOT NULL DEFAULT 0, delivery_address TEXT, picked_by INTEGER, picked_at TEXT);
        CREATE TABLE IF NOT EXISTS order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, item_id INTEGER NOT NULL, item_name TEXT NOT NULL, unit TEXT, qty REAL NOT NULL, unit_price REAL NOT NULL, FOREIGN KEY(order_id) REFERENCES orders(id));
        CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, amount REAL NOT NULL, method TEXT NOT NULL, reference TEXT, received_by INTEGER, paid_at TEXT NOT NULL, FOREIGN KEY(order_id) REFERENCES orders(id));
        CREATE TABLE IF NOT EXISTS delivery_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL UNIQUE, assigned_to INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'assigned', assigned_at TEXT NOT NULL, collected_at TEXT, delivered_at TEXT, FOREIGN KEY(order_id) REFERENCES orders(id));
        CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, order_id INTEGER NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(order_id) REFERENCES orders(id));
        """)
        # Migrate databases created by earlier app versions. Existing payments remain approved;
        # all new cashier-entered payments are explicitly pending accountant review.
        ensure_column(con, "payments", "status", "TEXT NOT NULL DEFAULT 'approved'")
        ensure_column(con, "payments", "approved_by", "INTEGER")
        ensure_column(con, "payments", "approved_at", "TEXT")
        ensure_column(con, "payments", "approval_note", "TEXT")
        if con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            con.executemany("INSERT INTO items(name,unit,cost,price,reorder_level) VALUES(?,?,?,?,?)", [
                ("Cement 50kg", "bags", 640, 780, 40), ("Roofing sheet 3m", "pcs", 930, 1150, 30),
                ("Nails 3 inch", "kg", 150, 210, 25), ("Paint 4L", "tins", 1100, 1450, 12),
                ("PVC pipe 4 inch", "pcs", 720, 950, 15)])
        if con.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0:
            con.executemany("INSERT INTO suppliers(name,phone) VALUES(?,?)", [
                ("Bamburi Distributors", "0711 000 111"), ("Mabati Depot", "0722 000 222"),
                ("Nairobi Tools & Paints", "0733 000 333")])


init_db()


def query(sql, params=()):
    # Return regular dictionaries, not sqlite3.Row objects: Streamlit widgets deepcopy
    # their options and sqlite3.Row is not deepcopy/pickle safe.
    with connect() as con:
        return [dict(row) for row in con.execute(sql, params).fetchall()]


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
    return hmac.compare_digest(hash_password(password, salt)[1], expected)


def stock_qty(item_id):
    row = query("""SELECT COALESCE((SELECT SUM(qty) FROM stock_in WHERE item_id=?),0)
        - COALESCE((SELECT SUM(qty) FROM sales WHERE item_id=?),0)
        - COALESCE((SELECT SUM(oi.qty) FROM order_items oi JOIN orders o ON o.id=oi.order_id
          WHERE oi.item_id=? AND o.status IN ('picked','ready_for_pickup','ready_for_delivery','out_for_delivery','delivered')),0) AS available""",
        (item_id, item_id, item_id))[0]
    return float(row["available"] or 0)


def order_total(order_id):
    return sum(r["qty"] * r["unit_price"] for r in query("SELECT qty,unit_price FROM order_items WHERE order_id=?", (order_id,)))


def paid_total(order_id, approved_only=True):
    sql = "SELECT amount FROM payments WHERE order_id=?" + (" AND status='approved'" if approved_only else "")
    return sum(r["amount"] for r in query(sql, (order_id,)))


def order_label(order):
    return f"{order['order_no']} · {order['customer']} · {order['status'].replace('_',' ').title()}"


def login_screen():
    count = query("SELECT COUNT(*) AS n FROM users")[0]["n"]
    st.markdown("# 🛠️ ShabikiHardware")
    st.caption("Orders, payment approval, stock and delivery coordination")
    if count == 0:
        st.info("Create the first Administrator account. The Administrator can then create separate staff accounts and assign roles.")
        with st.form("first_admin"):
            full_name = st.text_input("Administrator full name")
            username = st.text_input("Username (work email recommended)").strip().lower()
            password = st.text_input("Password (at least 12 characters)", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submit = st.form_submit_button("Create administrator", type="primary")
        if submit:
            if not full_name.strip() or "@" not in username:
                st.error("Enter a name and a valid email-style username.")
            elif len(password) < 12:
                st.error("Use a password with at least 12 characters.")
            elif password != confirm:
                st.error("The passwords do not match.")
            else:
                salt, digest = hash_password(password)
                execute("INSERT INTO users(username,full_name,salt,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", (username, full_name.strip(), salt, digest, "admin", now_iso()))
                st.success("Administrator created. Sign in with that account.")
                st.rerun()
    else:
        with st.form("login"):
            username = st.text_input("Username").strip().lower()
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Sign in", type="primary")
        if submit:
            users = query("SELECT * FROM users WHERE username=? AND active=1", (username,))
            if users and verify_password(password, users[0]["salt"], users[0]["password_hash"]):
                st.session_state.user_id = users[0]["id"]
                st.rerun()
            st.error("Incorrect username or password, or this account is inactive.")


def users_page(user):
    st.title("User accounts & roles")
    with st.expander("Create staff login", expanded=True):
        with st.form("create_user"):
            full_name = st.text_input("Staff member name")
            username = st.text_input("Username / email").strip().lower()
            role = st.selectbox("Company role", ROLES[1:], format_func=lambda value: ROLE_LABELS[value])
            password = st.text_input("Temporary password (12+ characters)", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submit = st.form_submit_button("Create account", type="primary")
        if submit:
            if not full_name.strip() or "@" not in username:
                st.error("Enter a name and valid email-style username.")
            elif len(password) < 12:
                st.error("Password must be at least 12 characters.")
            elif password != confirm:
                st.error("The passwords do not match.")
            else:
                salt, digest = hash_password(password)
                try:
                    execute("INSERT INTO users(username,full_name,salt,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", (username, full_name.strip(), salt, digest, role, now_iso()))
                    st.success("Staff login created.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That username already exists.")
    for account in query("SELECT id,username,full_name,role,active FROM users ORDER BY full_name"):
        cols = st.columns([2, 2, 2, 1, 1])
        cols[0].write(account["full_name"]); cols[1].write(account["username"])
        cols[2].write(ROLE_LABELS.get(account["role"], account["role"]))
        cols[3].write("Active" if account["active"] else "Disabled")
        if account["id"] == user["id"]:
            cols[4].caption("You")
        elif cols[4].button("Disable" if account["active"] else "Enable", key=f"toggle_{account['id']}"):
            execute("UPDATE users SET active=? WHERE id=?", (0 if account["active"] else 1, account["id"]))
            st.rerun()


def dashboard(user):
    st.title(f"Welcome, {user['full_name']}")
    pending = query("SELECT COUNT(*) AS n FROM payments WHERE status='pending'")[0]["n"]
    picking = query("SELECT COUNT(*) AS n FROM orders WHERE status='paid_awaiting_pick'")[0]["n"]
    deliveries = query("SELECT COUNT(*) AS n FROM delivery_tasks WHERE status IN ('assigned','collected')")[0]["n"]
    a, b, c = st.columns(3)
    a.metric("Payments awaiting approval", pending); b.metric("Paid orders to pick", picking); c.metric("Active deliveries", deliveries)
    if user["role"] == "delivery":
        unread = query("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND read_at IS NULL", (user["id"],))[0]["n"]
        st.info(f"You have {unread} new delivery notification(s). Open **Deliveries** to see assignments.")
    st.subheader("Available stock")
    items = query("SELECT id,name,unit,reorder_level FROM items ORDER BY name")
    st.dataframe([{"Item": i["name"], "Available": stock_qty(i["id"]), "Unit": i["unit"], "Reorder at": i["reorder_level"]} for i in items], use_container_width=True, hide_index=True)


def new_order_page(user):
    st.title("New customer order")
    st.caption("Enter the customer's requested items and issue an invoice. Payment is recorded by the cashier and must be approved by Accounts before a receipt/picking notification is issued.")
    items = query("SELECT id,name,unit,price FROM items ORDER BY name")
    if not items:
        st.warning("Add stock items before creating an order."); return
    st.session_state.setdefault("cart", [])
    # Use plain string options, not sqlite rows/dicts, for maximum Streamlit widget compatibility.
    item_by_label = {f"{i['name']} — {ksh(i['price'])} per {i['unit']}": i for i in items}
    labels = list(item_by_label)
    with st.form("add_to_cart"):
        item_label = st.selectbox("Select requested item", labels)
        qty = st.number_input("Quantity", min_value=0.01, step=1.0, value=1.0)
        add = st.form_submit_button("Add item to invoice")
    if add:
        item = item_by_label[item_label]
        committed = sum(line["qty"] for line in st.session_state.cart if line["item_id"] == item["id"])
        if qty + committed > stock_qty(item["id"]):
            st.error(f"Only {stock_qty(item['id'])} {item['unit']} currently available.")
        else:
            st.session_state.cart.append({"item_id": item["id"], "item_name": item["name"], "unit": item["unit"], "qty": qty, "unit_price": float(item["price"])})
            st.rerun()
    if not st.session_state.cart:
        st.info("Add the items requested by the customer to start their invoice."); return
    st.subheader("Invoice items")
    st.dataframe([{"Item": x["item_name"], "Qty": x["qty"], "Unit price": ksh(x["unit_price"]), "Line total": ksh(x["qty"]*x["unit_price"])} for x in st.session_state.cart], use_container_width=True, hide_index=True)
    st.markdown(f"**Invoice total: {ksh(sum(x['qty']*x['unit_price'] for x in st.session_state.cart))}**")
    if st.button("Clear invoice", key="clear_cart"):
        st.session_state.cart = []; st.rerun()
    with st.form("checkout"):
        customer = st.text_input("Customer name")
        phone = st.text_input("Customer phone")
        delivery = st.checkbox("Delivery required")
        address = st.text_input("Delivery address", disabled=not delivery)
        submit = st.form_submit_button("Create customer invoice", type="primary")
    if submit:
        if not customer.strip():
            st.error("Enter the customer's name."); return
        if delivery and not address.strip():
            st.error("Enter delivery address."); return
        insufficient = [x["item_name"] for x in st.session_state.cart if x["qty"] > stock_qty(x["item_id"])]
        if insufficient:
            st.error("Insufficient stock: " + ", ".join(insufficient)); return
        with connect() as con:
            cur = con.execute("INSERT INTO orders(order_no,created_at,customer,phone,created_by,status,delivery_required,delivery_address) VALUES(NULL,?,?,?,?,?,?,?)", (now_iso(), customer.strip(), phone.strip(), user["id"], "awaiting_payment", int(delivery), address.strip()))
            order_id = cur.lastrowid
            order_no = f"INV-{date.today():%y%m%d}-{order_id:05d}"
            con.execute("UPDATE orders SET order_no=? WHERE id=?", (order_no, order_id))
            con.executemany("INSERT INTO order_items(order_id,item_id,item_name,unit,qty,unit_price) VALUES(?,?,?,?,?,?)", [(order_id, x["item_id"], x["item_name"], x["unit"], x["qty"], x["unit_price"]) for x in st.session_state.cart])
        st.session_state.cart = []
        st.success(f"Invoice {order_no} created. Record the customer's payment in Orders & receipts; Accounts must approve it before the paid receipt is issued.")
        st.rerun()


def receipt_text(order, lines, payments, heading):
    total = sum(float(x["qty"])*float(x["unit_price"]) for x in lines)
    paid = sum(float(p["amount"]) for p in payments)
    out = ["SHABIKIHARDWARE", heading, f"Invoice: {order['order_no']}", f"Customer: {order['customer']}", f"Date: {order['created_at']}", "", "ITEMS"]
    out.extend(f"{x['item_name']} | {x['qty']:g} {x['unit'] or ''} x {ksh(x['unit_price'])} = {ksh(x['qty']*x['unit_price'])}" for x in lines)
    out += ["", f"Order total: {ksh(total)}", f"Approved payment(s): {ksh(paid)}", f"Balance: {ksh(max(total-paid, 0))}"]
    if payments:
        out += ["", "APPROVED PAYMENTS"]
        out.extend(f"{p['paid_at']} | {ksh(p['amount'])} | {p['method']} | {p['reference'] or '—'}" for p in payments)
    out.append("Thank you for your business.")
    return "\n".join(out)


def order_details(order, user):
    lines = query("SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order["id"],))
    payments = query("SELECT * FROM payments WHERE order_id=? AND status='approved' ORDER BY id", (order["id"],))
    pending = query("SELECT * FROM payments WHERE order_id=? AND status='pending' ORDER BY id", (order["id"],))
    total = sum(x["qty"]*x["unit_price"] for x in lines); paid = sum(p["amount"] for p in payments)
    st.markdown(f"### {order['order_no']} · {order['customer']}")
    a,b,c = st.columns(3); a.metric("Invoice total", ksh(total)); b.metric("Approved payments", ksh(paid)); c.metric("Balance", ksh(max(total-paid,0)))
    st.caption(f"Status: **{order['status'].replace('_',' ').title()}** · {order['created_at']}")
    st.dataframe([{"Item":x["item_name"],"Qty":x["qty"],"Unit price":ksh(x["unit_price"]),"Total":ksh(x["qty"]*x["unit_price"])} for x in lines], use_container_width=True, hide_index=True)
    st.download_button("Download invoice", receipt_text(order,lines,[],"CUSTOMER INVOICE"), file_name=f"{order['order_no']}-invoice.txt", mime="text/plain", key=f"invoice_{order['id']}")
    if pending:
        st.warning(f"{len(pending)} payment(s) awaiting Accounts approval. Receipts and picking are unavailable until approved.")
    if user["role"] in ("admin","manager","cashier") and order["status"] not in ("cancelled","delivered") and total-paid > 0:
        with st.form(f"payment_{order['id']}"):
            st.subheader("Record customer payment for Accounts review")
            amount = st.number_input("Amount received", min_value=0.01, max_value=float(total-paid), value=float(total-paid), step=100.0)
            method = st.selectbox("Payment method", ["Cash","M-Pesa","Bank transfer","Card","Other"], key=f"method_{order['id']}")
            reference = st.text_input("Payment transaction reference", key=f"reference_{order['id']}")
            submit = st.form_submit_button("Submit payment for approval", type="primary")
        if submit:
            execute("INSERT INTO payments(order_id,amount,method,reference,received_by,paid_at,status) VALUES(?,?,?,?,?,?, 'pending')", (order["id"], amount, method, reference.strip(), user["id"], now_iso()))
            st.success("Payment submitted to Accounts. A receipt will be available after approval.")
            st.rerun()
    if payments:
        st.subheader("Approved payment receipts")
        for p in payments:
            st.write(f"{p['paid_at']} · {ksh(p['amount'])} · {p['method']} · Ref: {p['reference'] or '—'}")
            customer_copy = receipt_text(order,lines,[p],"CUSTOMER PAYMENT RECEIPT")
            shop_copy = receipt_text(order,lines,[p],"SHOPKEEPER PAYMENT / PICKING COPY")
            left,right=st.columns(2)
            left.download_button("Download customer receipt",customer_copy,file_name=f"{order['order_no']}-receipt-{p['id']}.txt",mime="text/plain",key=f"customer_receipt_{p['id']}")
            right.download_button("Download shopkeeper copy",shop_copy,file_name=f"{order['order_no']}-shopkeeper-copy-{p['id']}.txt",mime="text/plain",key=f"shop_copy_{p['id']}")


def orders_page(user):
    st.title("Orders, invoices & receipts")
    orders = query("SELECT * FROM orders ORDER BY id DESC LIMIT 300")
    if not orders:
        st.info("No orders yet. Create one from New order."); return
    st.dataframe([{"Invoice":o["order_no"],"Date":o["created_at"][:10],"Customer":o["customer"],"Status":o["status"].replace("_"," ").title(),"Total":ksh(order_total(o["id"])),"Approved paid":ksh(paid_total(o["id"]))} for o in orders],use_container_width=True,hide_index=True)
    labels={f"{o['order_no']} · {o['customer']} · {o['status'].replace('_',' ').title()}":o for o in orders}
    selected_label=st.selectbox("Open an invoice",list(labels))
    order_details(labels[selected_label],user)


def approvals_page(user):
    st.title("Accounts — payment approvals")
    st.caption("Verify cash, M-Pesa/bank reference or other proof against the actual payment before approval. Approval issues the receipt and releases a fully paid order to picking.")
    pending = query("SELECT p.*,o.order_no,o.customer,u.full_name AS cashier FROM payments p JOIN orders o ON o.id=p.order_id LEFT JOIN users u ON u.id=p.received_by WHERE p.status='pending' ORDER BY p.id")
    if not pending:
        st.success("No payments are waiting for approval."); return
    for p in pending:
        with st.container(border=True):
            st.markdown(f"### {p['order_no']} · {p['customer']}")
            st.write(f"**Submitted by:** {p['cashier'] or 'Staff'} · **Amount:** {ksh(p['amount'])} · **Method:** {p['method']} · **Reference:** {p['reference'] or 'Not supplied'}")
            note=st.text_input("Approval note (optional)",key=f"approval_note_{p['id']}")
            a,b=st.columns(2)
            if a.button("Approve payment",type="primary",key=f"approve_{p['id']}"):
                with connect() as con:
                    con.execute("UPDATE payments SET status='approved',approved_by=?,approved_at=?,approval_note=? WHERE id=? AND status='pending'",(user["id"],now_iso(),note.strip(),p["id"]))
                    order=con.execute("SELECT * FROM orders WHERE id=?",(p["order_id"],)).fetchone()
                    total=con.execute("SELECT COALESCE(SUM(qty*unit_price),0) FROM order_items WHERE order_id=?",(p["order_id"],)).fetchone()[0]
                    approved=con.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE order_id=? AND status='approved'",(p["order_id"],)).fetchone()[0]
                    if approved >= total-0.001:
                        con.execute("UPDATE orders SET status='paid_awaiting_pick' WHERE id=?",(p["order_id"],))
                        shopkeepers=con.execute("SELECT id FROM users WHERE role='shopkeeper' AND active=1").fetchall()
                        for shop in shopkeepers:
                            con.execute("INSERT INTO notifications(user_id,order_id,message,created_at) VALUES(?,?,?,?)",(shop["id"],p["order_id"],f"Accounts approved payment for {p['order_no']}; receipt and order are ready for picking.",now_iso()))
                    else:
                        con.execute("UPDATE orders SET status='part_paid' WHERE id=?",(p["order_id"],))
                st.success("Payment approved. The customer receipt is now available." ); st.rerun()
            if b.button("Reject payment",key=f"reject_{p['id']}"):
                if not note.strip():
                    st.error("Add a note explaining why the payment is rejected.")
                else:
                    execute("UPDATE payments SET status='rejected',approved_by=?,approved_at=?,approval_note=? WHERE id=? AND status='pending'",(user["id"],now_iso(),note.strip(),p["id"]))
                    st.warning("Payment rejected. Cashier can review the note and submit a corrected payment."); st.rerun()


def picking_page(user):
    st.title("Shopkeeper picking desk")
    notices=query("SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC",(user["id"],))
    if notices: st.info(f"{len(notices)} new payment/order notification(s).")
    orders=query("SELECT * FROM orders WHERE status='paid_awaiting_pick' ORDER BY id")
    if not orders: st.success("No approved, fully-paid orders are waiting to be picked."); return
    for order in orders:
        with st.container(border=True):
            st.markdown(f"### {order['order_no']} — {order['customer']}")
            lines=query("SELECT * FROM order_items WHERE order_id=?",(order["id"],))
            pays=query("SELECT * FROM payments WHERE order_id=? AND status='approved' ORDER BY id",(order["id"],))
            st.dataframe([{"Pick item":r["item_name"],"Quantity":r["qty"],"Unit":r["unit"]} for r in lines],use_container_width=True,hide_index=True)
            st.write(f"Accounts-approved payment: **{ksh(paid_total(order['id']))} / {ksh(order_total(order['id']))}**")
            if order["delivery_required"]: st.caption(f"Delivery requested · {order['delivery_address']}")
            st.download_button("Download shopkeeper receipt / pick slip",receipt_text(order,lines,pays,"SHOPKEEPER PICKING COPY"),file_name=f"{order['order_no']}-pick-slip.txt",mime="text/plain",key=f"pick_slip_{order['id']}")
            delivery_users=query("SELECT id,full_name FROM users WHERE role='delivery' AND active=1 ORDER BY full_name") if order["delivery_required"] else []
            if order["delivery_required"] and delivery_users:
                names={d["full_name"]:d for d in delivery_users}
                assigned_name=st.selectbox("Assign delivery person",list(names),key=f"assign_{order['id']}")
                label="Confirm items picked & notify delivery"
            else:
                names={}; assigned_name=None
                label="Confirm items picked — customer collection"
                if order["delivery_required"]: st.error("No active delivery-person account exists. Ask the Administrator to create one.")
            if st.button(label,type="primary",key=f"picked_{order['id']}") and (not order["delivery_required"] or assigned_name):
                insufficient=[x["item_name"] for x in lines if x["qty"]>stock_qty(x["item_id"])]
                if insufficient: st.error("Not enough stock: "+", ".join(insufficient))
                else:
                    with connect() as con:
                        if order["delivery_required"]:
                            delivery=names[assigned_name]
                            con.execute("UPDATE orders SET status='ready_for_delivery',picked_by=?,picked_at=? WHERE id=?",(user["id"],now_iso(),order["id"]))
                            con.execute("INSERT INTO delivery_tasks(order_id,assigned_to,status,assigned_at) VALUES(?,?,?,?)",(order["id"],delivery["id"],"assigned",now_iso()))
                            con.execute("INSERT INTO notifications(user_id,order_id,message,created_at) VALUES(?,?,?,?)",(delivery["id"],order["id"],f"{order['order_no']} is picked and ready for delivery to {order['delivery_address']}.",now_iso()))
                        else:
                            con.execute("UPDATE orders SET status='ready_for_pickup',picked_by=?,picked_at=? WHERE id=?",(user["id"],now_iso(),order["id"]))
                        con.execute("UPDATE notifications SET read_at=? WHERE order_id=? AND user_id=? AND read_at IS NULL",(now_iso(),order["id"],user["id"]))
                    st.success("Picking confirmed; available stock is updated."); st.rerun()


def deliveries_page(user):
    st.title("Delivery assignments")
    for n in query("SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC",(user["id"],)): st.info(n["message"])
    tasks=query("SELECT d.*,o.order_no,o.customer,o.phone,o.delivery_address FROM delivery_tasks d JOIN orders o ON o.id=d.order_id WHERE d.assigned_to=? ORDER BY d.id DESC",(user["id"],))
    if not tasks: st.info("No delivery assignments yet."); return
    for task in tasks:
        with st.container(border=True):
            st.markdown(f"### {task['order_no']} — {task['customer']}")
            st.write(f"**Address:** {task['delivery_address'] or '—'} · **Phone:** {task['phone'] or '—'}")
            lines=query("SELECT * FROM order_items WHERE order_id=?",(task["order_id"],))
            st.dataframe([{"Item":x["item_name"],"Quantity":x["qty"],"Unit":x["unit"]} for x in lines],use_container_width=True,hide_index=True)
            if task["status"]=="assigned" and st.button("Acknowledge & collect items",type="primary",key=f"collect_{task['id']}"):
                with connect() as con:
                    con.execute("UPDATE delivery_tasks SET status='collected',collected_at=? WHERE id=?",(now_iso(),task["id"]))
                    con.execute("UPDATE orders SET status='out_for_delivery' WHERE id=?",(task["order_id"],))
                    con.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND order_id=? AND read_at IS NULL",(now_iso(),user["id"],task["order_id"]))
                st.rerun()
            elif task["status"]=="collected":
                st.warning("In transit")
                if st.button("Mark delivered",type="primary",key=f"delivered_{task['id']}"):
                    with connect() as con:
                        con.execute("UPDATE delivery_tasks SET status='delivered',delivered_at=? WHERE id=?",(now_iso(),task["id"]))
                        con.execute("UPDATE orders SET status='delivered' WHERE id=?",(task["order_id"],))
                    st.success("Delivery completed."); st.rerun()
            else: st.success("Delivered")


def inventory_page():
    st.title("Inventory & stock")
    tab_stock,tab_receive,tab_add=st.tabs(["Stock levels","Receive stock","Add item"])
    with tab_stock:
        items=query("SELECT * FROM items ORDER BY name")
        st.dataframe([{"Item":i["name"],"Unit":i["unit"],"Available":stock_qty(i["id"]),"Reorder level":i["reorder_level"],"Buying price":ksh(i["cost"]),"Selling price":ksh(i["price"])} for i in items],use_container_width=True,hide_index=True)
        low=[i["name"] for i in items if stock_qty(i["id"])<=i["reorder_level"]]
        if low: st.warning("Reorder alert: "+", ".join(low))
    with tab_receive:
        suppliers=query("SELECT id,name FROM suppliers ORDER BY name"); items=query("SELECT id,name,cost FROM items ORDER BY name")
        if not suppliers or not items: st.info("Add a supplier and stock item first.")
        else:
            supplier_map={x["name"]:x for x in suppliers}; item_map={x["name"]:x for x in items}
            with st.form("receive_stock"):
                received_date=st.date_input("Date",value=date.today()); supplier_name=st.selectbox("Supplier",list(supplier_map)); item_name=st.selectbox("Item",list(item_map)); item=item_map[item_name]
                qty=st.number_input("Quantity received",min_value=0.01,step=1.0,value=1.0); cost=st.number_input("Unit cost",min_value=0.0,value=float(item["cost"] or 0),step=10.0)
                submit=st.form_submit_button("Record received stock",type="primary")
            if submit:
                execute("INSERT INTO stock_in(date,supplier_id,item_id,qty,cost) VALUES(?,?,?,?,?)",(received_date.isoformat(),supplier_map[supplier_name]["id"],item["id"],qty,cost)); st.success("Stock receipt recorded."); st.rerun()
        data=query("SELECT si.date,s.name AS supplier,i.name AS item,si.qty,si.cost FROM stock_in si JOIN suppliers s ON s.id=si.supplier_id JOIN items i ON i.id=si.item_id ORDER BY si.id DESC")
        st.dataframe([{"Date":r["date"],"Supplier":r["supplier"],"Item":r["item"],"Quantity":r["qty"],"Unit cost":ksh(r["cost"])} for r in data],use_container_width=True,hide_index=True)
    with tab_add:
        with st.form("add_item"):
            name=st.text_input("Item name"); unit=st.text_input("Unit",value="pcs"); cost=st.number_input("Buying price",min_value=0.0,step=10.0); price=st.number_input("Selling price",min_value=0.0,step=10.0); reorder=st.number_input("Reorder level",min_value=0,step=1); submit=st.form_submit_button("Add item")
        if submit:
            if not name.strip(): st.error("Enter an item name.")
            else:
                try: execute("INSERT INTO items(name,unit,cost,price,reorder_level) VALUES(?,?,?,?,?)",(name.strip(),unit.strip(),cost,price,reorder)); st.success("Item added."); st.rerun()
                except sqlite3.IntegrityError: st.error("That item already exists.")


def suppliers_page():
    st.title("Suppliers")
    with st.form("supplier"):
        name=st.text_input("Supplier name"); phone=st.text_input("Phone"); submit=st.form_submit_button("Add supplier")
    if submit:
        if name.strip(): execute("INSERT INTO suppliers(name,phone) VALUES(?,?)",(name.strip(),phone.strip())); st.success("Supplier added."); st.rerun()
        else: st.error("Enter supplier name.")
    st.dataframe(query("SELECT name AS Supplier,phone AS Phone FROM suppliers ORDER BY name"),use_container_width=True,hide_index=True)


def accounts_page():
    st.title("Accounts")
    tab_exp,tab_income,tab_ledger=st.tabs(["Expenses","Other income","Approved payments"])
    with tab_exp:
        with st.form("expense"):
            d=st.date_input("Date",value=date.today(),key="exp_date"); category=st.selectbox("Category",["Rent","Electricity","Transport","Salaries","Licences","Repairs","Other"]); desc=st.text_input("Description",key="exp_desc"); amount=st.number_input("Amount",min_value=0.0,step=100.0,key="exp_amount"); submit=st.form_submit_button("Record expense")
        if submit: execute("INSERT INTO expenses(date,category,description,amount) VALUES(?,?,?,?)",(d.isoformat(),category,desc,amount)); st.success("Expense recorded."); st.rerun()
        data=query("SELECT date,category,description,amount FROM expenses ORDER BY id DESC"); st.dataframe([{"Date":x["date"],"Category":x["category"],"Description":x["description"],"Amount":ksh(x["amount"])} for x in data],use_container_width=True,hide_index=True)
    with tab_income:
        with st.form("income"):
            d=st.date_input("Date",value=date.today(),key="inc_date"); desc=st.text_input("Income source"); amount=st.number_input("Amount",min_value=0.0,step=100.0,key="inc_amount"); submit=st.form_submit_button("Record income")
        if submit: execute("INSERT INTO income(date,description,amount) VALUES(?,?,?)",(d.isoformat(),desc,amount)); st.success("Income recorded."); st.rerun()
        data=query("SELECT date,description,amount FROM income ORDER BY id DESC"); st.dataframe([{"Date":x["date"],"Source":x["description"],"Amount":ksh(x["amount"])} for x in data],use_container_width=True,hide_index=True)
    with tab_ledger:
        data=query("SELECT p.paid_at,o.order_no,o.customer,p.amount,p.method,p.reference,u.full_name FROM payments p JOIN orders o ON o.id=p.order_id LEFT JOIN users u ON u.id=p.approved_by WHERE p.status='approved' ORDER BY p.id DESC")
        st.dataframe([{"Approved at":x["paid_at"],"Invoice":x["order_no"],"Customer":x["customer"],"Amount":ksh(x["amount"]),"Method":x["method"],"Reference":x["reference"],"Approved by":x["full_name"]} for x in data],use_container_width=True,hide_index=True)


def workers_page():
    st.title("Workers")
    with st.form("worker"):
        name=st.text_input("Full name"); role=st.text_input("Job title"); phone=st.text_input("Phone"); salary=st.number_input("Monthly salary",min_value=0.0,step=1000.0); submit=st.form_submit_button("Add worker")
    if submit:
        if name.strip(): execute("INSERT INTO workers(name,role,phone,salary) VALUES(?,?,?,?)",(name.strip(),role.strip(),phone.strip(),salary)); st.success("Worker added."); st.rerun()
        else: st.error("Enter worker name.")
    data=query("SELECT name,role,phone,salary FROM workers ORDER BY name"); st.dataframe([{"Name":x["name"],"Job title":x["role"],"Phone":x["phone"],"Monthly salary":ksh(x["salary"])} for x in data],use_container_width=True,hide_index=True)


if "user_id" not in st.session_state: st.session_state.user_id=None
users=query("SELECT * FROM users WHERE id=? AND active=1",(st.session_state.user_id,)) if st.session_state.user_id else []
if not users:
    st.session_state.user_id=None; login_screen(); st.stop()
user=users[0]
with st.sidebar:
    st.markdown("## 🛠️ ShabikiHardware"); st.caption(f"{user['full_name']} · {ROLE_LABELS.get(user['role'],user['role'])}")
    if st.button("Sign out",use_container_width=True): st.session_state.user_id=None; st.session_state.cart=[]; st.rerun()
    page=st.radio("Workspace",ROLE_PAGES.get(user["role"],["Dashboard"]))

if page=="Dashboard": dashboard(user)
elif page=="New order" and user["role"] in ("admin","manager","cashier"): new_order_page(user)
elif page=="Orders & receipts": orders_page(user)
elif page=="Payment approvals" and user["role"] in ("admin","manager","accountant"): approvals_page(user)
elif page=="Picking desk" and user["role"] in ("admin","manager","shopkeeper"): picking_page(user)
elif page=="Deliveries" and user["role"] in ("admin","manager","delivery"): deliveries_page(user)
elif page=="Inventory" and user["role"] in ("admin","manager","shopkeeper"): inventory_page()
elif page=="Suppliers" and user["role"] in ("admin","manager"): suppliers_page()
elif page=="Accounts" and user["role"] in ("admin","manager","accountant"): accounts_page()
elif page=="Workers" and user["role"] in ("admin","manager"): workers_page()
elif page=="User accounts" and user["role"]=="admin": users_page(user)
else: st.error("You do not have permission to access this section.")
