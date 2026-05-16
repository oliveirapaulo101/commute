import os
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'budget_config.yaml')

CATEGORIES = [
    'Food/Dining', 'Shopping', 'Travel', 'Health',
    'Entertainment', 'Subscriptions', 'Other',
]

DEFAULT_LIMITS = {
    'Food/Dining': 500,
    'Shopping': 300,
    'Travel': 200,
    'Health': 150,
    'Entertainment': 100,
    'Subscriptions': 80,
    'Other': 200,
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        _save({'budget_limits': DEFAULT_LIMITS})
        return {'budget_limits': DEFAULT_LIMITS}
    with open(CONFIG_PATH, 'r') as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault('budget_limits', DEFAULT_LIMITS)
    return cfg


def _save(cfg):
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


def get_budget_limits():
    return load_config().get('budget_limits', DEFAULT_LIMITS)


def update_budget_limits(limits):
    cfg = load_config()
    cfg['budget_limits'] = limits
    _save(cfg)


def get_spending_alerts(monthly_spending, budget_limits):
    """Return sorted list of alert dicts for categories at ≥80 % of budget."""
    alerts = []
    for cat, limit in budget_limits.items():
        if limit <= 0:
            continue
        spent = monthly_spending.get(cat, 0)
        pct = (spent / limit) * 100
        if pct >= 80:
            alerts.append({
                'category': cat,
                'spent':    spent,
                'limit':    limit,
                'percent':  pct,
                'level':    'danger' if pct >= 100 else 'warning',
            })
    return sorted(alerts, key=lambda x: x['percent'], reverse=True)
