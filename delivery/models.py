from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
import datetime


class MilkProduct(models.Model):
    UNIT_CHOICES = [('L','Litre'),('mL','Millilitre'),('kg','Kilogram'),('g','Gram')]
    name          = models.CharField(max_length=100)
    unit          = models.CharField(max_length=5, choices=UNIT_CHOICES, default='L')
    default_price = models.DecimalField(max_digits=8, decimal_places=2)
    description   = models.TextField(blank=True)
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.unit})"


class Customer(models.Model):
    AREA_CHOICES = [
        ('north','North Venduvazhy'),('south','South Venduvazhy'),
        ('Substation','Substation'),('Madathipady','Madathipady'),('Elavanad','Elavanad'),('314','314'),('Onnam Mile','Onnam Mile')
    ]
    STATUS_CHOICES   = [('active','Active'),('inactive','Inactive'),('paused','Paused')]
    SCHEDULE_CHOICES = [
        ('daily',    'Every Day'),
        ('alternate','Alternate Days (Odd: 1,3,5)'),
        ('alt_even', 'Alternate Days (Even: 2,4,6)'),
        ('weekdays', 'Weekdays Only (Mon-Fri)'),
        ('weekends', 'Weekends Only (Sat-Sun)'),
        ('thrice',   'Thrice a Week (Mon/Wed/Fri)'),
        ('twice',    'Twice a Week (Mon/Thu)'),
        ('custom',   'Custom Days'),
    ]

    customer_id     = models.CharField(max_length=20, unique=True, blank=True)
    name            = models.CharField(max_length=150)
    phone           = models.CharField(max_length=15)
    alternate_phone = models.CharField(max_length=15, blank=True)
    email           = models.EmailField(blank=True)
    address         = models.TextField()
    area            = models.CharField(max_length=20, choices=AREA_CHOICES, default='central')
    landmark        = models.CharField(max_length=100, blank=True)
    pincode         = models.CharField(max_length=10, blank=True)

    delivery_schedule = models.CharField(max_length=20, choices=SCHEDULE_CHOICES, default='daily')
    delivery_time     = models.TimeField(default=datetime.time(6, 0))
    delivery_days     = models.CharField(max_length=50, default='1,2,3,4,5,6,7')

    # Legacy single-product fields (kept for backward compat, new multi-sub via CustomerSubscription)
    default_product = models.ForeignKey(MilkProduct, on_delete=models.SET_NULL, null=True, blank=True)
    default_qty     = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('1.00'))
    custom_price    = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    opening_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    credit_limit    = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('5000.00'))

    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    joining_date = models.DateField(default=datetime.date.today)
    notes        = models.TextField(blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.customer_id} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.customer_id:
            import random
            self.customer_id = f"MW{random.randint(1000,9999)}"
            while Customer.objects.filter(customer_id=self.customer_id).exists():
                self.customer_id = f"MW{random.randint(1000,9999)}"
        super().save(*args, **kwargs)

    def should_deliver_on(self, date):
        s = self.delivery_schedule
        if s == 'daily':     return True
        if s == 'alternate': return date.day % 2 == 1
        if s == 'alt_even':  return date.day % 2 == 0
        if s == 'weekdays':  return date.weekday() < 5
        if s == 'weekends':  return date.weekday() >= 5
        if s == 'thrice':    return date.weekday() in (0, 2, 4)
        if s == 'twice':     return date.weekday() in (0, 3)
        if s == 'custom':    return str(date.isoweekday()) in self.delivery_days.split(',')
        return True

    @property
    def price_per_unit(self):
        if self.custom_price:
            return self.custom_price
        if self.default_product:
            return self.default_product.default_price
        return Decimal('0.00')

    @property
    def active_subscriptions(self):
        return self.subscriptions.filter(is_active=True).select_related('product')

    @property
    def outstanding_balance(self):
        from django.db.models import Sum
        billed = self.bill_set.aggregate(t=Sum('net_amount'))['t'] or Decimal('0')
        paid   = self.payment_set.aggregate(t=Sum('amount'))['t']  or Decimal('0')
        return self.opening_balance + billed - paid


# ── MULTI-PRODUCT SUBSCRIPTION ──────────────────────────────────────────────
class CustomerSubscription(models.Model):
    """One row per product a customer subscribes to."""
    customer     = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='subscriptions')
    product      = models.ForeignKey(MilkProduct, on_delete=models.CASCADE)
    quantity     = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('1.00'))
    custom_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                        help_text='Leave blank to use product default price')
    is_active    = models.BooleanField(default=True)
    start_date   = models.DateField(default=datetime.date.today)
    notes        = models.CharField(max_length=200, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['product__name']
        unique_together = ['customer', 'product']

    def __str__(self):
        return f"{self.customer.name} – {self.product.name} x{self.quantity}"

    @property
    def price(self):
        return self.custom_price if self.custom_price else self.product.default_price

    @property
    def daily_amount(self):
        return self.quantity * self.price


class DailyDelivery(models.Model):
    customer       = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='deliveries')
    product        = models.ForeignKey(MilkProduct, on_delete=models.SET_NULL, null=True)
    date           = models.DateField(default=datetime.date.today)
    quantity       = models.DecimalField(max_digits=6, decimal_places=2)
    price_per_unit = models.DecimalField(max_digits=8, decimal_places=2)
    amount         = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    is_delivered   = models.BooleanField(default=True)
    not_delivered_reason = models.CharField(max_length=200, blank=True)
    notes          = models.CharField(max_length=200, blank=True)
    recorded_by    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', 'customer__name']
        unique_together = ['customer', 'date', 'product']

    def __str__(self):
        return f"{self.customer.name} - {self.date} - {self.quantity}L"

    def save(self, *args, **kwargs):
        self.amount = (self.quantity * self.price_per_unit) if self.is_delivered else Decimal('0')
        super().save(*args, **kwargs)


class Bill(models.Model):
    STATUS_CHOICES = [('unpaid','Unpaid'),('partial','Partial'),('paid','Paid')]

    bill_number      = models.CharField(max_length=20, unique=True, blank=True)
    customer         = models.ForeignKey(Customer, on_delete=models.CASCADE)
    month            = models.IntegerField()
    year             = models.IntegerField()
    from_date        = models.DateField()
    to_date          = models.DateField()
    total_quantity   = models.DecimalField(max_digits=8,  decimal_places=2, default=Decimal('0'))
    total_amount     = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    discount         = models.DecimalField(max_digits=8,  decimal_places=2, default=Decimal('0'))
    net_amount       = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    previous_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    grand_total      = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    status           = models.CharField(max_length=10, choices=STATUS_CHOICES, default='unpaid')
    notes            = models.TextField(blank=True)
    generated_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    generated_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering         = ['-year', '-month', 'customer__name']
        unique_together  = ['customer', 'month', 'year']

    def __str__(self):
        return f"Bill#{self.bill_number} - {self.customer.name}"

    def save(self, *args, **kwargs):
        if not self.bill_number:
            import random
            self.bill_number = f"MW-{self.year}{self.month:02d}-{random.randint(100,999)}"
        self.net_amount  = self.total_amount - self.discount
        self.grand_total = self.net_amount + self.previous_balance
        super().save(*args, **kwargs)

    @property
    def amount_paid(self):
        from django.db.models import Sum
        return self.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')

    @property
    def amount_due(self):
        return max(Decimal('0'), self.grand_total - self.amount_paid)


class Payment(models.Model):
    METHOD_CHOICES = [
        ('cash','Cash'),('upi','UPI'),('bank','Bank Transfer'),
        ('cheque','Cheque'),('other','Other'),
    ]
    customer         = models.ForeignKey(Customer, on_delete=models.CASCADE)
    bill             = models.ForeignKey(Bill, on_delete=models.SET_NULL, null=True, blank=True)
    amount           = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method   = models.CharField(max_length=10, choices=METHOD_CHOICES, default='cash')
    reference_number = models.CharField(max_length=50, blank=True)
    payment_date     = models.DateField(default=datetime.date.today)
    notes            = models.CharField(max_length=200, blank=True)
    received_by      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date']

    def __str__(self):
        return f"Payment - {self.customer.name} - Rs.{self.amount}"


# ── EXPENSE TRACKER ──────────────────────────────────────────────────────────
class ExpenseCategory(models.Model):
    name      = models.CharField(max_length=80)
    icon      = models.CharField(max_length=20, default='other')  # stores slug like 'feed','medicine'
    color     = models.CharField(max_length=20, default='#6b7280')
    is_active = models.BooleanField(default=True)
    created_at= models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Expense Categories'

    def __str__(self):
        return self.name

    def get_icon_emoji(self):
        MAP = {
            'feed':'🌾','medicine':'💊','electricity':'⚡','travel':'🚗',
            'maintenance':'🔧','labour':'👷','milk':'🥛','vet':'🏥',
            'packaging':'📦','testing':'🧪','water':'💧','other':'🌿',
        }
        return MAP.get(self.icon, '🌿')


class Expense(models.Model):
    PAYMENT_CHOICES = [
        ('cash','Cash'),('upi','UPI'),('bank','Bank Transfer'),
        ('cheque','Cheque'),('credit','Credit/Loan'),
    ]
    category     = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True)
    title        = models.CharField(max_length=200)
    amount       = models.DecimalField(max_digits=10, decimal_places=2)
    date         = models.DateField(default=datetime.date.today)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default='cash')
    vendor       = models.CharField(max_length=100, blank=True)
    invoice_no   = models.CharField(max_length=50,  blank=True)
    description  = models.TextField(blank=True)
    receipt      = models.ImageField(upload_to='receipts/', null=True, blank=True)
    is_recurring = models.BooleanField(default=False)
    added_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.title} - Rs.{self.amount} ({self.date})"


class DeliveryRoute(models.Model):
    name         = models.CharField(max_length=100)
    area         = models.CharField(max_length=50)
    delivery_boy = models.CharField(max_length=100, blank=True)
    customers    = models.ManyToManyField(Customer, blank=True)
    notes        = models.TextField(blank=True)
    is_active    = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Notification(models.Model):
    TYPE_CHOICES = [('info','Info'),('warning','Warning'),('success','Success'),('error','Error')]
    title      = models.CharField(max_length=200)
    message    = models.TextField()
    type       = models.CharField(max_length=10, choices=TYPE_CHOICES, default='info')
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
