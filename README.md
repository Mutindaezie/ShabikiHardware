# ShabikiHardware

A Streamlit hardware-shop management app for role-based staff access, invoices, payment approval, receipts, stock picking, and delivery coordination.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Order and payment workflow

1. A cashier enters the customer's items and details and creates an invoice.
2. The cashier records the customer's payment and submits it for Accounts review. It is not treated as paid yet.
3. An Accountant (or Administrator/Manager) verifies the payment and approves or rejects it. A receipt is only available after approval.
4. After the approved payments cover the invoice total, the order appears in the shopkeeper's picking desk, with a shopkeeper receipt/pick-slip download.
5. The shopkeeper confirms the items picked. Stock-out is then reflected in inventory. For delivery orders, the shopkeeper assigns a delivery person and the app creates an in-app notification for them.
6. The delivery person acknowledges collection and marks the order delivered.

## Roles and access

On first launch, create the initial Administrator account. There are no built-in credentials. The Administrator creates named staff accounts with unique usernames and passwords. Roles include Cashier, Shopkeeper/Storekeeper, Delivery person, Accountant, Manager, and Administrator.

## Deploy to Streamlit Community Cloud

1. Select the `Mutindaezie/ShabikiHardware` GitHub repository.
2. Select `copilot/convert-to-streamlit` (or merge this branch and select `main`).
3. Set **Main file path** to `streamlit_app.py`.
4. Deploy/reboot and create the initial Administrator account if this is a fresh database.

## Data warning

This version uses local SQLite (`shabiki.db`). Streamlit Community Cloud's local filesystem is not a suitable persistent production database: data can be lost when an app restarts/rebuilds, and multiple replicas will not share the database file. Configure a persistent hosted database and backups before relying on it for business records.
