import streamlit as st
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path("shabiki.db")
st.set_page_config(page_title="ShabikiHardware", page_icon="🛠️", layout="wide")


def connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    con = connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        unit TEXT,
        cost REAL,
        price REAL,
        reorder_level INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT
    );
    CREATE TABLE IF NOT EXISTS stock_in (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        supplier_id INTEGER,
        item_id INTEGER,
        qty REAL,
        cost REAL
    );
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        customer TEXT,
        item_id INTEGER,
        qty REAL,
        price REAL,
        paid REAL
    );
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        category TEXT,
        description TEXT,
        amount REAL
    );
    CREATE TABLE IF NOT EXISTS income (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        description TEXT,
        amount REAL
    );
    CREATE TABLE IF NOT EXISTS workers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        role TEXT,
        phone TEXT,
        salary REAL
    );
    """)
    con.commit()
    if con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
        con.executemany("INSERT INTO items(name,unit,cost,price,reorder_level) VALUES(?,?,?,?,?)", [
            ("Cement 50kg", "bags", 640, 780, 40),
            ("Roofing sheet 3m", "pcs", 930, 1150, 30),
            ("Nails 3 inch", "kg", 150, 210, 25),
            ("Paint 4L", "tins", 1100, 1450, 12),
            ("PVC pipe 4 inch", "pcs", 720, 950, 15),
        ])
        con.executemany("INSERT INTO suppliers(name,phone) VALUES(?,?)", [
            ("Bamburi Distributors", "0711 000 111"),
            ("Mabati Depot", "0722 000 222"),
            ("Nairobi Tools & Paints", "0733 000 333"),
        ])
        con.commit()
    con.close()


init_db()


def rows(sql, params=()):
    con = connect()
    data = con.execute(sql, params).fetchall()
    con.close()
    return data


def stock_qty(item_id):
    received = rows("SELECT COALESCE(SUM(qty),0) FROM stock_in WHERE item_id=?", (item_id,))[0][0]
    sold = rows("SELECT COALESCE(SUM(qty),0) FROM sales WHERE item_id=?", (item_id,))[0][0]
    return (received or 0) - (sold or 0)


def ksh(value):
    return f"KSh {value:,.0f}"


def execute(sql, params=()):
    con = connect()
    con.execute(sql, params)
    con.commit()
    con.close()


with st.sidebar:
    st.markdown("## 🛠️ ShabikiHardware")
    page = st.radio("Navigation", ["Dashboard", "Inventory", "Suppliers", "Sales", "Accounts", "Workers"])

if page == "Dashboard":
    st.title("Dashboard")
    sales_today = rows("SELECT COALESCE(SUM(qty*price),0) FROM sales WHERE date=?", (date.today().isoformat(),))[0][0]
    month_sales = rows("SELECT COALESCE(SUM(qty*price),0) FROM sales WHERE substr(date,1,7)=?", (date.today().isoformat()[:7],))[0][0]
    expenses = rows("SELECT COALESCE(SUM(amount),0) FROM expenses")[0][0]
    income = rows("SELECT COALESCE(SUM(amount),0) FROM income")[0][0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sales today", ksh(sales_today))
    c2.metric("Sales this month", ksh(month_sales))
    c3.metric("Expenses", ksh(expenses))
    c4.metric("Other income", ksh(income))
    data = rows("SELECT name,reorder_level,id FROM items ORDER BY name")
    st.subheader("Stock levels")
    st.dataframe([{"Item": n, "Quantity": stock_qty(i), "Reorder level": level} for n, level, i in data], use_container_width=True, hide_index=True)

elif page == "Inventory":
    st.title("Stock & Inventory")
    tab1, tab2 = st.tabs(["Stock items", "Receive stock"])
    with tab1:
        with st.expander("Add stock item"):
            with st.form("add_item"):
                name = st.text_input("Item name")
                unit = st.text_input("Unit", value="pcs")
                cost = st.number_input("Buying price", min_value=0.0, step=10.0)
                price = st.number_input("Selling price", min_value=0.0, step=10.0)
                reorder = st.number_input("Reorder level", min_value=0, step=1)
                if st.form_submit_button("Add item"):
                    if name:
                        try:
                            execute("INSERT INTO items(name,unit,cost,price,reorder_level) VALUES(?,?,?,?,?)", (name, unit, cost, price, reorder))
                            st.success("Item added")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("An item with that name already exists.")
        data = rows("SELECT id,name,unit,cost,price,reorder_level FROM items ORDER BY name")
        st.dataframe([{"ID": r[0], "Item": r[1], "Unit": r[2], "Buying price": ksh(r[3]), "Selling price": ksh(r[4]), "Available": stock_qty(r[0]), "Reorder level": r[5]} for r in data], use_container_width=True, hide_index=True)
    with tab2:
        suppliers = rows("SELECT id,name FROM suppliers")
        items = rows("SELECT id,name,cost FROM items")
        if suppliers and items:
            with st.form("receive_stock"):
                received_date = st.date_input("Date", value=date.today())
                supplier = st.selectbox("Supplier", suppliers, format_func=lambda x: x[1])
                item = st.selectbox("Item", items, format_func=lambda x: x[1])
                qty = st.number_input("Quantity", min_value=1.0, step=1.0)
                unit_cost = st.number_input("Unit cost", min_value=0.0, value=float(item[2]), step=10.0)
                if st.form_submit_button("Receive stock"):
                    execute("INSERT INTO stock_in(date,supplier_id,item_id,qty,cost) VALUES(?,?,?,?,?)", (received_date.isoformat(), supplier[0], item[0], qty, unit_cost))
                    st.success("Stock received")
                    st.rerun()
        data = rows("SELECT si.date,s.name,i.name,si.qty,si.cost FROM stock_in si JOIN suppliers s ON s.id=si.supplier_id JOIN items i ON i.id=si.item_id ORDER BY si.id DESC")
        st.dataframe([{"Date": r[0], "Supplier": r[1], "Item": r[2], "Quantity": r[3], "Unit cost": ksh(r[4])} for r in data], use_container_width=True, hide_index=True)

elif page == "Suppliers":
    st.title("Suppliers")
    with st.expander("Add supplier"):
        with st.form("add_supplier"):
            name = st.text_input("Supplier name")
            phone = st.text_input("Phone")
            if st.form_submit_button("Save supplier"):
                if name:
                    execute("INSERT INTO suppliers(name,phone) VALUES(?,?)", (name, phone))
                    st.success("Supplier added")
                    st.rerun()
    data = rows("SELECT id,name,phone FROM suppliers ORDER BY name")
    st.dataframe([{"ID": r[0], "Name": r[1], "Phone": r[2]} for r in data], use_container_width=True, hide_index=True)

elif page == "Sales":
    st.title("Sales")
    with st.expander("Record a sale"):
        items = rows("SELECT id,name,price FROM items")
        if items:
            with st.form("sale"):
                sale_date = st.date_input("Date", value=date.today())
                customer = st.text_input("Customer", value="Walk-in")
                item = st.selectbox("Item", items, format_func=lambda x: x[1])
                available = stock_qty(item[0])
                st.caption(f"Available stock: {available}")
                qty = st.number_input("Quantity", min_value=1.0, step=1.0)
                price = st.number_input("Unit price", min_value=0.0, value=float(item[2]), step=10.0)
                paid = st.number_input("Amount paid", min_value=0.0, step=100.0)
                if st.form_submit_button("Save sale"):
                    if qty <= available:
                        execute("INSERT INTO sales(date,customer,item_id,qty,price,paid) VALUES(?,?,?,?,?,?)", (sale_date.isoformat(), customer, item[0], qty, price, paid))
                        st.success("Sale recorded")
                        st.rerun()
                    else:
                        st.error("Not enough stock")
    data = rows("SELECT s.id,s.date,s.customer,i.name,s.qty,s.price,s.paid FROM sales s JOIN items i ON i.id=s.item_id ORDER BY s.id DESC")
    st.dataframe([{"Invoice": f"INV-{r[0]:04d}", "Date": r[1], "Customer": r[2], "Item": r[3], "Quantity": r[4], "Unit price": ksh(r[5]), "Total": ksh(r[4]*r[5]), "Paid": ksh(r[6]), "Balance": ksh(r[4]*r[5]-r[6])} for r in data], use_container_width=True, hide_index=True)

elif page == "Accounts":
    st.title("Accounts")
    tab1, tab2 = st.tabs(["Expenses", "Other income"])
    with tab1:
        with st.form("expense"):
            expense_date = st.date_input("Expense date", value=date.today())
            category = st.selectbox("Category", ["Rent", "Electricity", "Transport", "Salaries", "Licences", "Repairs", "Other"])
            description = st.text_input("Description")
            amount = st.number_input("Amount", min_value=0.0, step=100.0)
            if st.form_submit_button("Record expense"):
                execute("INSERT INTO expenses(date,category,description,amount) VALUES(?,?,?,?)", (expense_date.isoformat(), category, description, amount))
                st.success("Expense recorded")
                st.rerun()
        data = rows("SELECT date,category,description,amount FROM expenses ORDER BY id DESC")
        st.dataframe([{"Date": r[0], "Category": r[1], "Description": r[2], "Amount": ksh(r[3])} for r in data], use_container_width=True, hide_index=True)
    with tab2:
        with st.form("income"):
            income_date = st.date_input("Income date", value=date.today())
            description = st.text_input("Source")
            amount = st.number_input("Amount", min_value=0.0, step=100.0, key="income_amount")
            if st.form_submit_button("Record income"):
                execute("INSERT INTO income(date,description,amount) VALUES(?,?,?)", (income_date.isoformat(), description, amount))
                st.success("Income recorded")
                st.rerun()
        data = rows("SELECT date,description,amount FROM income ORDER BY id DESC")
        st.dataframe([{"Date": r[0], "Source": r[1], "Amount": ksh(r[2])} for r in data], use_container_width=True, hide_index=True)

else:
    st.title("Workers")
    with st.expander("Add worker"):
        with st.form("worker"):
            name = st.text_input("Full name")
            role = st.text_input("Role")
            phone = st.text_input("Phone")
            salary = st.number_input("Monthly salary", min_value=0.0, step=1000.0)
            if st.form_submit_button("Add worker"):
                if name:
                    execute("INSERT INTO workers(name,role,phone,salary) VALUES(?,?,?,?)", (name, role, phone, salary))
                    st.success("Worker added")
                    st.rerun()
    data = rows("SELECT id,name,role,phone,salary FROM workers ORDER BY name")
    st.dataframe([{"ID": r[0], "Name": r[1], "Role": r[2], "Phone": r[3], "Salary": ksh(r[4])} for r in data], use_container_width=True, hide_index=True)
