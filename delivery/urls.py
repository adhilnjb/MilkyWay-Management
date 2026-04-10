from django.urls import path
from . import views

urlpatterns = [
    path('login/',  views.login_view,  name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('',        views.dashboard,   name='dashboard'),

    # Customers
    path('customers/',                     views.customer_list,   name='customer_list'),
    path('customers/add/',                 views.customer_add,    name='customer_add'),
    path('customers/<int:pk>/',            views.customer_detail, name='customer_detail'),
    path('customers/<int:pk>/edit/',       views.customer_edit,   name='customer_edit'),
    path('customers/<int:pk>/delete/',     views.customer_delete, name='customer_delete'),

    # Subscriptions
    path('subscriptions/<int:pk>/toggle/', views.subscription_toggle, name='subscription_toggle'),

    # Deliveries
    path('delivery/',             views.delivery_today,       name='delivery_today'),
    path('delivery/list/',        views.delivery_list,        name='delivery_list'),
    path('delivery/bulk-update/', views.delivery_bulk_update, name='delivery_bulk_update'),
    path('delivery/quick-add/',   views.delivery_quick_add,   name='delivery_quick_add'),

    # Bills
    path('bills/',                       views.bill_list,      name='bill_list'),
    path('bills/generate/',              views.bill_generate,  name='bill_generate'),
    path('bills/<int:pk>/',              views.bill_detail,    name='bill_detail'),
    path('bills/<int:pk>/edit/',         views.bill_edit,      name='bill_edit'),
    path('bills/<int:pk>/delete/',       views.bill_delete,    name='bill_delete'),
    path('bills/<int:pk>/pdf/',          views.bill_pdf,       name='bill_pdf'),
    path('bills/<int:pk>/mark-paid/',    views.bill_mark_paid, name='bill_mark_paid'),
    path('bills/<int:pk>/whatsapp/',     views.bill_whatsapp,  name='bill_whatsapp'),
    path('api/bill/<int:pk>/status/',    views.api_bill_status, name='api_bill_status'),

    # Payments
    path('payments/',                       views.payment_list,         name='payment_list'),
    path('payments/add/',                   views.payment_add,          name='payment_add'),
    path('payments/add/<int:customer_pk>/', views.payment_add,          name='payment_add_customer'),
    path('payments/<int:pk>/delete/',       views.payment_delete,       name='payment_delete'),

    # Products
    path('products/',                views.product_list, name='product_list'),
    path('products/add/',            views.product_add,  name='product_add'),
    path('products/<int:pk>/edit/',  views.product_edit, name='product_edit'),

    # Expenses
    path('expenses/',                  views.expense_list,          name='expense_list'),
    path('expenses/add/',              views.expense_add,           name='expense_add'),
    path('expenses/<int:pk>/edit/',    views.expense_edit,          name='expense_edit'),
    path('expenses/<int:pk>/delete/',  views.expense_delete,        name='expense_delete'),
    path('expenses/categories/',       views.expense_category_list, name='expense_category_list'),

    # Reports
    path('reports/', views.reports, name='reports'),

    # API
    path('api/customer/<int:pk>/price/', views.api_customer_price, name='api_customer_price'),
]
