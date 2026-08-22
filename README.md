# Paytm Business AI

AI Co-Pilot prototype for small Indian merchants. The app combines representative Paytm-style transaction data, merchant-entered inventory, invoice/OCR input, and analytics to explain what happened and suggest what to do next.

## Structure

- `backend/` - FastAPI app, PostgreSQL inventory store, CSV transaction analytics, LLM/OCR provider interfaces
- `frontend/` - React + Vite + Tailwind dashboard
- `data/` - synthetic prototype transaction and inventory data

## Run

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set DATABASE_URL=postgresql+psycopg2://paytm_ai:YOUR_PASSWORD@localhost/paytm_ai
python -m alembic -c alembic.ini upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Environment

Backend:

- `DATABASE_URL=postgresql+psycopg2://USER@HOST/DATABASE` is required
- `LLM_PROVIDER=mock` by default
- `LLM_API_KEY` optional, only needed for a real provider implementation
- `OCR_PROVIDER=mock` by default

Frontend:

- `VITE_API_BASE_URL=http://localhost:8000`

The frontend never reads AI or OCR secrets.

## PostgreSQL

Create the database and role with PostgreSQL's `psql`:

```sql
CREATE USER paytm_ai WITH PASSWORD 'YOUR_PASSWORD';
CREATE DATABASE paytm_ai OWNER paytm_ai;
GRANT ALL PRIVILEGES ON DATABASE paytm_ai TO paytm_ai;
```

Then run migrations from `backend/`:

```bash
python -m alembic -c alembic.ini upgrade head
```

The historical transaction dataset remains in `data/transactions.csv`. It is not copied into PostgreSQL.
