import csv
import io
from dateutil import parser as dateparser


def _normalize_amount(raw):
    s = str(raw).strip().replace('$', '').replace(',', '').replace('(', '-').replace(')', '')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_date(raw):
    try:
        return dateparser.parse(str(raw).strip()).strftime('%Y-%m-%d')
    except Exception:
        return str(raw).strip()


def _key(fields, *candidates):
    """Return first header key that contains any candidate substring."""
    for candidate in candidates:
        for f in fields:
            if candidate in f.lower():
                return f
    return None


# ---------------------------------------------------------------------------
# Bank-specific parsers
# ---------------------------------------------------------------------------

def _parse_chase(reader):
    txs = []
    for row in reader:
        fields = list(row.keys())
        date_k = _key(fields, 'transaction date', 'date')
        desc_k = _key(fields, 'description', 'memo')
        amt_k  = _key(fields, 'amount')
        if not all([date_k, desc_k, amt_k]):
            continue
        amount = _normalize_amount(row[amt_k])
        if amount == 0:
            continue
        txs.append({
            'date':        _parse_date(row[date_k]),
            'description': row[desc_k].strip(),
            'amount':      amount,
            'source_bank': 'Chase',
        })
    return txs


def _parse_bofa(reader):
    txs = []
    for row in reader:
        fields = list(row.keys())
        date_k = _key(fields, 'date')
        desc_k = _key(fields, 'description', 'payee')
        amt_k  = _key(fields, 'amount')
        if not all([date_k, desc_k, amt_k]):
            continue
        amount = _normalize_amount(row[amt_k])
        if amount == 0:
            continue
        txs.append({
            'date':        _parse_date(row[date_k]),
            'description': row[desc_k].strip(),
            'amount':      amount,
            'source_bank': 'BofA',
        })
    return txs


def _parse_discover(reader):
    """Discover exports charges as positive; we negate to make expenses negative."""
    txs = []
    for row in reader:
        fields = list(row.keys())
        # Prefer "Trans. Date" over "Post Date"
        date_k = _key(fields, 'trans. date', 'trans date', 'transaction date', 'date')
        desc_k = _key(fields, 'description')
        amt_k  = _key(fields, 'amount')
        if not all([date_k, desc_k, amt_k]):
            continue
        raw = _normalize_amount(row[amt_k])
        if raw == 0:
            continue
        # Discover convention: charges positive, credits/payments negative → invert
        amount = -raw
        txs.append({
            'date':        _parse_date(row[date_k]),
            'description': row[desc_k].strip(),
            'amount':      amount,
            'source_bank': 'Discover',
        })
    return txs


def _parse_generic(reader):
    txs = []
    for row in reader:
        fields = list(row.keys())
        date_k = _key(fields, 'date')
        desc_k = _key(fields, 'description', 'merchant', 'payee', 'name', 'memo')
        amt_k  = _key(fields, 'amount', 'debit', 'credit')
        if not all([date_k, desc_k, amt_k]):
            continue
        amount = _normalize_amount(row[amt_k])
        if amount == 0:
            continue
        txs.append({
            'date':        _parse_date(row[date_k]),
            'description': row[desc_k].strip(),
            'amount':      amount,
            'source_bank': 'Unknown',
        })
    return txs


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _detect_bank(headers):
    hl = [h.lower().strip() for h in headers]
    joined = ' '.join(hl)
    if 'trans. date' in joined or 'trans date' in joined:
        return 'discover'
    if 'reference number' in joined or 'account number' in joined:
        return 'bofa'
    if 'transaction date' in joined or ('type' in joined and 'balance' in joined):
        return 'chase'
    return 'generic'


_PARSERS = {
    'chase':   _parse_chase,
    'bofa':    _parse_bofa,
    'discover': _parse_discover,
    'generic': _parse_generic,
}

_BANK_LABELS = {
    'chase': 'Chase', 'bofa': 'Bank of America',
    'discover': 'Discover', 'generic': 'Unknown',
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_csv(file_content):
    """
    Parse a bank CSV export (bytes or str).

    Returns (transactions, bank_label) where transactions is a list of dicts
    with keys: date, description, amount, source_bank.
    """
    if isinstance(file_content, bytes):
        try:
            content = file_content.decode('utf-8')
        except UnicodeDecodeError:
            content = file_content.decode('latin-1')
    else:
        content = file_content

    content = content.lstrip('﻿')  # strip BOM

    # Skip preamble rows that don't look like CSV headers
    lines = content.strip().splitlines()
    csv_start = 0
    for i, line in enumerate(lines):
        if ',' in line and any(
            w in line.lower() for w in ['date', 'description', 'amount']
        ):
            csv_start = i
            break

    content = '\n'.join(lines[csv_start:])
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []

    bank_key = _detect_bank(headers)
    transactions = _PARSERS[bank_key](reader)
    valid = [t for t in transactions if t['description'] and t['amount'] != 0]
    return valid, _BANK_LABELS[bank_key]
