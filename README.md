# 🥛 MilkDairy Pro — Complete Milk Delivery Management System

A full-featured Django web application to manage your milk delivery business — customers, daily deliveries, billing, payments, and PDF invoices.

---

## ✨ Features

| Feature | Details |
|---|---|
| 📊 **Sales Dashboard** | Live stats, 7-day charts, area distribution, missed deliveries alert |
| 👥 **Customer Management** | Full profile: name, phone, address, area, delivery time, default qty, custom pricing |
| 🥛 **Product & Pricing** | Multiple milk products with default prices, per-customer price override |
| 🚚 **Daily Delivery** | Bulk update all customers at once, mark delivered/not-delivered, quick-mark button |
| 🧾 **Monthly Billing** | Auto-generate bills from delivery data, discount support, previous balance carry-forward |
| 📄 **PDF Invoice** | Professional ReportLab PDF with itemized delivery list, summary, company branding |
| 💳 **Payment Tracking** | Cash/UPI/Bank/Cheque, link payment to specific bill, auto-update bill status |
| 📈 **Reports** | Monthly summary by customer, daily totals, revenue charts |
| 🔒 **Secure Login** | Django auth with session management |
| ⚙️ **Admin Panel** | Full Django admin for all data management |

---

## 🚀 Quick Setup

### Windows
```
Double-click: setup_windows.bat
```

### Linux / Mac
```bash
chmod +x setup_linux_mac.sh
./setup_linux_mac.sh
```

### Manual Setup
```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate.bat       # Windows

# 2. Install packages
pip install -r requirements.txt

# 3. Database setup
python manage.py makemigrations delivery
python manage.py migrate

# 4. Create admin account
python manage.py createsuperuser

# 5. Run server
python manage.py runserver
```

Open browser → **http://127.0.0.1:8000**

---

## 📁 Project Structure

```
milkdairy/
├── manage.py
├── requirements.txt
├── setup_windows.bat
├── setup_linux_mac.sh
├── milkdairy/
│   ├── settings.py       ← Configuration
│   └── urls.py           ← Main URL routing
└── delivery/
    ├── models.py         ← Database models
    ├── views.py          ← All page logic
    ├── urls.py           ← App URLs
    ├── admin.py          ← Admin panel config
    └── templates/
        └── delivery/
            ├── base.html          ← Sidebar layout
            ├── login.html         ← Login page
            ├── dashboard.html     ← Main dashboard
            ├── customer_list.html
            ├── customer_form.html ← Add/Edit customer
            ├── customer_detail.html
            ├── delivery_today.html ← Daily update
            ├── delivery_list.html
            ├── bill_generate.html
            ├── bill_list.html
            ├── bill_detail.html   ← View + mark paid
            ├── payment_form.html
            ├── product_list.html
            ├── product_form.html
            └── reports.html
```

---

## 📱 Key Pages

| URL | Page |
|---|---|
| `/` | Dashboard |
| `/customers/` | Customer list with search/filter |
| `/customers/add/` | Add new customer |
| `/delivery/` | Today's delivery update |
| `/bills/` | All bills |
| `/bills/generate/` | Generate monthly bills |
| `/bills/<id>/pdf/` | Download PDF invoice |
| `/reports/` | Monthly sales report |
| `/products/` | Manage milk products & prices |
| `/admin/` | Django admin panel |

---

## 🧾 PDF Invoice

Bills can be downloaded as professional PDF invoices including:
- Company header with branding
- Customer details
- Itemized daily delivery table
- Sub total, discount, previous balance
- Grand total with highlighted styling
- Auto-generated bill number

---

## 💡 Usage Workflow

1. **Add Products** → Set Full Cream Milk ₹70/L, Toned Milk ₹55/L, etc.
2. **Add Customers** → Fill name, phone, address, select product & default qty
3. **Daily Update** → Go to "Today's Delivery", adjust qty, mark delivered ✓
4. **Month End** → Go to "Generate Bills", select customers & month → PDF ready
5. **Collect Payment** → Record payment against bill → status auto-updates

---

## 🔧 Configuration

Edit `milkdairy/settings.py`:
```python
TIME_ZONE = 'Asia/Kolkata'     # Change for your timezone
DEBUG = False                   # Set False for production
ALLOWED_HOSTS = ['yourdomain.com']
```

---

## 📦 Dependencies

- **Django 4.2** — Web framework
- **ReportLab 4.0** — PDF generation
- **Pillow** — Image handling
- **SQLite** — Default database (upgrade to PostgreSQL for production)

---

Built with ❤️ for milk dairy businesses in India
