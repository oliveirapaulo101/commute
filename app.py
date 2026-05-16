import json
import os
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify
)

from models import (
    init_db, insert_transactions, update_category,
    get_monthly_spending, get_spending_trend, get_recurring_bills,
    get_all_transactions, upsert_savings_goal, get_savings_goals,
    delete_savings_goal,
)
from csv_parser import parse_csv
from categorizer import categorize_batch, CATEGORIES
from config_manager import (
    load_config, get_budget_limits, update_budget_limits,
    get_spending_alerts, CATEGORIES as BUDGET_CATEGORIES,
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))


@app.before_request
def _setup():
    init_db()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route('/')
def dashboard():
    now = datetime.now()
    year, month = now.year, now.month

    monthly_spending = get_monthly_spending(year, month)
    budget_limits    = get_budget_limits()
    alerts           = get_spending_alerts(monthly_spending, budget_limits)
    savings_goals    = get_savings_goals()
    recurring_bills  = get_recurring_bills()
    spending_trend   = get_spending_trend(6)

    # Donut chart — only expense categories
    expense_cats    = [c for c in BUDGET_CATEGORIES if c in monthly_spending]
    expense_amounts = [monthly_spending[c] for c in expense_cats]

    # Bar chart
    trend_labels  = [t[0] for t in spending_trend]
    trend_amounts = [t[1] for t in spending_trend]

    # Budget status bars
    budget_status = {}
    for cat, limit in budget_limits.items():
        spent = monthly_spending.get(cat, 0)
        pct   = min((spent / limit * 100) if limit > 0 else 0, 150)
        budget_status[cat] = {
            'spent':   round(spent, 2),
            'limit':   limit,
            'percent': round(pct, 1),
            'level':   'danger' if pct >= 100 else ('warning' if pct >= 80 else 'ok'),
        }

    return render_template(
        'dashboard.html',
        monthly_spending  = monthly_spending,
        budget_limits     = budget_limits,
        budget_status     = budget_status,
        alerts            = alerts,
        savings_goals     = savings_goals,
        recurring_bills   = recurring_bills,
        categories_json   = json.dumps(expense_cats),
        amounts_json      = json.dumps(expense_amounts),
        trend_labels_json = json.dumps(trend_labels),
        trend_amounts_json= json.dumps(trend_amounts),
        current_month     = now.strftime('%B %Y'),
        no_data           = not monthly_spending,
    )


# ---------------------------------------------------------------------------
# CSV Upload
# ---------------------------------------------------------------------------

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'file' not in request.files or not request.files['file'].filename:
            flash('Please select a CSV file.', 'error')
            return redirect(request.url)

        f = request.files['file']
        if not f.filename.lower().endswith('.csv'):
            flash('Only .csv files are accepted.', 'error')
            return redirect(request.url)

        try:
            content = f.read()
            transactions, bank = parse_csv(content)

            if not transactions:
                flash('No valid transactions found — check the CSV format.', 'warning')
                return redirect(request.url)

            # Optional AI categorization
            if request.form.get('auto_categorize') == 'on':
                if not os.getenv('ANTHROPIC_API_KEY'):
                    flash('ANTHROPIC_API_KEY not set — transactions saved as "Other".', 'warning')
                else:
                    try:
                        cats = categorize_batch(transactions)
                        for tx, cat in zip(transactions, cats):
                            tx['category'] = cat
                    except Exception as exc:
                        flash(f'AI categorization error: {exc}. Saved as "Other".', 'warning')

            inserted = insert_transactions(transactions)
            flash(
                f'Imported {inserted} new transaction(s) from {bank} '
                f'({len(transactions) - inserted} duplicate(s) skipped).',
                'success',
            )
            return redirect(url_for('dashboard'))

        except Exception as exc:
            flash(f'Error processing file: {exc}', 'error')
            return redirect(request.url)

    return render_template('upload.html')


# ---------------------------------------------------------------------------
# Transactions list
# ---------------------------------------------------------------------------

@app.route('/transactions')
def transactions():
    page     = max(request.args.get('page', 1, type=int), 1)
    per_page = 50
    txs, total = get_all_transactions(limit=per_page, offset=(page - 1) * per_page)
    total_pages = max((total + per_page - 1) // per_page, 1)
    return render_template(
        'transactions.html',
        transactions = txs,
        page         = page,
        total_pages  = total_pages,
        categories   = CATEGORIES,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.route('/settings')
def settings():
    return render_template(
        'settings.html',
        config        = load_config(),
        savings_goals = get_savings_goals(),
        categories    = BUDGET_CATEGORIES,
    )


@app.route('/settings/budget', methods=['POST'])
def update_budget():
    limits = {}
    for cat in BUDGET_CATEGORIES:
        key = f'limit_{cat.replace("/", "_")}'
        try:
            limits[cat] = max(float(request.form.get(key, 0)), 0)
        except ValueError:
            limits[cat] = 0
    update_budget_limits(limits)
    flash('Budget limits saved.', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/goals', methods=['POST'])
def add_goal():
    name    = request.form.get('name', '').strip()
    target  = request.form.get('target_amount', '0')
    current = request.form.get('current_amount', '0')

    if not name:
        flash('Goal name is required.', 'error')
        return redirect(url_for('settings'))

    try:
        upsert_savings_goal(name, float(target), float(current))
        flash(f'Goal "{name}" saved.', 'success')
    except Exception as exc:
        flash(f'Error saving goal: {exc}', 'error')

    return redirect(url_for('settings'))


@app.route('/settings/goals/<int:goal_id>/delete', methods=['POST'])
def delete_goal(goal_id):
    delete_savings_goal(goal_id)
    flash('Goal deleted.', 'success')
    return redirect(url_for('settings'))


# ---------------------------------------------------------------------------
# API — manual re-categorize
# ---------------------------------------------------------------------------

@app.route('/api/categorize/<int:tx_id>', methods=['POST'])
def manual_categorize(tx_id):
    data = request.get_json(silent=True) or {}
    cat  = data.get('category')
    if cat and cat in CATEGORIES:
        update_category(tx_id, cat)
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'invalid category'}), 400


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port)
