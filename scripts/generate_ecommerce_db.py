"""Build data/ecommerce.db: an ecommerce star schema in SQLite.

    fact_sales (one row per order line)
      ├── dim_date       date_key
      ├── dim_customer   customer_key
      ├── dim_product    product_key
      ├── dim_geography  geo_key
      ├── dim_channel    channel_key
      └── dim_promotion  promo_key

Same seed, same data. Run:  python scripts/generate_ecommerce_db.py
"""

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_PATH  # noqa: E402

random.seed(42)

START, END = date(2025, 10, 1), date(2026, 9, 30)
NUM_CUSTOMERS = 1200
NUM_ORDERS = 5200

PRODUCTS = {
    # category: (sub_category, brands, price range, cost ratio, return rate)
    "Electronics": [("Mobiles", ["Nova", "Pixelon", "Zentro"], (9000, 45000), 0.84, 0.06),
                    ("Audio", ["SoundMax", "Beatz", "Nova"], (900, 12000), 0.62, 0.08),
                    ("Accessories", ["Zentro", "Plugit"], (199, 2500), 0.48, 0.05)],
    "Fashion": [("Men", ["UrbanLane", "Kraft"], (499, 3999), 0.42, 0.22),
                ("Women", ["Aurelia", "UrbanLane"], (599, 4999), 0.40, 0.26),
                ("Footwear", ["StrideOn", "Kraft"], (799, 5999), 0.45, 0.18)],
    "Home & Kitchen": [("Cookware", ["ChefPro", "HomeNest"], (499, 6999), 0.58, 0.07),
                       ("Decor", ["HomeNest", "Artisa"], (299, 3999), 0.46, 0.09),
                       ("Appliances", ["ChefPro", "Voltix"], (1999, 18999), 0.72, 0.06)],
    "Beauty": [("Skincare", ["Glowé", "PureLeaf"], (199, 1999), 0.44, 0.04),
               ("Haircare", ["PureLeaf", "Silkara"], (149, 1299), 0.46, 0.03)],
    "Sports": [("Fitness", ["FitCore", "Ironclad"], (399, 9999), 0.55, 0.06),
               ("Outdoor", ["TrailX", "FitCore"], (599, 7999), 0.56, 0.07)],
    "Books": [("Fiction", ["PageTurn", "InkWell"], (199, 799), 0.66, 0.02),
              ("Non-Fiction", ["InkWell", "PageTurn"], (249, 1299), 0.65, 0.02)],
}
NOUNS = {
    "Mobiles": ["Smartphone 5G", "Smartphone Lite", "Smartphone Pro"],
    "Audio": ["Wireless Earbuds", "Bluetooth Speaker", "Over-Ear Headphones"],
    "Accessories": ["Fast Charger", "Power Bank", "Phone Case"],
    "Men": ["Cotton Shirt", "Slim Jeans", "Polo T-Shirt"],
    "Women": ["Kurta Set", "Summer Dress", "Denim Jacket"],
    "Footwear": ["Running Shoes", "Leather Sneakers", "Sandals"],
    "Cookware": ["Non-Stick Pan", "Pressure Cooker", "Knife Set"],
    "Decor": ["Table Lamp", "Wall Art", "Cushion Covers"],
    "Appliances": ["Air Fryer", "Mixer Grinder", "Robot Vacuum"],
    "Skincare": ["Vitamin C Serum", "Sunscreen SPF50", "Night Cream"],
    "Haircare": ["Argan Shampoo", "Hair Oil", "Conditioner"],
    "Fitness": ["Yoga Mat", "Dumbbell Set", "Resistance Bands"],
    "Outdoor": ["Trekking Backpack", "Camping Tent", "Cycling Helmet"],
    "Fiction": ["Mystery Novel", "Fantasy Saga", "Romance Paperback"],
    "Non-Fiction": ["Finance Guide", "Self-Help Book", "History Atlas"],
}
CITIES = [
    ("Delhi", "Delhi", "North", "Tier 1"), ("Gurugram", "Haryana", "North", "Tier 1"),
    ("Jaipur", "Rajasthan", "North", "Tier 2"), ("Lucknow", "Uttar Pradesh", "North", "Tier 2"),
    ("Chandigarh", "Chandigarh", "North", "Tier 2"), ("Mumbai", "Maharashtra", "West", "Tier 1"),
    ("Pune", "Maharashtra", "West", "Tier 1"), ("Ahmedabad", "Gujarat", "West", "Tier 2"),
    ("Surat", "Gujarat", "West", "Tier 2"), ("Indore", "Madhya Pradesh", "West", "Tier 3"),
    ("Bengaluru", "Karnataka", "South", "Tier 1"), ("Chennai", "Tamil Nadu", "South", "Tier 1"),
    ("Hyderabad", "Telangana", "South", "Tier 1"), ("Kochi", "Kerala", "South", "Tier 2"),
    ("Coimbatore", "Tamil Nadu", "South", "Tier 3"), ("Kolkata", "West Bengal", "East", "Tier 1"),
    ("Bhubaneswar", "Odisha", "East", "Tier 2"), ("Patna", "Bihar", "East", "Tier 3"),
    ("Guwahati", "Assam", "East", "Tier 3"), ("Ranchi", "Jharkhand", "East", "Tier 3"),
]
CHANNELS = {"Website": "Desktop", "Mobile App": "Mobile", "Marketplace": "Mixed"}
SOURCES = ["Organic Search", "Paid Search", "Social Media", "Email", "Direct", "Affiliate"]
PROMOS = [
    ("PR00", "No Promotion", "None", 0, None, None),
    ("PR01", "Festive Mega Sale", "Seasonal", 20, date(2025, 10, 10), date(2025, 10, 25)),
    ("PR02", "Diwali Dhamaka", "Seasonal", 25, date(2025, 10, 28), date(2025, 11, 10)),
    ("PR03", "Year End Clearance", "Clearance", 35, date(2025, 12, 20), date(2026, 1, 5)),
    ("PR04", "New User Offer", "First Order", 15, None, None),
    ("PR05", "Weekend Flash Sale", "Flash Sale", 30, None, None),
    ("PR06", "Bank Card Offer", "Bank Offer", 10, None, None),
    ("PR07", "App Exclusive Coupon", "Coupon", 12, None, None),
    ("PR08", "Summer Sale", "Seasonal", 20, date(2026, 5, 15), date(2026, 6, 5)),
    ("PR09", "Independence Day Sale", "Seasonal", 18, date(2026, 8, 8), date(2026, 8, 17)),
]
SEGMENT_WEIGHT = {"VIP": 9.0, "Loyal": 4.0, "Regular": 1.6, "Occasional": 0.6}
PAYMENTS = (["UPI", "Credit Card", "Debit Card", "Cash on Delivery", "Wallet", "Net Banking"],
            [42, 18, 12, 17, 7, 4])

DDL = """
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_geography;
DROP TABLE IF EXISTS dim_channel;
DROP TABLE IF EXISTS dim_promotion;

CREATE TABLE dim_date (
    date_key TEXT PRIMARY KEY, full_date TEXT, year TEXT, quarter TEXT, year_month TEXT,
    month_name TEXT, week_of_year TEXT, day_name TEXT, is_weekend TEXT, is_festive_season TEXT);
CREATE TABLE dim_customer (
    customer_key TEXT PRIMARY KEY, customer_name TEXT, gender TEXT, age_group TEXT,
    customer_segment TEXT, acquisition_source TEXT, signup_date TEXT, signup_year_month TEXT,
    membership TEXT);
CREATE TABLE dim_product (
    product_key TEXT PRIMARY KEY, sku TEXT, product_name TEXT, category TEXT, sub_category TEXT,
    brand TEXT, price_band TEXT);
CREATE TABLE dim_geography (
    geo_key TEXT PRIMARY KEY, city TEXT, state TEXT, region TEXT, city_tier TEXT, country TEXT);
CREATE TABLE dim_channel (
    channel_key TEXT PRIMARY KEY, sales_channel TEXT, device_type TEXT, traffic_source TEXT);
CREATE TABLE dim_promotion (
    promo_key TEXT PRIMARY KEY, promo_name TEXT, promo_type TEXT, discount_pct REAL);
CREATE TABLE fact_sales (
    order_line_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    date_key TEXT NOT NULL REFERENCES dim_date(date_key),
    customer_key TEXT NOT NULL REFERENCES dim_customer(customer_key),
    product_key TEXT NOT NULL REFERENCES dim_product(product_key),
    geo_key TEXT NOT NULL REFERENCES dim_geography(geo_key),
    channel_key TEXT NOT NULL REFERENCES dim_channel(channel_key),
    promo_key TEXT NOT NULL REFERENCES dim_promotion(promo_key),
    order_status TEXT, payment_method TEXT,
    quantity INTEGER, unit_price REAL, gross_sales REAL, discount_amount REAL, net_revenue REAL,
    cogs REAL, gross_profit REAL, shipping_cost REAL, is_returned INTEGER, returned_amount REAL,
    is_cancelled INTEGER, delivery_days INTEGER, is_first_order INTEGER);
"""


def build_dates():
    rows, day = [], START
    while day <= END:
        festive = date(2025, 10, 1) <= day <= date(2025, 11, 15)
        rows.append((day.isoformat(), day.isoformat(), str(day.year), f"Q{(day.month - 1) // 3 + 1} {day.year}",
                     day.strftime("%Y-%m"), day.strftime("%B"), f"W{day.isocalendar()[1]:02d}",
                     day.strftime("%A"), "Yes" if day.weekday() >= 5 else "No", "Yes" if festive else "No"))
        day += timedelta(days=1)
    return rows


def build_products():
    rows, prices, key = [], {}, 1
    for category, subs in PRODUCTS.items():
        for sub, brands, (low, high), cost_ratio, return_rate in subs:
            for noun in NOUNS[sub]:
                for brand in random.sample(brands, k=min(2, len(brands))):
                    price = round(random.uniform(low, high) / 10) * 10 - 1
                    band = "Budget" if price < 1000 else "Mid-Range" if price < 5000 else "Premium"
                    pk = f"P{key:04d}"
                    rows.append((pk, f"SKU-{key:05d}", f"{brand} {noun}", category, sub, brand, band))
                    popularity = random.uniform(0.5, 3.0) * (2.5 if price < 1500 else 1.0)
                    prices[pk] = (price, cost_ratio, return_rate, popularity, category)
                    key += 1
    return rows, prices


def build_customers():
    rows, weights = [], {}
    first = ["Aarav", "Diya", "Kabir", "Ananya", "Vihaan", "Isha", "Arjun", "Meera", "Rohan", "Sara",
             "Aditya", "Nisha", "Karan", "Priya", "Dev", "Riya", "Neel", "Tara", "Yash", "Zoya"]
    last = ["Sharma", "Iyer", "Patel", "Reddy", "Das", "Khan", "Menon", "Singh", "Gupta", "Nair"]
    for i in range(1, NUM_CUSTOMERS + 1):
        segment = random.choices(list(SEGMENT_WEIGHT), [6, 18, 44, 32])[0]
        signup = START - timedelta(days=random.randint(-300, 900))
        signup = min(signup, END - timedelta(days=5))
        key = f"C{i:05d}"
        rows.append((key, f"{random.choice(first)} {random.choice(last)}",
                     random.choices(["Female", "Male", "Other"], [48, 49, 3])[0],
                     random.choices(["18-24", "25-34", "35-44", "45-54", "55+"], [22, 38, 22, 12, 6])[0],
                     segment, random.choice(SOURCES), signup.isoformat(), signup.strftime("%Y-%m"),
                     "Plus Member" if segment in ("VIP", "Loyal") and random.random() < 0.7 else "Standard"))
        weights[key] = (SEGMENT_WEIGHT[segment], signup, random.randrange(len(CITIES)))
    return rows, weights


def order_date():
    while True:
        day = START + timedelta(days=random.randint(0, (END - START).days))
        weight = 1.0
        if date(2025, 10, 8) <= day <= date(2025, 11, 12):
            weight = 2.6
        elif day.month in (12, 1):
            weight = 1.3
        elif day.month in (2, 3):
            weight = 0.8
        if day.weekday() >= 5:
            weight *= 1.25
        if random.random() < weight / 3.3:
            return day


def pick_promo(day, first_order, channel):
    active = [p for p in PROMOS if p[4] and p[4] <= day <= p[5]]
    if active and random.random() < 0.65:
        return active[0]
    if first_order and random.random() < 0.6:
        return PROMOS[4]
    roll = random.random()
    if day.weekday() >= 5 and roll < 0.15:
        return PROMOS[5]
    if roll < 0.25:
        return PROMOS[6]
    if channel == "Mobile App" and roll < 0.35:
        return PROMOS[7]
    return PROMOS[0]


def build_facts(prices, customers):
    channels = [(f"CH{i:02d}", ch, dev, src) for i, ((ch, dev), src) in enumerate(
        ((c, s) for c in CHANNELS.items() for s in SOURCES), start=1)]
    keys = list(customers)
    cust_weights = [customers[k][0] for k in keys]
    product_keys = list(prices)
    product_weights = [prices[k][3] for k in product_keys]

    orders = sorted((order_date(), random.choices(keys, cust_weights)[0]) for _ in range(NUM_ORDERS))
    seen, facts, line_no = set(), [], 1
    for number, (day, customer) in enumerate(orders, start=1):
        _, signup, home_city = customers[customer]
        if day < signup:
            day = signup
        # Customers who signed up well before the window usually ordered before it too.
        existing = signup < START - timedelta(days=60) and random.random() < 0.85
        first_order = customer not in seen and not existing
        seen.add(customer)
        channel = random.choices(channels, [3] * 6 + [5] * 6 + [2] * 6)[0]
        promo = pick_promo(day, first_order, channel[1])
        geo = home_city if random.random() < 0.9 else random.randrange(len(CITIES))
        tier = CITIES[geo][3]
        payment = random.choices(*PAYMENTS)[0]
        cancelled = random.random() < (0.07 if payment == "Cash on Delivery" else 0.03)
        in_transit = (END - day).days < 4 and not cancelled
        delivery = None if cancelled else max(1, int(random.gauss({"Tier 1": 2.2, "Tier 2": 3.6, "Tier 3": 5.1}[tier], 1.1)))
        lines = random.choices([1, 2, 3, 4], [55, 27, 12, 6])[0]
        order_shipping = 0 if random.random() < 0.55 else random.choice([40, 60, 80, 99])
        for product in random.sample(random.choices(product_keys, product_weights, k=lines * 2), k=lines):
            price, cost_ratio, return_rate, _, category = prices[product]
            qty = random.choices([1, 2, 3], [78, 17, 5])[0] if price > 1500 else random.choices([1, 2, 3, 4], [55, 28, 12, 5])[0]
            gross = qty * price
            discount = round(gross * promo[3] / 100, 2)
            net = round(gross - discount, 2)
            cogs = round(qty * price * cost_ratio * random.uniform(0.95, 1.05), 2)
            shipping = round(order_shipping / lines + (35 if price > 5000 else 18) * random.uniform(0.8, 1.2), 2)
            returned = (not cancelled and not in_transit
                        and random.random() < return_rate * (1.4 if payment == "Cash on Delivery" else 1.0))
            status = "Cancelled" if cancelled else "In Transit" if in_transit else "Returned" if returned else "Delivered"
            if cancelled:
                net = discount = cogs = shipping = 0.0
            facts.append((f"L{line_no:06d}", f"ORD{number:06d}", day.isoformat(), customer, product,
                          f"G{geo + 1:03d}", channel[0], promo[0], status, payment, qty, price,
                          float(gross), discount, net, cogs, round(net - cogs, 2), shipping,
                          int(returned), net if returned else 0.0, int(cancelled), delivery, int(first_order)))
            line_no += 1
    return channels, facts


def main():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    products, prices = build_products()
    customers, customer_info = build_customers()
    channels, facts = build_facts(prices, customer_info)
    geos = [(f"G{i + 1:03d}", *city, "India") for i, city in enumerate(CITIES)]
    promos = [p[:4] for p in PROMOS]

    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.executescript(DDL)
        conn.executemany("INSERT INTO dim_date VALUES (?,?,?,?,?,?,?,?,?,?)", build_dates())
        conn.executemany("INSERT INTO dim_customer VALUES (?,?,?,?,?,?,?,?,?)", customers)
        conn.executemany("INSERT INTO dim_product VALUES (?,?,?,?,?,?,?)", products)
        conn.executemany("INSERT INTO dim_geography VALUES (?,?,?,?,?,?)", geos)
        conn.executemany("INSERT INTO dim_channel VALUES (?,?,?,?)", channels)
        conn.executemany("INSERT INTO dim_promotion VALUES (?,?,?,?)", promos)
        conn.executemany(f"INSERT INTO fact_sales VALUES ({','.join('?' * 23)})", facts)
    print(f"Wrote {DATABASE_PATH}: {len(facts)} order lines, {NUM_ORDERS} orders, "
          f"{len(customers)} customers, {len(products)} products")


if __name__ == "__main__":
    main()
