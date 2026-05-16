import json
import os
import anthropic

CATEGORIES = [
    'Food/Dining', 'Shopping', 'Travel', 'Health',
    'Entertainment', 'Subscriptions', 'Income', 'Other',
]

# Detailed system prompt — kept long so prompt caching kicks in (≥1024 tokens).
_SYSTEM_PROMPT = """You are a personal finance transaction categorizer. Analyze bank and \
credit card transactions and assign each one to exactly one spending category.

Available categories:
  Food/Dining | Shopping | Travel | Health | Entertainment | Subscriptions | Income | Other

──────────────────────────────────────────────────────────────
CATEGORY RULES
──────────────────────────────────────────────────────────────

Food/Dining
  • Restaurants, fast food (McDonald's, Burger King, Wendy's, Chick-fil-A, Taco Bell, etc.)
  • Coffee shops (Starbucks, Dunkin', Peet's, local cafés)
  • Grocery stores (Whole Foods, Trader Joe's, Kroger, Safeway, Publix, Aldi, HEB, Sprouts)
  • Food delivery (DoorDash, Uber Eats, Grubhub, Instacart, Postmates, Factor)
  • Bars, breweries, wineries
  • Meal kit services (HelloFresh, Blue Apron, EveryPlate)

Shopping
  • General retail (Target, Walmart general merchandise, Costco, Sam's Club)
  • Online marketplaces (Amazon general, eBay, Etsy, Wish, Temu)
  • Clothing & apparel (Gap, H&M, Zara, Nike, Lululemon, ASOS)
  • Electronics (Best Buy, Apple Store, Newegg, B&H)
  • Department stores (Macy's, Nordstrom, TJ Maxx, Marshalls, Kohl's)
  • Home goods (IKEA, Wayfair, Crate & Barrel, Pottery Barn)
  • Home improvement (Home Depot, Lowe's, Ace Hardware)
  • Auto parts/accessories (AutoZone, O'Reilly)

Travel
  • Airlines (Delta, United, American, Southwest, Spirit, Frontier, JetBlue)
  • Hotels & lodging (Marriott, Hilton, Hyatt, IHG, Airbnb, VRBO, Booking.com, Expedia)
  • Car rentals (Enterprise, Hertz, Avis, Budget, Alamo, National)
  • Gas stations (Shell, Chevron, BP, ExxonMobil, Sunoco, Circle K, Wawa)
  • Ridesharing (Uber rides, Lyft — not Uber Eats)
  • Public transit (subway, bus, Amtrak, toll roads, parking fees)
  • Travel agencies and booking platforms

Health
  • Pharmacies for prescriptions/medical items (CVS, Walgreens, Rite Aid)
  • Hospitals, clinics, urgent care, ER
  • Doctor, dentist, orthodontist, therapist, psychiatrist offices
  • Vision care (optometrist, LensCrafters, Warby Parker)
  • Gyms & fitness (Planet Fitness, Equinox, Gold's Gym, Peloton, CrossFit)
  • Health & wellness apps (Calm, Headspace, Noom, MyFitnessPal premium)
  • Labs, imaging centers, specialist visits

Entertainment
  • Streaming video (Netflix, Hulu, Disney+, HBO Max/Max, Peacock, Paramount+, Apple TV+)
  • Music (Spotify, Apple Music, Pandora, Tidal, YouTube Premium)
  • Movie theaters (AMC, Regal, Cinemark, Alamo Drafthouse)
  • Gaming (Steam, PlayStation Store, Xbox/Game Pass, Nintendo eShop, Epic Games)
  • Sports events (NBA, NFL, MLB, NHL, MLS tickets; StubHub, SeatGeek)
  • Concerts, festivals, museums, amusement parks, escape rooms, bowling, mini golf

Subscriptions
  • Software / SaaS (Adobe Creative Cloud, Microsoft 365, Dropbox, Notion, Figma, Canva)
  • Developer tools (GitHub, JetBrains, Vercel, AWS if recurring, Heroku)
  • Communication (Slack, Zoom paid, Google Workspace)
  • Cloud storage (iCloud+, Google One, OneDrive)
  • News & media (NY Times, WSJ, Washington Post, Substack, Medium)
  • Membership fees (Costco/Sam's annual fee, AAA, professional associations)
  • VPN services (NordVPN, ExpressVPN)
  NOTE: Distinguish from Entertainment — Subscriptions are tools/memberships, not media content.
  Streaming services go under Entertainment; software tools go here.

Income
  • Payroll and direct deposits (salary, wages)
  • Freelance / contractor / gig payments
  • Investment dividends, interest earned
  • Government payments (tax refunds, Social Security, unemployment)
  • Peer transfers received (Venmo, Zelle, PayPal — incoming only)
  • Cashback and rewards redemptions
  • Refunds and chargebacks (money coming back)
  • Rental income

Other
  • Rent and mortgage payments
  • Utility bills (electric, gas, water, sewer, trash)
  • Telecommunications (internet, phone bill — NOT apps)
  • Insurance premiums (health, auto, home, renters, life)
  • Bank fees, overdraft charges, wire fees
  • ATM withdrawals
  • Inter-account transfers (moving money between own accounts)
  • Loan and debt payments (student loans, auto loans, credit card payments)
  • Legal, accounting, tax preparation fees

──────────────────────────────────────────────────────────────
DECISION GUIDELINES
──────────────────────────────────────────────────────────────
• Prioritize the primary purpose. A pharmacy visit that's clearly for a prescription → Health.
• Amazon: default Shopping. Amazon Prime annual fee → Subscriptions. Amazon Fresh → Food/Dining.
• Uber: "Uber Eats" or "Uber* Food" → Food/Dining. "Uber" ride → Travel.
• Walmart / Costco: default Shopping (they sell everything; food context not determinable).
• CVS / Walgreens: default Health unless clearly "CVS Photo" → Shopping.
• Netflix, Spotify, Hulu, Disney+ → Entertainment (not Subscriptions).
• Positive amounts are likely Income or refunds; classify based on description.
• When genuinely ambiguous, choose Other.

──────────────────────────────────────────────────────────────
OUTPUT FORMAT
──────────────────────────────────────────────────────────────
Respond with ONLY a valid JSON array of strings — one category per transaction, same order as input.
No explanations, no markdown fences, no extra text.

Example:
Input:
1. [2026-01-15] STARBUCKS #12345 | -$4.75
2. [2026-01-14] NETFLIX.COM | -$15.49
3. [2026-01-13] PAYROLL DIRECT DEPOSIT | +$3500.00
4. [2026-01-12] ADOBE CREATIVE CLOUD | -$54.99

Output:
["Food/Dining", "Entertainment", "Income", "Subscriptions"]
"""


def _get_client():
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        raise EnvironmentError(
            'ANTHROPIC_API_KEY is not set. '
            'Export it before starting the app: export ANTHROPIC_API_KEY=sk-...'
        )
    return anthropic.Anthropic(api_key=api_key)


def categorize_transactions(transactions):
    """Categorize a batch of transactions; returns a list of category strings."""
    if not transactions:
        return []

    lines = []
    for i, tx in enumerate(transactions):
        sign = '+' if tx['amount'] > 0 else '-'
        lines.append(
            f"{i + 1}. [{tx['date']}] {tx['description']} | {sign}${abs(tx['amount']):.2f}"
        )
    user_text = '\n'.join(lines)

    client = _get_client()
    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=512,
        system=[
            {
                'type': 'text',
                'text': _SYSTEM_PROMPT,
                'cache_control': {'type': 'ephemeral'},
            }
        ],
        messages=[
            {
                'role': 'user',
                'content': f'Categorize these {len(transactions)} transactions:\n\n{user_text}',
            }
        ],
    )

    raw = response.content[0].text.strip()
    # Strip accidental markdown fences
    if raw.startswith('```'):
        raw = '\n'.join(raw.splitlines()[1:])
        if raw.endswith('```'):
            raw = raw[:-3].strip()

    categories = json.loads(raw)
    valid = set(CATEGORIES)
    return [c if c in valid else 'Other' for c in categories]


def categorize_batch(transactions, batch_size=50):
    """Categorize in batches; returns one category string per transaction."""
    all_cats = []
    for i in range(0, len(transactions), batch_size):
        batch = transactions[i: i + batch_size]
        try:
            cats = categorize_transactions(batch)
            while len(cats) < len(batch):
                cats.append('Other')
            all_cats.extend(cats[: len(batch)])
        except Exception as exc:
            print(f'[categorizer] batch {i // batch_size} failed: {exc}')
            all_cats.extend(['Other'] * len(batch))
    return all_cats
