import sqlite3
import json
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])

DB_PATH = ".deeprabbit_reviews.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT,
                pr_number INTEGER,
                status TEXT,
                issues_count INTEGER,
                rating TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

init_db()

def log_review(repo: str, pr_number: int, status: str, issues_count: int, rating: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO reviews (repo, pr_number, status, issues_count, rating) VALUES (?, ?, ?, ?, ?)",
                (repo, pr_number, status, issues_count, rating)
            )
            conn.commit()
    except Exception:
        pass

@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM reviews ORDER BY timestamp DESC LIMIT 50")
        rows = cur.fetchall()

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DeepRabbit Dashboard</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; }
            h1 { color: #818cf8; }
            table { width: 100%; border-collapse: collapse; margin-top: 1rem; background: #1e293b; border-radius: 8px; overflow: hidden; }
            th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #334155; }
            th { background: #334155; color: #cbd5e1; }
            tr:hover { background: #475569; }
            .badge { padding: 4px 8px; border-radius: 4px; font-size: 0.85em; }
            .badge.approve { background: #10b981; color: white; }
            .badge.comment { background: #3b82f6; color: white; }
            .badge.request_changes { background: #ef4444; color: white; }
        </style>
    </head>
    <body>
        <h1>🐇 DeepRabbit Review Dashboard</h1>
        <p>Recent Pull Request Reviews</p>
        <table>
            <tr>
                <th>Time</th>
                <th>Repository</th>
                <th>PR #</th>
                <th>Status</th>
                <th>Issues</th>
                <th>Rating</th>
            </tr>
    """
    for row in rows:
        rating = row['rating'] or 'comment'
        html += f"""
            <tr>
                <td>{row['timestamp']}</td>
                <td>{row['repo']}</td>
                <td>#{row['pr_number']}</td>
                <td>{row['status']}</td>
                <td>{row['issues_count']}</td>
                <td><span class="badge {rating}">{rating.upper()}</span></td>
            </tr>
        """
    html += """
        </table>
    </body>
    </html>
    """
    return html
