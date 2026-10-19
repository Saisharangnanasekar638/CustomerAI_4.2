# CustomerAI 4.2 - setup with an online database (Supabase)

Use **Python 3.12** (3.14 has no ready-made pandas/numpy wheels yet, which is what caused the
"vswhere.exe" build error). Create the environment with `py -3.12 -m venv .venv`.

## 1. Create the database (once)
1. supabase.com -> New project (any region near you; save the database password).
2. Project Settings -> Database -> Connection string -> **Session pooler** -> copy the URI.
3. Copy `.env.example` to `backend/.env` in the project root and paste it as `DATABASE_URL`
   (replace `[YOUR-PASSWORD]`). If the password has `@ # / : ? %`, use the `DB_HOST/DB_USER/...`
   block in `.env.example` instead, which needs no encoding.

## 2. Load your data (once)
    pip install -r requirements.txt
    python scripts/check_connection.py
    python scripts/load_data.py --csv path\to\Indian_Banking_CRM_Complete.csv
    (or, to copy your existing local MySQL table: set SOURCE_DATABASE_URL in .env, then
     python scripts/load_data.py --from-source)

The loader converts text numbers such as "1,23,456.50" to real numbers and Yes/No columns to 1/0.

## 3. Run
    uvicorn backend.main:app --port 8000          (project root, terminal 1)
    cd frontend ; streamlit run app.py            (terminal 2)

Health check: http://localhost:8000/api/health

## 4. Upload your own data from the app
Open **Upload and Analyze** in the sidebar. Choose a CSV or Excel file, read the file check, explore it
(priority customers, any chart, column profile), then optionally save it. Saving needs `ADMIN_KEY` set on the
API (see `.env.example`); you type that key in the page. "Replace" swaps all data, "Add" updates matching
customer_ids and appends new ones. A file needs `customer_id` and `propensity_score` to be saved; without
`propensity_score` you can still analyze it on that page.

## 5. Hosting (nothing runs on your computer)
Three free pieces, each in the cloud:

| Piece | Where | What to set |
|---|---|---|
| Database | Supabase (already done) | nothing |
| API | Render (Web Service, or `render.yaml` Blueprint) | build `pip install -r requirements.txt`, start `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`, env: `PYTHON_VERSION=3.12.7`, `DATABASE_URL` (Session pooler string), `ADMIN_KEY`, `CORS_ORIGINS` |
| App | Streamlit Community Cloud | repo, main file `frontend/app.py`, Secrets: `API_BASE_URL = "https://your-api.onrender.com"` |

Order: push the project to a private GitHub repo (`backend/.env` is in `.gitignore`), deploy the API, open
`https://your-api.onrender.com/api/health` (expect `"status":"ok"`), then deploy the app with that address.
Finally set `CORS_ORIGINS` on Render to the app's address.

Notes: Render's free API sleeps after about 15 minutes idle, so the first visit afterwards takes up to a minute.
A free monitor (for example UptimeRobot) pinging `/api/health` every 5 minutes keeps it awake.
Deploy the whole project folder, not only `frontend/`: the Upload page reuses `backend/ingest.py`.
Alternatives: Railway or Fly.io for the API; Hugging Face Spaces (Streamlit) for the app.
