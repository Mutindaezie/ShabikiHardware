# ShabikiHardware

A Streamlit hardware-shop management app for role-based staff access, inventory, customer orders, payments, picking, and delivery coordination.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Staff roles and order flow

On the first launch, create the initial Administrator account. There are no shared/default credentials. The Administrator creates individual staff logins and assigns roles:

- **Cashier:** create customer orders/invoices, record payments, issue receipts.
- **Shopkeeper / Storekeeper:** view paid orders, download the picking copy, confirm items picked, and update stock-out.
- **Delivery person:** receives in-app assignment notifications, acknowledges collection, and marks deliveries complete.
- **Manager:** oversee orders and manage inventory, suppliers, accounts, and workers.
- **Accountant:** review orders/payments and manage accounts.
- **Administrator:** all sections, including user-account management.

Order workflow: cashier creates an invoice → cashier records customer payment → app issues customer and shopkeeper receipt downloads and queues the paid order for picking → shopkeeper confirms picking (stock is deducted at this point) → for delivery orders the shopkeeper assigns an active delivery user, who receives an in-app notification and updates delivery status.

## Deploy to Streamlit Community Cloud

1. Select the `Mutindaezie/ShabikiHardware` GitHub repository.
2. Select branch `copilot/convert-to-streamlit` (or merge this branch and choose `main`).
3. Set **Main file path** to `streamlit_app.py`.
4. Deploy. On the first visit, set up the Administrator account.

## Data and deployment note

This version uses a local SQLite database file (`shabiki.db`). Streamlit Community Cloud's local filesystem is not a suitable persistent production database: data can be lost when an app is restarted/rebuilt, and multiple app replicas will not share this file. Before relying on it for real business records, configure a persistent hosted database and regular backups. Keep administrator credentials private and create separate accounts for staff.
