from django.db import migrations, models
from django.conf import settings
import datetime
from decimal import Decimal


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel('MilkProduct', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('name', models.CharField(max_length=100)),
            ('unit', models.CharField(choices=[('L','Litre'),('mL','Millilitre'),('kg','Kilogram'),('g','Gram')], default='L', max_length=5)),
            ('default_price', models.DecimalField(decimal_places=2, max_digits=8)),
            ('description', models.TextField(blank=True)),
            ('is_active', models.BooleanField(default=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'ordering':['name']}),

        migrations.CreateModel('ExpenseCategory', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('name', models.CharField(max_length=80)),
            ('icon', models.CharField(max_length=20, default='other')),
            ('color', models.CharField(max_length=20, default='#6b7280')),
            ('is_active', models.BooleanField(default=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'ordering':['name'],'verbose_name_plural':'Expense Categories'}),

        migrations.CreateModel('Customer', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('customer_id', models.CharField(blank=True, max_length=20, unique=True)),
            ('name', models.CharField(max_length=150)),
            ('phone', models.CharField(max_length=15)),
            ('alternate_phone', models.CharField(blank=True, max_length=15)),
            ('email', models.EmailField(blank=True)),
            ('address', models.TextField()),
            ('area', models.CharField(choices=[('north','North Zone'),('south','South Zone'),('east','East Zone'),('west','West Zone'),('central','Central Zone')], default='central', max_length=20)),
            ('landmark', models.CharField(blank=True, max_length=100)),
            ('pincode', models.CharField(blank=True, max_length=10)),
            ('delivery_schedule', models.CharField(choices=[('daily','Every Day'),('alternate','Alternate Days (Odd: 1,3,5)'),('alt_even','Alternate Days (Even: 2,4,6)'),('weekdays','Weekdays Only (Mon-Fri)'),('weekends','Weekends Only (Sat-Sun)'),('thrice','Thrice a Week (Mon/Wed/Fri)'),('twice','Twice a Week (Mon/Thu)'),('custom','Custom Days')], default='daily', max_length=20)),
            ('delivery_time', models.TimeField(default=datetime.time(6,0))),
            ('delivery_days', models.CharField(default='1,2,3,4,5,6,7', max_length=50)),
            ('default_qty', models.DecimalField(decimal_places=2, default=Decimal('1.00'), max_digits=6)),
            ('custom_price', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
            ('opening_balance', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10)),
            ('credit_limit', models.DecimalField(decimal_places=2, default=Decimal('5000.00'), max_digits=10)),
            ('status', models.CharField(choices=[('active','Active'),('inactive','Inactive'),('paused','Paused')], default='active', max_length=10)),
            ('joining_date', models.DateField(default=datetime.date.today)),
            ('notes', models.TextField(blank=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('default_product', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to='delivery.milkproduct')),
            ('created_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, related_name='customers_created')),
        ], options={'ordering':['name']}),

        migrations.CreateModel('CustomerSubscription', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('quantity', models.DecimalField(decimal_places=2, default=Decimal('1.00'), max_digits=6)),
            ('custom_price', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
            ('is_active', models.BooleanField(default=True)),
            ('start_date', models.DateField(default=datetime.date.today)),
            ('notes', models.CharField(blank=True, max_length=200)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('customer', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='subscriptions', to='delivery.customer')),
            ('product', models.ForeignKey(on_delete=models.deletion.CASCADE, to='delivery.milkproduct')),
        ], options={'ordering':['product__name']}),
        migrations.AlterUniqueTogether(name='customersubscription', unique_together={('customer','product')}),

        migrations.CreateModel('DailyDelivery', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('date', models.DateField(default=datetime.date.today)),
            ('quantity', models.DecimalField(decimal_places=2, max_digits=6)),
            ('price_per_unit', models.DecimalField(decimal_places=2, max_digits=8)),
            ('amount', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10)),
            ('is_delivered', models.BooleanField(default=True)),
            ('not_delivered_reason', models.CharField(blank=True, max_length=200)),
            ('notes', models.CharField(blank=True, max_length=200)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('customer', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='deliveries', to='delivery.customer')),
            ('product', models.ForeignKey(null=True, on_delete=models.deletion.SET_NULL, to='delivery.milkproduct')),
            ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, related_name='deliveries_recorded')),
        ], options={'ordering':['-date','customer__name']}),
        migrations.AlterUniqueTogether(name='dailydelivery', unique_together={('customer','date','product')}),

        migrations.CreateModel('Bill', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('bill_number', models.CharField(blank=True, max_length=20, unique=True)),
            ('month', models.IntegerField()),
            ('year', models.IntegerField()),
            ('from_date', models.DateField()),
            ('to_date', models.DateField()),
            ('total_quantity', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=8)),
            ('total_amount', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10)),
            ('discount', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=8)),
            ('net_amount', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10)),
            ('previous_balance', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10)),
            ('grand_total', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10)),
            ('status', models.CharField(choices=[('unpaid','Unpaid'),('partial','Partial'),('paid','Paid')], default='unpaid', max_length=10)),
            ('notes', models.TextField(blank=True)),
            ('generated_at', models.DateTimeField(auto_now_add=True)),
            ('customer', models.ForeignKey(on_delete=models.deletion.CASCADE, to='delivery.customer')),
            ('generated_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, related_name='bills_generated')),
        ], options={'ordering':['-year','-month','customer__name']}),
        migrations.AlterUniqueTogether(name='bill', unique_together={('customer','month','year')}),

        migrations.CreateModel('Payment', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
            ('payment_method', models.CharField(choices=[('cash','Cash'),('upi','UPI'),('bank','Bank Transfer'),('cheque','Cheque'),('other','Other')], default='cash', max_length=10)),
            ('reference_number', models.CharField(blank=True, max_length=50)),
            ('payment_date', models.DateField(default=datetime.date.today)),
            ('notes', models.CharField(blank=True, max_length=200)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('bill', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to='delivery.bill')),
            ('customer', models.ForeignKey(on_delete=models.deletion.CASCADE, to='delivery.customer')),
            ('received_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, related_name='payments_received')),
        ], options={'ordering':['-payment_date']}),

        migrations.CreateModel('Expense', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('title', models.CharField(max_length=200)),
            ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
            ('date', models.DateField(default=datetime.date.today)),
            ('payment_mode', models.CharField(choices=[('cash','Cash'),('upi','UPI'),('bank','Bank Transfer'),('cheque','Cheque'),('credit','Credit/Loan')], default='cash', max_length=10)),
            ('vendor', models.CharField(blank=True, max_length=100)),
            ('invoice_no', models.CharField(blank=True, max_length=50)),
            ('description', models.TextField(blank=True)),
            ('receipt', models.ImageField(blank=True, null=True, upload_to='receipts/')),
            ('is_recurring', models.BooleanField(default=False)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('category', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to='delivery.expensecategory')),
            ('added_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, related_name='expenses_added')),
        ], options={'ordering':['-date','-created_at']}),

        migrations.CreateModel('DeliveryRoute', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('name', models.CharField(max_length=100)),
            ('area', models.CharField(max_length=50)),
            ('delivery_boy', models.CharField(blank=True, max_length=100)),
            ('notes', models.TextField(blank=True)),
            ('is_active', models.BooleanField(default=True)),
            ('customers', models.ManyToManyField(blank=True, to='delivery.customer')),
        ]),

        migrations.CreateModel('Notification', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('title', models.CharField(max_length=200)),
            ('message', models.TextField()),
            ('type', models.CharField(choices=[('info','Info'),('warning','Warning'),('success','Success'),('error','Error')], default='info', max_length=10)),
            ('is_read', models.BooleanField(default=False)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'ordering':['-created_at']}),
    ]
