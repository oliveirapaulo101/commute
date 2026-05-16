import sqlite3
import os
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'finance.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT DEFAULT 'Other',
            source_bank TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_unique
            ON transactions(date, description, amount, source_bank);

        CREATE TABLE IF NOT EXISTS savings_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            target_amount REAL NOT NULL,
            current_amount REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    conn.close()


def insert_transactions(transactions):
    conn = get_db()
    inserted = 0
    for tx in transactions:
        try:
            conn.execute(
                '''INSERT OR IGNORE INTO transactions
                   (date, description, amount, category, source_bank)
                   VALUES (?, ?, ?, ?, ?)''',
                (tx['date'], tx['description'], tx['amount'],
                 tx.get('category', 'Other'), tx.get('source_bank', ''))
            )
            if conn.execute('SELECT changes()').fetchone()[0]:
                inserted += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return inserted


def get_uncategorized():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, date, description, amount FROM transactions WHERE category = 'Other'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_category(tx_id, category):
    conn = get_db()
    conn.execute('UPDATE transactions SET category = ? WHERE id = ?', (category, tx_id))
    conn.commit()
    conn.close()


def get_monthly_spending(year, month):
    conn = get_db()
    rows = conn.execute('''
        SELECT category, SUM(amount) as total
        FROM transactions
        WHERE strftime('%Y', date) = ?
          AND strftime('%m', date) = ?
          AND amount < 0
        GROUP BY category
        ORDER BY total ASC
    ''', (str(year), f'{month:02d}')).fetchall()
    conn.close()
    return {r['category']: round(abs(r['total']), 2) for r in rows}


def get_spending_trend(months=6):
    """Last N calendar months of total spending, oldest first, zero-filled."""
    today = date.today()
    result = []
    for i in range(months - 1, -1, -1):
        d = today - relativedelta(months=i)
        label = d.strftime('%Y-%m')
        conn = get_db()
        row = conn.execute('''
            SELECT COALESCE(SUM(amount), 0) as total
            FROM transactions
            WHERE strftime('%Y-%m', date) = ?
              AND amount < 0
        ''', (label,)).fetchone()
        conn.close()
        result.append((label, round(abs(row['total']), 2)))
    return result


def get_recurring_bills():
    """Transactions appearing 2+ times in the last 90 days."""
    conn = get_db()
    rows = conn.execute('''
        SELECT
            description,
            ROUND(AVG(amount), 2)  AS avg_amount,
            COUNT(*)               AS occurrences,
            MAX(date)              AS last_date
        FROM transactions
        WHERE date >= date('now', '-90 days')
          AND amount < 0
        GROUP BY description
        HAVING occurrences >= 2
        ORDER BY avg_amount ASC
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_transactions(limit=50, offset=0):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM transactions ORDER BY date DESC, id DESC LIMIT ? OFFSET ?',
        (limit, offset)
    ).fetchall()
    total = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    conn.close()
    return [dict(r) for r in rows], total


def upsert_savings_goal(name, target_amount, current_amount):
    conn = get_db()
    conn.execute('''
        INSERT INTO savings_goals (name, target_amount, current_amount)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            target_amount  = excluded.target_amount,
            current_amount = excluded.current_amount
    ''', (name, target_amount, current_amount))
    conn.commit()
    conn.close()


def get_savings_goals():
    conn = get_db()
    rows = conn.execute('SELECT * FROM savings_goals ORDER BY name').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_savings_goal(goal_id):
    conn = get_db()
    conn.execute('DELETE FROM savings_goals WHERE id = ?', (goal_id,))
    conn.commit()
    conn.close()
