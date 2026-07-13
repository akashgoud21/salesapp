import os
import sqlite3
import json
from datetime import datetime
from functools import wraps

import requests
import pandas as pd
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_from_directory, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --------------------------------------------------------------------------
# App configuration
# --------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"txt", "pdf", "png", "jpg", "jpeg", "gif", "csv", "xlsx", "docx", "zip"}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-this-in-production")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                filesize INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );

            CREATE TABLE IF NOT EXISTS sales_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                total_revenue REAL,
                total_orders INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );
            """
        )
        db.commit()


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get("user_id") is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.context_processor
def inject_user():
    return {"current_username": session.get("username")}


# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("register"))

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?", (username, email)
        ).fetchone()
        if existing:
            flash("Username or email already registered.", "danger")
            return redirect(url_for("register"))

        db.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (username, email, generate_password_hash(password), datetime.utcnow().isoformat()),
        )
        db.commit()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        flash(f"Welcome back, {user['username']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user_id = session["user_id"]

    file_count = db.execute(
        "SELECT COUNT(*) AS c FROM files WHERE user_id = ?", (user_id,)
    ).fetchone()["c"]

    sales_uploads = db.execute(
        "SELECT * FROM sales_uploads WHERE user_id = ? ORDER BY uploaded_at DESC LIMIT 5",
        (user_id,),
    ).fetchall()

    total_revenue = db.execute(
        "SELECT SUM(total_revenue) AS s FROM sales_uploads WHERE user_id = ?", (user_id,)
    ).fetchone()["s"] or 0

    recent_files = db.execute(
        "SELECT * FROM files WHERE user_id = ? ORDER BY uploaded_at DESC LIMIT 5",
        (user_id,),
    ).fetchall()

    return render_template(
        "dashboard.html",
        file_count=file_count,
        sales_uploads=sales_uploads,
        total_revenue=total_revenue,
        recent_files=recent_files,
    )


# --------------------------------------------------------------------------
# File management
# --------------------------------------------------------------------------
@app.route("/files", methods=["GET", "POST"])
@login_required
def files():
    db = get_db()
    user_id = session["user_id"]
    user_folder = os.path.join(app.config["UPLOAD_FOLDER"], str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    if request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded or uploaded.filename == "":
            flash("No file selected.", "danger")
            return redirect(url_for("files"))

        if not allowed_file(uploaded.filename):
            flash("File type not allowed.", "danger")
            return redirect(url_for("files"))

        original_name = secure_filename(uploaded.filename)
        stored_name = f"{datetime.utcnow().timestamp()}_{original_name}"
        filepath = os.path.join(user_folder, stored_name)
        uploaded.save(filepath)
        filesize = os.path.getsize(filepath)

        db.execute(
            """INSERT INTO files (user_id, filename, stored_name, filesize, uploaded_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, original_name, stored_name, filesize, datetime.utcnow().isoformat()),
        )
        db.commit()
        flash("File uploaded successfully.", "success")
        return redirect(url_for("files"))

    all_files = db.execute(
        "SELECT * FROM files WHERE user_id = ? ORDER BY uploaded_at DESC", (user_id,)
    ).fetchall()
    return render_template("files.html", files=all_files)


@app.route("/files/download/<int:file_id>")
@login_required
def download_file(file_id):
    db = get_db()
    user_id = session["user_id"]
    record = db.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id)
    ).fetchone()
    if record is None:
        flash("File not found.", "danger")
        return redirect(url_for("files"))

    user_folder = os.path.join(app.config["UPLOAD_FOLDER"], str(user_id))
    return send_from_directory(
        user_folder, record["stored_name"], as_attachment=True, download_name=record["filename"]
    )


@app.route("/files/delete/<int:file_id>", methods=["POST"])
@login_required
def delete_file(file_id):
    db = get_db()
    user_id = session["user_id"]
    record = db.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id)
    ).fetchone()

    if record:
        user_folder = os.path.join(app.config["UPLOAD_FOLDER"], str(user_id))
        filepath = os.path.join(user_folder, record["stored_name"])
        if os.path.exists(filepath):
            os.remove(filepath)
        db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        db.commit()
        flash("File deleted.", "info")
    else:
        flash("File not found.", "danger")

    return redirect(url_for("files"))


# --------------------------------------------------------------------------
# Weather (Open-Meteo — free, no API key required)
# --------------------------------------------------------------------------
@app.route("/weather", methods=["GET", "POST"])
@login_required
def weather():
    weather_data = None
    city = ""

    if request.method == "POST":
        city = request.form.get("city", "").strip()
        if city:
            try:
                geo_resp = requests.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": city, "count": 1},
                    timeout=8,
                )
                geo_resp.raise_for_status()
                geo_data = geo_resp.json()

                if geo_data.get("results"):
                    place = geo_data["results"][0]
                    lat, lon = place["latitude"], place["longitude"]

                    wx_resp = requests.get(
                        "https://api.open-meteo.com/v1/forecast",
                        params={
                            "latitude": lat,
                            "longitude": lon,
                            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                            "timezone": "auto",
                        },
                        timeout=8,
                    )
                    wx_resp.raise_for_status()
                    wx_data = wx_resp.json()

                    weather_data = {
                        "city": place.get("name"),
                        "country": place.get("country", ""),
                        "current": wx_data.get("current", {}),
                        "daily": wx_data.get("daily", {}),
                    }
                else:
                    flash(f"No results found for '{city}'.", "warning")
            except requests.RequestException as exc:
                flash(f"Weather service error: {exc}", "danger")

    return render_template("weather.html", weather_data=weather_data, city=city)


# --------------------------------------------------------------------------
# Sales analysis
# --------------------------------------------------------------------------
@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    db = get_db()
    user_id = session["user_id"]
    chart_data = None
    summary = None

    if request.method == "POST":
        uploaded = request.files.get("sales_file")
        if not uploaded or uploaded.filename == "":
            flash("No file selected.", "danger")
            return redirect(url_for("sales"))

        if not uploaded.filename.lower().endswith((".csv", ".xlsx")):
            flash("Please upload a CSV or Excel file.", "danger")
            return redirect(url_for("sales"))

        try:
            if uploaded.filename.lower().endswith(".csv"):
                df = pd.read_csv(uploaded)
            else:
                df = pd.read_excel(uploaded)
        except Exception as exc:
            flash(f"Could not read file: {exc}", "danger")
            return redirect(url_for("sales"))

        df.columns = [c.strip().lower() for c in df.columns]

        # Try to find common column names
        date_col = next((c for c in df.columns if "date" in c), None)
        amount_col = next(
            (c for c in df.columns if c in ("amount", "revenue", "sales", "total", "price")), None
        )
        product_col = next(
            (c for c in df.columns if c in ("product", "item", "category")), None
        )

        if amount_col is None:
            flash(
                "Could not find a revenue/amount column. Expected one of: amount, revenue, sales, total, price.",
                "danger",
            )
            return redirect(url_for("sales"))

        df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0)
        total_revenue = float(df[amount_col].sum())
        total_orders = int(len(df))

        # Build chart: revenue by product if available, else by date, else raw index
        if product_col:
            grouped = df.groupby(product_col)[amount_col].sum().sort_values(ascending=False).head(10)
            labels = grouped.index.astype(str).tolist()
            values = grouped.values.tolist()
            chart_label = "Revenue by Product"
        elif date_col:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            grouped = df.dropna(subset=[date_col]).groupby(df[date_col].dt.date)[amount_col].sum()
            labels = [str(d) for d in grouped.index.tolist()]
            values = grouped.values.tolist()
            chart_label = "Revenue by Date"
        else:
            labels = [f"Row {i+1}" for i in range(min(len(df), 20))]
            values = df[amount_col].head(20).tolist()
            chart_label = "Revenue by Row"

        chart_data = {"labels": labels, "values": values, "label": chart_label}
        summary = {
            "total_revenue": round(total_revenue, 2),
            "total_orders": total_orders,
            "average_order": round(total_revenue / total_orders, 2) if total_orders else 0,
        }

        db.execute(
            """INSERT INTO sales_uploads (user_id, filename, uploaded_at, total_revenue, total_orders)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, secure_filename(uploaded.filename), datetime.utcnow().isoformat(),
             total_revenue, total_orders),
        )
        db.commit()
        flash("Sales file analyzed successfully.", "success")

    history = db.execute(
        "SELECT * FROM sales_uploads WHERE user_id = ? ORDER BY uploaded_at DESC LIMIT 10",
        (user_id,),
    ).fetchall()

    return render_template(
        "sales.html",
        chart_data=json.dumps(chart_data) if chart_data else None,
        summary=summary,
        history=history,
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        init_db()
    else:
        init_db()  # safe: uses CREATE TABLE IF NOT EXISTS
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
else:
    # When run under gunicorn (Render), still ensure DB exists
    init_db()
