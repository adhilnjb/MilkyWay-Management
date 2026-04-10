#!/bin/bash
set -e
echo ""
echo "============================================"
echo " MilkDairy Pro v5 – Setup"
echo " Bill Fix + Full CRUD + Expense Tracker"
echo "============================================"
echo ""
command -v python3 &>/dev/null || { echo "[ERROR] Install Python3 from python.org"; exit 1; }
echo "[OK] $(python3 --version)"

python3 -m venv venv && source venv/bin/activate

echo "[1/5] Installing packages..."
pip install "django>=4.2,<5.0" reportlab pillow --quiet
echo "[OK] Django + ReportLab + Pillow installed"

echo "[2/5] Running migrations..."
python manage.py migrate
echo "[OK] Database ready"

echo "[3/5] Create your admin login:"
python manage.py createsuperuser

echo "[4/5] Loading sample data..."
python manage.py shell << 'PYEOF'
from delivery.models import MilkProduct, Customer, ExpenseCategory, Expense
import datetime
from decimal import Decimal

# Products
prods = [
    ('Full Cream Milk', 70), ('Toned Milk', 55),
    ('Double Toned', 50),    ('Buffalo Milk', 80),
    ('Skimmed Milk', 45),    ('Flavoured Milk', 65),
]
prod_objs = {}
for name, price in prods:
    p, _ = MilkProduct.objects.get_or_create(name=name, defaults={'unit':'L','default_price':Decimal(str(price))})
    prod_objs[name] = p

# Expense Categories
cats = [
    ('Feed / Fodder','🌾'),   ('Medicine / Vaccines','💊'),
    ('Electricity','⚡'),       ('Travel Expense','🚗'),
    ('Maintenance / Repair','🔧'),('Labour / Wages','👷'),
    ('Milk Purchase','🥛'),    ('Veterinary','🏥'),
    ('Packaging','📦'),          ('Water / Utility','💧'),
    ('Testing / Lab','🧪'),    ('Other','🌿'),
]
for name, icon in cats:
    ExpenseCategory.objects.get_or_create(name=name, defaults={'icon': icon})
print(f"  {len(cats)} expense categories created")

# Customers with varied schedules
custs = [
    {'name':'Rajesh Kumar',   'phone':'9876543210','area':'north','address':'Plot 12 Gandhi Nagar',  'default_product':prod_objs['Full Cream Milk'],'default_qty':Decimal('2'),  'delivery_schedule':'daily'},
    {'name':'Priya Sharma',   'phone':'9876543211','area':'south','address':'B-45 Laxmi Colony',     'default_product':prod_objs['Toned Milk'],      'default_qty':Decimal('1'),  'delivery_schedule':'alternate'},
    {'name':'Mohammed Ali',   'phone':'9876543212','area':'east', 'address':'House 7 Azad Nagar',    'default_product':prod_objs['Full Cream Milk'],'default_qty':Decimal('1.5'),'delivery_schedule':'alt_even'},
    {'name':'Sunita Devi',    'phone':'9876543213','area':'west', 'address':'C-22 Shivaji Nagar',    'default_product':prod_objs['Double Toned'],    'default_qty':Decimal('1'),  'delivery_schedule':'weekdays'},
    {'name':'Arjun Menon',    'phone':'9876543214','area':'central','address':'Flat 3B Central Park','default_product':prod_objs['Toned Milk'],      'default_qty':Decimal('2'),  'delivery_schedule':'thrice'},
    {'name':'Kavitha Nair',   'phone':'9876543215','area':'north','address':'10A Rose Garden',       'default_product':prod_objs['Buffalo Milk'],    'default_qty':Decimal('1'),  'delivery_schedule':'twice'},
    {'name':'Suresh Babu',    'phone':'9876543216','area':'south','address':'44 MG Road',            'default_product':prod_objs['Full Cream Milk'],'default_qty':Decimal('0.5'),'delivery_schedule':'weekends'},
]
for c in custs:
    Customer.objects.get_or_create(phone=c['phone'], defaults={**c,'joining_date':datetime.date.today()})
print(f"  {len(custs)} customers created with varied schedules")

# Sample expenses
today = datetime.date.today()
sample_exp = [
    ('Monthly Cattle Feed',  'Feed / Fodder',        Decimal('3500'), 'cash', 'Ram Feed Store'),
    ('Electricity Bill',     'Electricity',           Decimal('850'),  'upi',  'KSEB'),
    ('Vet Consultation',     'Veterinary',            Decimal('500'),  'cash', 'Dr. Sharma'),
    ('Delivery Fuel',        'Travel Expense',        Decimal('400'),  'upi',  'Petrol Bunk'),
    ('Milk Packaging',       'Packaging',             Decimal('300'),  'cash', 'Local Supplier'),
]
for title, cat_name, amt, mode, vendor in sample_exp:
    cat = ExpenseCategory.objects.get(name=cat_name)
    Expense.objects.get_or_create(
        title=title,
        defaults={'category':cat,'amount':amt,'date':today,'payment_mode':mode,'vendor':vendor}
    )
print(f"  {len(sample_exp)} sample expenses created")
print("  ✅ All sample data loaded!")
PYEOF

echo ""
echo "============================================"
echo " SETUP COMPLETE!"
echo " URL:   http://127.0.0.1:8000"
echo " Admin: http://127.0.0.1:8000/admin"
echo " Press Ctrl+C to stop the server"
echo "============================================"
echo ""
python manage.py runserver
