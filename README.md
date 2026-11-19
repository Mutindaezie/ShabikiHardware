# ShabikiHardware

A hardware management system for inventory, suppliers, sales, accounts, and workers.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy to Streamlit Community Cloud

1. Push this repository to GitHub.
2. Open Streamlit Community Cloud.
3. Select `Mutindaezie/ShabikiHardware`.
4. Select the `main` or `copilot/convert-to-streamlit` branch.
5. Set **Main file path** to `streamlit_app.py`.
6. Deploy.

SQLite data is stored in `shabiki.db`. For durable production hosting, replace SQLite with a persistent database such as PostgreSQL or Turso.
