@echo off
title MilkDairy Pro v5 - Setup
color 0B
echo.
echo  ============================================
echo   MilkDairy Pro v5 - Auto Setup
echo   Full Bill Management + Bug Fixes
echo  ============================================
echo.
python --version >nul 2>&1 || (echo [ERROR] Install Python 3.10+ from python.org & pause & exit /b 1)
echo [OK] Python found
python -m venv venv
call venv\Scripts\activate.bat
echo [1/5] Installing packages...
pip install "django>=4.2,<5.0" reportlab pillow --quiet
echo [2/5] Running migrations...
python manage.py migrate
echo [3/5] Create admin login:
python manage.py createsuperuser
echo [4/5] Loading sample data...
python manage.py shell -c "from delivery.models import MilkProduct,Customer,ExpenseCategory,Expense;import datetime;from decimal import Decimal;[MilkProduct.objects.get_or_create(name=n,defaults={'unit':'L','default_price':Decimal(str(p))}) for n,p in [('Full Cream Milk',70),('Toned Milk',55),('Double Toned',50),('Buffalo Milk',80)]];[ExpenseCategory.objects.get_or_create(name=n,defaults={'icon':i}) for n,i in [('Feed / Fodder','🌾'),('Medicine / Vaccines','💊'),('Electricity','⚡'),('Travel Expense','🚗'),('Maintenance / Repair','🔧'),('Labour / Wages','👷'),('Veterinary','🏥'),('Packaging','📦'),('Other','🌿')]];print('Sample data loaded!')"
echo.
echo  ============================================
echo   DONE! Starting server...
echo   URL:   http://127.0.0.1:8000
echo   Admin: http://127.0.0.1:8000/admin
echo  ============================================
echo.
python manage.py runserver
pause
