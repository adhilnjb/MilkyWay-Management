from django.contrib import admin
from .models import (Customer, CustomerSubscription, DailyDelivery,
                     Bill, Payment, MilkProduct, DeliveryRoute,
                     Notification, Expense, ExpenseCategory)

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display  = ['customer_id','name','phone','area','delivery_schedule','status']
    list_filter   = ['status','area','delivery_schedule']
    search_fields = ['name','phone','customer_id']

@admin.register(CustomerSubscription)
class SubAdmin(admin.ModelAdmin):
    list_display = ['customer','product','quantity','custom_price','is_active']
    list_filter  = ['is_active','product']

@admin.register(DailyDelivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ['customer','product','date','quantity','price_per_unit','amount','is_delivered']
    list_filter  = ['date','is_delivered']

@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ['bill_number','customer','month','year','grand_total','status']
    list_filter  = ['status','month','year']

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['customer','amount','payment_method','payment_date']

@admin.register(MilkProduct)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name','unit','default_price','is_active']

@admin.register(ExpenseCategory)
class ExpCatAdmin(admin.ModelAdmin):
    list_display = ['icon','name','is_active']

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display  = ['title','category','amount','date','payment_mode']
    list_filter   = ['category','payment_mode','date']
    search_fields = ['title','vendor']

admin.site.register(DeliveryRoute)
admin.site.register(Notification)
