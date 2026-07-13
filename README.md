# Sales Suite — Flask Web App

A full-featured Flask application with login/register, dashboard, file management,
weather lookup, and sales analysis with charts. Uses SQLite for storage and
Bootstrap 5 + Chart.js for the UI.

## Features
- User registration & login (hashed passwords, session-based auth)
- Dashboard with quick stats
- File upload / download / delete (per-user storage)
- Weather lookup via the free Open-Meteo API (no API key needed)
- Sales analysis: upload a CSV/XLSX, get totals + a Chart.js bar chart
- SQLite database created automatically on first run

## Project Structure
```
salesapp/
├── app.py                 # Main Flask application (all routes)
├── requirements.txt
├── render.yaml             # Render.com deployment config
├── .gitignore
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── files.html
│   ├── weather.html
│   └── sales.html
├── static/
│   ├── css/style.css
│   └── js/script.js
└── uploads/                # created automatically, per-user subfolders
```

## Run Locally

1. **Install Python 3.10+** if you don't already have it.

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the app:**
   ```bash
   python app.py
   ```

5. Open your browser to **http://127.0.0.1:5000**

The SQLite database (`database.db`) and the `uploads/` folder are created
automatically the first time you run the app.

## Sample Sales CSV format
Any CSV/XLSX works as long as it has one revenue-like column. Example:

```csv
date,product,amount
2026-01-01,Widget A,120.50
2026-01-02,Widget B,89.99
2026-01-03,Widget A,45.00
```

Recognized revenue columns: `amount`, `revenue`, `sales`, `total`, `price`
Recognized grouping columns: `product`, `item`, `category`, or any `*date*` column.

## Deploy to GitHub

```bash
cd salesapp
git init
git add .
git commit -m "Initial commit: Sales Suite Flask app"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

## Deploy to Render

1. Push the project to GitHub (steps above).
2. Go to [render.com](https://render.com) → **New +** → **Web Service**.
3. Connect your GitHub repo.
4. Render will detect `render.yaml` automatically, or configure manually:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Environment:** Python 3
5. Add an environment variable `SECRET_KEY` (or let Render auto-generate one,
   as configured in `render.yaml`).
6. Click **Create Web Service** — Render will build and deploy automatically.

**Note on persistence:** Render's free tier filesystem is ephemeral, meaning
uploaded files and the SQLite database will reset on redeploys/restarts. For
production use, switch to Render's persistent disk add-on or migrate to a
managed database like PostgreSQL.

## Security Notes
- Change `SECRET_KEY` before deploying to production (never use the default).
- Passwords are hashed with Werkzeug's `generate_password_hash`.
- File uploads are restricted by extension and size (16 MB max).
