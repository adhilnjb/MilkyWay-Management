import io, datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db.models import Sum, Count, Q, Prefetch, Avg
from django.core.paginator import Paginator
from decimal import Decimal, ROUND_HALF_UP
import datetime, json, calendar, io, urllib.parse
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, HRFlowable, KeepTogether,
)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .models import Bill, DailyDelivery, Payment

from .models import (Customer, CustomerSubscription, DailyDelivery,
                     Bill, Payment, MilkProduct, Notification,
                     Expense, ExpenseCategory, DeliveryRoute)


# ── helpers ──────────────────────────────────────────────────────────────────
from decimal import Decimal, InvalidOperation

def _dec(value, default='0'):
    """Safely convert a form value to Decimal, falling back to default."""
    if isinstance(value, str):
        value = value.strip()
    if value in (None, ''):
        value = default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(str(default))


def _parse_date(s, fallback=None):
    if not s:
        return fallback or datetime.date.today()
    try:
        return datetime.datetime.strptime(str(s).strip(), '%Y-%m-%d').date()
    except ValueError:
        return fallback or datetime.date.today()


# ── AUTH ──────────────────────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        user = authenticate(request, username=request.POST.get('username',''),
                            password=request.POST.get('password',''))
        if user:
            login(request, user)
            return redirect('dashboard')
        messages.error(request, 'Invalid username or password.')
    return render(request, 'delivery/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


# ── DASHBOARD ─────────────────────────────────────────────────────────────────
@login_required
def dashboard(request):
    today = datetime.date.today()
    month, year = today.month, today.year

    total_customers   = Customer.objects.filter(status='active').count()
    today_deliveries  = DailyDelivery.objects.filter(date=today, is_delivered=True)
    today_qty         = today_deliveries.aggregate(q=Sum('quantity'))['q'] or Decimal('00.00')
    today_revenue     = today_deliveries.aggregate(r=Sum('amount'))['r']   or Decimal('0.00')

    month_deliveries  = DailyDelivery.objects.filter(date__month=month, date__year=year, is_delivered=True)
    month_qty         = month_deliveries.aggregate(q=Sum('quantity'))['q'] or Decimal('00.00')
    month_revenue     = month_deliveries.aggregate(r=Sum('amount'))['r']   or Decimal('0.00')

    pending_bills     = Bill.objects.filter(status__in=['unpaid','partial']).count()
    pending_amount    = Bill.objects.filter(status__in=['unpaid','partial']).aggregate(t=Sum('grand_total'))['t'] or Decimal('0.00')

    month_expenses    = Expense.objects.filter(date__month=month, date__year=year).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    week_start = today - datetime.timedelta(days=6)
    week_data  = {
        row['date']: row
        for row in DailyDelivery.objects
            .filter(date__gte=week_start, date__lte=today, is_delivered=True)
            .values('date')
            .annotate(q=Sum('quantity'), r=Sum('amount'))
    }
    chart_labels, chart_qty, chart_rev = [], [], []
    for i in range(6, -1, -1):
        d = today - datetime.timedelta(days=i)
        row = week_data.get(d, {})
        chart_labels.append(d.strftime('%d %b'))
        chart_qty.append(float(row.get('q') or 0))
        chart_rev.append(float(row.get('r') or 0))

    area_data  = Customer.objects.filter(status='active').values('area').annotate(c=Count('id'))
    exp_by_cat = (Expense.objects
                  .filter(date__month=month, date__year=year)
                  .values('category__name')
                  .annotate(total=Sum('amount'))
                  .order_by('-total')[:5])

    recent_deliveries = DailyDelivery.objects.select_related('customer', 'product').order_by('-created_at')[:10]
    delivered_ids     = today_deliveries.values_list('customer_id', flat=True)
    missed_customers  = Customer.objects.filter(status='active').exclude(id__in=delivered_ids)[:8]
    notifications     = Notification.objects.filter(is_read=False)[:5]

    return render(request, 'delivery/dashboard.html', {
        'total_customers': total_customers,
        'today_qty': today_qty, 'today_revenue': today_revenue,
        'month_qty': month_qty, 'month_revenue': month_revenue,
        'pending_bills': pending_bills, 'pending_amount': pending_amount,
        'month_expenses': month_expenses,
        'net_profit': month_revenue - month_expenses,
        'chart_labels': json.dumps(chart_labels),
        'chart_qty': json.dumps(chart_qty),
        'chart_rev': json.dumps(chart_rev),
        'area_data': list(area_data),
        'exp_by_cat': list(exp_by_cat),
        'recent_deliveries': recent_deliveries,
        'missed_customers': missed_customers,
        'notifications': notifications,
        'today': today,
    })


# ── CUSTOMERS ─────────────────────────────────────────────────────────────────
@login_required
def customer_list(request):
    qs = Customer.objects.select_related('default_product').prefetch_related(
        Prefetch('subscriptions',
                 queryset=CustomerSubscription.objects.filter(is_active=True).select_related('product'))
    )
    q        = request.GET.get('q','')
    status   = request.GET.get('status','')
    area     = request.GET.get('area','')
    schedule = request.GET.get('schedule','')

    if q:        qs = qs.filter(Q(name__icontains=q)|Q(phone__icontains=q)|Q(customer_id__icontains=q))
    if status:   qs = qs.filter(status=status)
    if area:     qs = qs.filter(area=area)
    if schedule: qs = qs.filter(delivery_schedule=schedule)

    all_c     = Customer.objects.all()
    paginator = Paginator(qs.order_by('name'), 20)
    page      = paginator.get_page(request.GET.get('page'))
    return render(request, 'delivery/customer_list.html', {
        'page_obj': page, 'q': q, 'status': status, 'area': area, 'schedule': schedule,
        'status_choices':   Customer.STATUS_CHOICES,
        'area_choices':     Customer.AREA_CHOICES,
        'schedule_choices': Customer.SCHEDULE_CHOICES,
        'total':          qs.count(),
        'active_count':   all_c.filter(status='active').count(),
        'paused_count':   all_c.filter(status='paused').count(),
        'inactive_count': all_c.filter(status='inactive').count(),
    })


# NOTE: _dec() (value + optional default, defined near the top of
# this file) already covers this. Removed the duplicate definition
# and duplicate imports that used to be here — keeping two copies
# around is exactly what let the old broken version further down
# silently take priority.


# NOTE: _parse_date() (s, fallback=None) is already defined near the
# top of this file. Removed the duplicate single-argument definition
# that used to be here — it was silently overriding the original one
# for every call in this file, which caused
# "_parse_date() takes 1 positional argument but 2 were given" on
# /delivery/ (and would break any other view passing a fallback).


@login_required
def customer_add(request):
    products = MilkProduct.objects.filter(is_active=True)
    if request.method == 'POST':
        try:
            customer = _create_or_update_customer(request.POST, user=request.user)
            _save_subscriptions(customer, request.POST)
            messages.success(request, f'Customer {customer.name} added! ID: {customer.customer_id}')
            return redirect('customer_detail', pk=customer.pk)
        except Exception as e:
            messages.error(request, f'Error saving customer: {e}')
    return render(request, 'delivery/customer_form.html', {
        'products': products, 'action': 'Add',
        'status_choices':   Customer.STATUS_CHOICES,
        'area_choices':     Customer.AREA_CHOICES,
        'schedule_choices': Customer.SCHEDULE_CHOICES,
    })


@login_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    products = MilkProduct.objects.filter(is_active=True)
    if request.method == 'POST':
        try:
            _create_or_update_customer(request.POST, customer=customer)
            _save_subscriptions(customer, request.POST)
            messages.success(request, 'Customer updated successfully!')
            return redirect('customer_detail', pk=pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
    existing_subs = customer.subscriptions.filter(is_active=True).select_related('product')
    return render(request, 'delivery/customer_form.html', {
        'customer': customer, 'products': products, 'action': 'Edit',
        'status_choices':   Customer.STATUS_CHOICES,
        'area_choices':     Customer.AREA_CHOICES,
        'schedule_choices': Customer.SCHEDULE_CHOICES,
        'existing_subs': existing_subs,
    })


def _create_or_update_customer(p, customer=None, user=None):
    if customer is None:
        customer = Customer()
        customer.created_by = user

    customer.name            = p.get('name', '').strip()
    customer.phone           = p.get('phone', '').strip()
    customer.alternate_phone = p.get('alternate_phone', '').strip()
    customer.email           = p.get('email', '').strip()
    customer.address         = p.get('address', '').strip()
    customer.area            = p.get('area', 'central')
    customer.landmark        = p.get('landmark', '').strip()
    customer.pincode         = p.get('pincode', '').strip()
    customer.delivery_schedule = p.get('delivery_schedule', 'daily')
    customer.delivery_time   = p.get('delivery_time', '06:00') or '06:00'
    customer.delivery_days   = p.get('delivery_days', '1,2,3,4,5,6,7')
    customer.opening_balance = _dec(p.get('opening_balance', '0'))
    customer.credit_limit    = _dec(p.get('credit_limit', '5000'), '5000')
    customer.status          = p.get('status', 'active')
    customer.notes           = p.get('notes', '').strip()
    customer.joining_date    = _parse_date(p.get('joining_date'))

    prod_id = p.get('default_product', '').strip()
    customer.default_product = MilkProduct.objects.filter(pk=prod_id).first() if prod_id else None
    customer.default_qty     = _dec(p.get('default_qty', '1'), '1')
    cp = p.get('custom_price', '').strip()
    customer.custom_price    = _dec(cp) if cp else None

    customer.save()
    return customer


def _save_subscriptions(customer, p):
    prod_ids = p.getlist('sub_product')
    qtys     = p.getlist('sub_qty')
    prices   = p.getlist('sub_price')

    if not prod_ids:
        return

    customer.subscriptions.all().update(is_active=False)

    for i, pid in enumerate(prod_ids):
        pid = pid.strip()
        if not pid:
            continue
        try:
            product = MilkProduct.objects.get(pk=pid)
        except MilkProduct.DoesNotExist:
            continue

        qty       = _dec(qtys[i] if i < len(qtys) else '1', '1')
        price_raw = prices[i].strip() if i < len(prices) else ''
        price     = _dec(price_raw) if price_raw else None

        CustomerSubscription.objects.update_or_create(
            customer=customer, product=product,
            defaults={'quantity': qty, 'custom_price': price, 'is_active': True}
        )


@login_required
def customer_detail(request, pk):
    customer      = get_object_or_404(Customer, pk=pk)
    today         = datetime.date.today()
    month, year   = today.month, today.year
    subscriptions = customer.subscriptions.filter(is_active=True).select_related('product')
    deliveries    = DailyDelivery.objects.filter(customer=customer).select_related('product').order_by('-date')[:30]
    bills         = Bill.objects.filter(customer=customer).order_by('-year', '-month')
    payments      = Payment.objects.filter(customer=customer).order_by('-payment_date')[:10]
    month_qs      = DailyDelivery.objects.filter(customer=customer, date__month=month,
                                                  date__year=year, is_delivered=True)
    month_qty     = month_qs.aggregate(q=Sum('quantity'))['q'] or Decimal('0.00')
    month_amt     = month_qs.aggregate(a=Sum('amount'))['a']   or Decimal('0.00')
    return render(request, 'delivery/customer_detail.html', {
        'customer': customer, 'subscriptions': subscriptions,
        'deliveries': deliveries, 'bills': bills, 'payments': payments,
        'month_qty': month_qty, 'month_amount': month_amt,
        'outstanding': customer.outstanding_balance,
    })


@login_required
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        name = customer.name
        customer.delete()
        messages.success(request, f'Customer {name} deleted.')
        return redirect('customer_list')
    return render(request, 'delivery/confirm_delete.html', {'object': customer, 'type': 'Customer'})


# ── SUBSCRIPTIONS ─────────────────────────────────────────────────────────────
@login_required
def subscription_toggle(request, pk):
    sub = get_object_or_404(CustomerSubscription, pk=pk)
    if request.method == 'POST':
        sub.is_active = not sub.is_active
        sub.save()
        return JsonResponse({'success': True, 'is_active': sub.is_active})
    return JsonResponse({'success': False})


# ── DAILY DELIVERY ────────────────────────────────────────────────────────────
def should_deliver_on(self, date):
        # 1. If the customer is completely inactive, never deliver
        if self.status == 'inactive':
            return False
            
        # 2. If the customer is temporarily paused, do not deliver today
        if self.status == 'paused':
            return False

        # 3. Otherwise, check their normal delivery schedule patterns
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

@login_required
def delivery_today(request):
    today    = datetime.date.today()
    date_str = request.GET.get('date', today.strftime('%Y-%m-%d'))
    sel_date = _parse_date(date_str, today)
    date_str = sel_date.strftime('%Y-%m-%d')

    filter_area     = request.GET.get('area','')
    filter_status   = request.GET.get('status','')
    filter_search   = request.GET.get('search','').strip()
    filter_schedule = request.GET.get('schedule','')

    # CHANGED: Changed filter(status='active') to exclude(status='inactive')
    # This brings in both Active and Paused customers into the daily tracker list.
    customers = (Customer.objects.exclude(status='inactive')
                 .select_related('default_product')
                 .prefetch_related(
                     Prefetch('subscriptions',
                              queryset=CustomerSubscription.objects.filter(is_active=True).select_related('product'))
                 ).order_by('area','name'))

    if filter_area:     customers = customers.filter(area=filter_area)
    if filter_search:   customers = customers.filter(
        Q(name__icontains=filter_search)|Q(phone__icontains=filter_search)|
        Q(customer_id__icontains=filter_search))
    if filter_schedule: customers = customers.filter(delivery_schedule=filter_schedule)

    deliveries_map = {}
    for d in DailyDelivery.objects.filter(date=sel_date).select_related('customer','product'):
        deliveries_map[(d.customer_id, d.product_id)] = d

    rows = []
    for c in customers:
        # If c.status is 'paused', your updated should_deliver_on() handles returning False
        scheduled = c.should_deliver_on(sel_date)
        subs = list(c.active_subscriptions)

        if not subs and c.default_product:
            class _FakeSub:
                pass
            fs = _FakeSub()
            fs.id = None
            fs.product   = c.default_product
            fs.quantity  = c.default_qty
            fs.price     = c.price_per_unit
            subs = [fs]

        sub_rows = []
        for sub in subs:
            key      = (c.id, sub.product.id if sub.product else None)
            existing = deliveries_map.get(key)
            sub_rows.append({'sub': sub, 'delivery': existing})

        # Pack row details along with the explicit user status
        row = {
            'customer': c, 
            'scheduled': scheduled, 
            'sub_rows': sub_rows,
            'is_paused': (c.status == 'paused') # Helpful shortcut variable for your template
        }
        
        if filter_status == 'delivered':
            if not any(sr['delivery'] and sr['delivery'].is_delivered for sr in sub_rows):
                continue
        elif filter_status == 'pending':
            if all(sr['delivery'] and sr['delivery'].is_delivered for sr in sub_rows):
                continue
        rows.append(row)

    total_delivered = sum(1 for r in rows if any(
        sr['delivery'] and sr['delivery'].is_delivered for sr in r['sub_rows']))
    
    total_qty    = sum(Decimal(str(sr['delivery'].quantity)) for r in rows for sr in r['sub_rows']
                       if sr['delivery'] and sr['delivery'].is_delivered)
    
    total_amount = sum(Decimal(str(sr['delivery'].amount)) for r in rows for sr in r['sub_rows']
                       if sr['delivery'] and sr['delivery'].is_delivered)
    
    scheduled_count = sum(1 for r in rows if r['scheduled'])
    pending_count   = len(rows) - total_delivered

    return render(request, 'delivery/delivery_today.html', {
        'rows': rows, 'sel_date': sel_date, 'today': today,
        'yesterday': (sel_date - datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
        'tomorrow':  (sel_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
        'total_delivered': total_delivered, 'total_qty': total_qty,
        'total_amount': total_amount, 'scheduled_count': scheduled_count,
        'pending_count': pending_count,
        'filter_area': filter_area, 'filter_status': filter_status,
        'filter_search': filter_search, 'filter_schedule': filter_schedule,
        'area_choices':     Customer.AREA_CHOICES,
        'schedule_choices': Customer.SCHEDULE_CHOICES,
    })

@login_required
def delivery_bulk_update(request):
    if request.method != 'POST':
        return redirect('delivery_today')

    date_str = request.POST.get('date', datetime.date.today().strftime('%Y-%m-%d'))
    sel_date = _parse_date(date_str)

    updated_count = 0
    to_update     = []
    to_create     = []

    keys = set()
    for key in request.POST:
        if key.startswith('qty_'):
            parts = key[4:].split('_')
            if len(parts) == 2:
                keys.add((parts[0], parts[1]))

    customers_map = {str(c.pk): c for c in Customer.objects.filter(pk__in=[k[0] for k in keys])}
    products_map  = {str(p.pk): p for p in MilkProduct.objects.filter(pk__in=[k[1] for k in keys])}
    existing_records = {
        (str(d.customer_id), str(d.product_id)): d
        for d in DailyDelivery.objects.filter(
            date=sel_date,
            customer_id__in=[k[0] for k in keys],
            product_id__in=[k[1] for k in keys]
        )
    }

    for cid, pid in keys:
        customer = customers_map.get(cid)
        product  = products_map.get(pid)
        if not customer or not product:
            continue

        del_key = f'delivered_{cid}_{pid}'
        qty_key = f'qty_{cid}_{pid}'
        rsn_key = f'reason_{cid}_{pid}'

        is_delivered = request.POST.get(del_key) in ('on', 'true', '1', 'yes')
        qty_raw      = request.POST.get(qty_key, '').strip()
        reason       = request.POST.get(rsn_key, '')

        qty   = Decimal(qty_raw) if qty_raw else (customer.default_qty if is_delivered else Decimal('0'))
        qty   = max(Decimal('0.00'), qty)
        sub   = CustomerSubscription.objects.filter(
            customer=customer, product=product, is_active=True).first()
        price  = sub.custom_price if (sub and sub.custom_price) else product.default_price
        amount = (qty * price) if is_delivered else Decimal('0')

        existing = existing_records.get((cid, pid))
        if existing:
            existing.quantity              = qty
            existing.price_per_unit        = price
            existing.amount                = amount
            existing.is_delivered          = is_delivered
            existing.not_delivered_reason  = reason if not is_delivered else ""
            existing.recorded_by           = request.user
            to_update.append(existing)
        else:
            to_create.append(DailyDelivery(
                customer=customer, product=product, date=sel_date,
                quantity=qty, price_per_unit=price, amount=amount,
                is_delivered=is_delivered,
                not_delivered_reason=reason if not is_delivered else "",
                recorded_by=request.user,
            ))
        updated_count += 1

    if to_update:
        DailyDelivery.objects.bulk_update(to_update, [
            'quantity','price_per_unit','amount',
            'is_delivered','not_delivered_reason','recorded_by'
        ])
    if to_create:
        DailyDelivery.objects.bulk_create(to_create, ignore_conflicts=True)

    day_stats = DailyDelivery.objects.filter(
        date=sel_date, is_delivered=True
    ).aggregate(q=Sum('quantity'), r=Sum('amount'))

    messages.success(request,
        f"Updated {updated_count} items for {sel_date.strftime('%d %b %Y')}. "
        f"Total: {day_stats['q'] or 0:.1f}L | Revenue: 💸{day_stats['r'] or 0:,.2f}"
    )
    return redirect(f"/delivery/?date={date_str}")


@login_required
def delivery_quick_add(request):
    if request.method == 'POST':
        try:
            data     = json.loads(request.body)
            customer = get_object_or_404(Customer, pk=data['customer_id'])
            date     = _parse_date(data.get('date'))
            qty      = _dec(str(data.get('quantity', customer.default_qty)))
            price    = customer.price_per_unit
            obj, created = DailyDelivery.objects.update_or_create(
                customer=customer, date=date, product=customer.default_product,
                defaults={'quantity': qty, 'price_per_unit': price,
                          'is_delivered': data.get('is_delivered', True),
                          'recorded_by': request.user}
            )
            return JsonResponse({'success': True, 'amount': float(obj.amount), 'created': created})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False})


@login_required
def delivery_list(request):
    qs         = DailyDelivery.objects.select_related('customer','product').order_by('-date')
    date_from  = request.GET.get('from', '')
    date_to    = request.GET.get('to', '')
    customer_q = request.GET.get('customer', '')
    area_q     = request.GET.get('area', '')

    if date_from:  qs = qs.filter(date__gte=date_from)
    if date_to:    qs = qs.filter(date__lte=date_to)
    if customer_q: qs = qs.filter(
        Q(customer__name__icontains=customer_q) |
        Q(customer__customer_id__icontains=customer_q))
    if area_q:     qs = qs.filter(customer__area__iexact=area_q)

    totals    = qs.filter(is_delivered=True).aggregate(qty=Sum('quantity'), rev=Sum('amount'))
    area_choices = (Customer.objects
                    .exclude(area__isnull=True)
                    .exclude(area__exact='')
                    .values_list('area', flat=True)
                    .distinct()
                    .order_by('area'))

    paginator = Paginator(qs, 25)
    page      = paginator.get_page(request.GET.get('page'))
    return render(request, 'delivery/delivery_list.html', {
        'page_obj':    page,
        'date_from':   date_from,
        'date_to':     date_to,
        'customer_q':  customer_q,
        'area_q':      area_q,
        'area_choices': area_choices,
        'totals':      totals,
    })


# ── TRIP-WISE DELIVERY ENTRY ──────────────────────────────────────────────────
@login_required
def trip_delivery_entry(request):
    """
    Delivery recording page filtered by DeliveryRoute (trip).
    Shows each customer in the route with their active subscriptions.
    Supports update_or_create so re-saving the same day is safe.
    """
    today  = datetime.date.today()
    routes = DeliveryRoute.objects.filter(is_active=True).prefetch_related('customers')

    sel_date  = _parse_date(request.GET.get('date', today.strftime('%Y-%m-%d')), today)
    sel_route = request.GET.get('route','').strip()
    route_obj = None
    trip_rows = []   # [{customer, entries:[{sub, existing, default_qty, delivered}]}]

    if sel_route:
        route_obj = get_object_or_404(DeliveryRoute, pk=sel_route, is_active=True)

        # All customers in this route, active only
        route_customers = (route_obj.customers
                           .filter(status='active')
                           .prefetch_related(
                               Prefetch('subscriptions',
                                        queryset=CustomerSubscription.objects
                                        .filter(is_active=True).select_related('product'))
                           ).order_by('name'))

        # Pre-fetch all deliveries for this date+route in one query
        existing_map = {
            (d.customer_id, d.product_id): d
            for d in DailyDelivery.objects.filter(
                date=sel_date,
                customer__in=route_customers
            ).select_related('customer','product')
        }

        for customer in route_customers:
            if not customer.should_deliver_on(sel_date):
                continue

            subs = list(customer.active_subscriptions)

            # Fallback to legacy single product
            if not subs and customer.default_product:
                class _FakeSub:
                    id = None
                fs = _FakeSub()
                fs.product  = customer.default_product
                fs.quantity = customer.default_qty
                fs.price    = customer.price_per_unit
                subs = [fs]

            entries = []
            for sub in subs:
                key      = (customer.id, sub.product.id)
                existing = existing_map.get(key)
                entries.append({
                    'sub':         sub,
                    'existing':    existing,
                    'default_qty': existing.quantity if existing else sub.quantity,
                    'delivered':   existing.is_delivered if existing else True,
                    'reason':      existing.not_delivered_reason if existing else '',
                })

            if entries:
                trip_rows.append({'customer': customer, 'entries': entries})

    # ── POST: save deliveries ────────────────────────────────────────────────
    if request.method == 'POST' and request.POST.get('route_id'):
        post_route = get_object_or_404(DeliveryRoute, pk=request.POST['route_id'], is_active=True)
        post_date  = _parse_date(request.POST.get('date'), today)

        to_update = []
        to_create = []

        # Collect keys from POST: qty_CUSTID_PRODID
        keys = set()
        for k in request.POST:
            if k.startswith('qty_'):
                parts = k[4:].split('_')
                if len(parts) == 2:
                    keys.add((parts[0], parts[1]))

        customers_map = {str(c.pk): c for c in Customer.objects.filter(pk__in=[k[0] for k in keys])}
        products_map  = {str(p.pk): p for p in MilkProduct.objects.filter(pk__in=[k[1] for k in keys])}
        existing_recs = {
            (str(d.customer_id), str(d.product_id)): d
            for d in DailyDelivery.objects.filter(
                date=post_date,
                customer_id__in=[k[0] for k in keys],
                product_id__in=[k[1] for k in keys]
            )
        }

        saved = 0
        for cid, pid in keys:
            customer = customers_map.get(cid)
            product  = products_map.get(pid)
            if not customer or not product:
                continue

            is_delivered = request.POST.get(f'delivered_{cid}_{pid}') in ('on','true','1','yes')
            qty_raw      = request.POST.get(f'qty_{cid}_{pid}', '').strip()
            reason       = request.POST.get(f'reason_{cid}_{pid}', '')

            qty   = _dec(qty_raw, str(customer.default_qty)) if qty_raw else customer.default_qty
            qty   = max(Decimal('0.00'), qty)
            sub   = CustomerSubscription.objects.filter(
                customer=customer, product=product, is_active=True).first()
            price  = sub.custom_price if (sub and sub.custom_price) else product.default_price
            amount = (qty * price) if is_delivered else Decimal('0.00')

            existing = existing_recs.get((cid, pid))
            if existing:
                existing.route                 = post_route
                existing.quantity              = qty
                existing.price_per_unit        = price
                existing.amount                = amount
                existing.is_delivered          = is_delivered
                existing.not_delivered_reason  = reason if not is_delivered else ''
                existing.recorded_by           = request.user
                to_update.append(existing)
            else:
                to_create.append(DailyDelivery(
                    customer=customer, product=product,
                    route=post_route, date=post_date,
                    quantity=qty, price_per_unit=price, amount=amount,
                    is_delivered=is_delivered,
                    not_delivered_reason=reason if not is_delivered else '',
                    recorded_by=request.user,
                ))
            saved += 1

        if to_update:
            DailyDelivery.objects.bulk_update(to_update, [
                'route','quantity','price_per_unit','amount',
                'is_delivered','not_delivered_reason','recorded_by'
            ])
        if to_create:
            DailyDelivery.objects.bulk_create(to_create, ignore_conflicts=True)

        messages.success(request,
            f"✅ {saved} delivery record(s) saved for {post_route.name} "
            f"on {post_date.strftime('%d %b %Y')}.")
        return redirect(
            f"{request.path}?route={post_route.pk}&date={post_date.strftime('%Y-%m-%d')}"
        )

    context = {
        'routes':     routes,
        'route_obj':  route_obj,
        'sel_date':   sel_date,
        'trip_rows':  trip_rows,
        'today':      today,
        'yesterday':  (sel_date - datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
        'tomorrow':   (sel_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
        'area_choices': Customer.AREA_CHOICES,
    }
    return render(request, 'delivery/trip_delivery_entry.html', context)


# ── TRIP SUMMARY REPORT ───────────────────────────────────────────────────────
@login_required
def trip_summary(request):
    """
    Report page: for a given date + route shows each customer's
    products/quantities and route-level product totals at the bottom.
    """
    today  = datetime.date.today()
    routes = DeliveryRoute.objects.filter(is_active=True)

    sel_date  = _parse_date(request.GET.get('date', today.strftime('%Y-%m-%d')), today)
    sel_route = request.GET.get('route','').strip()
    route_obj = None

    trip_customers     = []
    product_totals     = {}   # {product_name: {qty, amount, unit}}
    grand_total_qty    = Decimal('00.00')
    grand_total_amount = Decimal('0.00')
    not_delivered_count = 0

    if sel_route:
        route_obj = get_object_or_404(DeliveryRoute, pk=sel_route, is_active=True)

        deliveries = (DailyDelivery.objects
                      .filter(route=route_obj, date=sel_date)
                      .select_related('customer','product')
                      .order_by('customer__name','product__name'))

        # Group by customer
        customer_map = {}
        for d in deliveries:
            cid = d.customer_id
            if cid not in customer_map:
                customer_map[cid] = {
                    'customer':      d.customer,
                    'deliveries':    [],
                    'total_qty':     Decimal('0'),
                    'total_amount':  Decimal('0'),
                    'not_delivered': 0,
                }
            customer_map[cid]['deliveries'].append(d)

            if d.is_delivered:
                customer_map[cid]['total_qty']    += d.quantity
                customer_map[cid]['total_amount'] += d.amount
                grand_total_qty    += d.quantity
                grand_total_amount += d.amount

                # Per-product totals across whole route
                pname = d.product.name if d.product else 'Unknown'
                unit  = d.product.unit if d.product else ''
                if pname not in product_totals:
                    product_totals[pname] = {'qty': Decimal('0'), 'amount': Decimal('0'), 'unit': unit}
                product_totals[pname]['qty']    += d.quantity
                product_totals[pname]['amount'] += d.amount
            else:
                customer_map[cid]['not_delivered'] += 1
                not_delivered_count += 1

        trip_customers = list(customer_map.values())

    context = {
        'routes':               routes,
        'route_obj':            route_obj,
        'sel_date':             sel_date,
        'trip_customers':       trip_customers,
        'product_totals':       product_totals,
        'grand_total_qty':      grand_total_qty,
        'grand_total_amount':   grand_total_amount,
        'not_delivered_count':  not_delivered_count,
        'customer_count':       len(trip_customers),
        'today':                today,
        'yesterday':            (sel_date - datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
        'tomorrow':             (sel_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
    }
    return render(request, 'delivery/trip_summary.html', context)


# ── BILLING ───────────────────────────────────────────────────────────────────
@login_required
def bill_list(request):
    # REMOVED customer__area from here because it's a standard text field
    bills  = Bill.objects.select_related('customer').order_by('-year', '-month', 'customer__name')
    
    status = request.GET.get('status', '')
    q      = request.GET.get('q', '')
    month  = request.GET.get('month', '')
    year   = request.GET.get('year', '')
    area   = request.GET.get('area', '') # Capture selected area text

    # Apply filters
    if status: 
        bills = bills.filter(status=status)
    if q:      
        bills = bills.filter(
            Q(customer__name__icontains=q) | 
            Q(bill_number__icontains=q) |
            Q(customer__customer_id__icontains=q)
        )
    if month and month.isdigit(): 
        bills = bills.filter(month=int(month))
    if year  and year.isdigit():  
        bills = bills.filter(year=int(year))
    if area:                      
        bills = bills.filter(customer__area=area) # Filter directly by text match

    # Pagination setup
    paginator   = Paginator(bills, 20)
    page_obj    = paginator.get_page(request.GET.get('page'))

    # Recalculate/Sync data
    for b in page_obj:
        fresh = (b.total_amount - b.discount) + b.previous_balance
        if b.grand_total != fresh:
            Bill.objects.filter(pk=b.pk).update(grand_total=fresh)
            b.grand_total = fresh

    # Totals computation
    total_receivable = bills.filter(status__in=['unpaid', 'partial']).aggregate(
        res=Sum('grand_total')
    )['res'] or 0

    # Dynamically extract all distinct, non-empty areas from your existing Customer directory
    areas = Customer.objects.exclude(area__isnull=True).exclude(area='').values_list('area', flat=True).distinct().order_by('area')

    return render(request, 'delivery/bill_list.html', {
        'page_obj': page_obj, 
        'status': status, 
        'q': q, 
        'month': month, 
        'year': year,
        'area': area,      # Pass active area string back to keep form sticky
        'areas': areas,    # Pass plain list of strings ['Area 1', 'Area 2', ...]
        'total_receivable': total_receivable,
        'months': [(i, datetime.date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
        'today': datetime.date.today(),
    })


@login_required
def bill_generate(request):
    customers = Customer.objects.filter(status='active').order_by('name')
    today     = datetime.date.today()

    if request.method == 'POST':
        cust_ids     = request.POST.getlist('customers')
        month        = int(request.POST.get('month', today.month))
        year         = int(request.POST.get('year',  today.year))
        discount_pct = _dec(request.POST.get('discount_pct','0'))

        from_date = datetime.date(year, month, 1)
        to_date   = datetime.date(year, month, calendar.monthrange(year, month)[1])

        if not cust_ids:
            messages.warning(request, 'Select at least one customer.')
            return redirect('bill_generate')

        generated = updated_existing = skipped = 0

        for cid in cust_ids:
            customer = get_object_or_404(Customer, pk=cid)
            deliveries   = DailyDelivery.objects.filter(
                customer=customer, date__gte=from_date, date__lte=to_date, is_delivered=True)
            total_qty    = deliveries.aggregate(q=Sum('quantity'))['q'] or Decimal('0')
            total_amount = deliveries.aggregate(a=Sum('amount'))['a']   or Decimal('0')

            if total_qty == 0:
                skipped += 1
                continue

            last_bill = Bill.objects.filter(
                customer=customer, to_date__lt=from_date).order_by('-to_date').first()

            prev_balance = Decimal('0')
            if last_bill:
                last_paid    = Payment.objects.filter(bill=last_bill).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                prev_balance = last_bill.grand_total - last_paid
                extra = Payment.objects.filter(
                    customer=customer, bill__isnull=True,
                    payment_date__gt=last_bill.generated_at.date(),
                    payment_date__lt=from_date
                ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                prev_balance -= extra
            else:
                old_unlinked = Payment.objects.filter(
                    customer=customer, bill__isnull=True,
                    payment_date__lt=from_date
                ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                prev_balance = -old_unlinked

            discount      = (total_amount * discount_pct / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            existing_bill = Bill.objects.filter(customer=customer, month=month, year=year).first()

            bill, created = Bill.objects.update_or_create(
                customer=customer, month=month, year=year,
                defaults={
                    'from_date': from_date, 'to_date': to_date,
                    'total_quantity': total_qty, 'total_amount': total_amount,
                    'discount': discount, 'previous_balance': prev_balance,
                    'generated_by': request.user,
                    'status': existing_bill.status if existing_bill else 'unpaid',
                }
            )
            paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')
            new_status = ('paid' if bill.grand_total <= 0 else
                          'paid' if paid >= bill.grand_total else
                          'partial' if paid > 0 else 'unpaid')
            Bill.objects.filter(pk=bill.pk).update(status=new_status)
            generated += 1 if created else 0
            updated_existing += 0 if created else 1

        messages.success(request,
            f"{from_date.strftime('%B %Y')}: {generated} generated, "
            f"{updated_existing} updated, {skipped} skipped.")
        return redirect('bill_list')

    sel_month    = int(request.GET.get('month', today.month))
    sel_year     = int(request.GET.get('year',  today.year))
    existing_ids = set(Bill.objects.filter(month=sel_month, year=sel_year)
                       .values_list('customer_id', flat=True))

    return render(request, 'delivery/bill_generate.html', {
        'customers': customers, 'today': today,
        'months': [(i, datetime.date(2000,i,1).strftime('%B')) for i in range(1,13)],
        'existing_bill_cust_ids': existing_ids,
        'sel_month': sel_month, 'sel_year': sel_year,
    })


@login_required
def bill_detail(request, pk):
    bill       = get_object_or_404(Bill, pk=pk)
    deliveries = DailyDelivery.objects.filter(
        customer=bill.customer, date__gte=bill.from_date,
        date__lte=bill.to_date, is_delivered=True
    ).order_by('date').select_related('product')
    payments   = Payment.objects.filter(bill=bill).order_by('-payment_date')

    current_stats       = deliveries.aggregate(actual_qty=Sum('quantity'), actual_amt=Sum('amount'))
    amount_paid         = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    actual_grand_total  = (current_stats['actual_amt'] or Decimal('0')) - bill.discount + bill.previous_balance

    if bill.grand_total != actual_grand_total:
        Bill.objects.filter(pk=bill.pk).update(
            total_quantity=current_stats['actual_qty'] or Decimal('0'),
            total_amount=current_stats['actual_amt'] or Decimal('0'),
            grand_total=actual_grand_total)
        bill.grand_total = actual_grand_total

    amount_due      = max(Decimal('0.00'), bill.grand_total - amount_paid)
    expected_status = ('paid' if bill.grand_total <= 0 else
                       'paid' if amount_paid >= bill.grand_total else
                       'partial' if amount_paid > 0 else 'unpaid')
    if bill.status != expected_status:
        Bill.objects.filter(pk=bill.pk).update(status=expected_status)
        bill.status = expected_status

    return render(request, 'delivery/bill_detail.html', {
        'bill': bill, 'deliveries': deliveries, 'payments': payments,
        'amount_paid': amount_paid, 'amount_due': amount_due,
    })


@login_required
def bill_edit(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    if request.method == 'POST':
        p = request.POST
        bill.discount          = _dec(p.get('discount','0'))
        bill.previous_balance  = _dec(p.get('previous_balance','0'))
        bill.notes             = p.get('notes','')
        bill.status            = p.get('status', bill.status)
        bill.grand_total       = (bill.total_amount - bill.discount) + bill.previous_balance
        bill.save()

        paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')
        new_status = ('paid' if bill.grand_total <= 0 else
                      'paid' if paid >= bill.grand_total else
                      'partial' if paid > 0 else 'unpaid')
        Bill.objects.filter(pk=bill.pk).update(status=new_status, grand_total=bill.grand_total)
        messages.success(request, f'Bill #{bill.bill_number} updated. Total: 💸{bill.grand_total:.2f}')
        return redirect('bill_detail', pk=pk)
    return render(request, 'delivery/bill_edit.html', {'bill': bill})


@login_required
def bill_delete(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    if request.method == 'POST':
        bill.payment_set.update(bill=None)
        no = bill.bill_number; cn = bill.customer.name
        bill.delete()
        messages.success(request, f'Bill #{no} for {cn} deleted.')
        return redirect('bill_list')
    return render(request, 'delivery/confirm_delete.html', {
        'object': bill, 'type': 'Bill',
        'warning': 'Linked payments will be unlinked (not deleted).',
    })


import datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Sum
from django.contrib.auth.decorators import login_required

# NOTE: _dec() is already defined near the top of this file (accepts
# value + optional default, returns Decimal). The old single-argument
# version that used to live here has been removed — it was silently
# overriding the correct one because it appeared later in the file,
# which is what caused "_dec() takes 1 positional argument but 2 were
# given" to keep happening even after the top-of-file fix.
#
# If any code below in this file relied on _dec() returning None on
# invalid input (e.g. to show "Please enter a valid amount"), check
# those call sites — the shared _dec() now returns the `default`
# (0 by default) instead of None on invalid input.

@login_required
def bill_mark_paid(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    
    if request.method == 'POST':
        p = request.POST
        raw_override = p.get('amount_override', '').strip()
        
        # Determine the target collection amount
        if raw_override:
            try:
                amt = Decimal(raw_override)
            except (InvalidOperation, ValueError, TypeError):
                messages.error(request, 'Please enter a valid numeric payment amount.')
                return redirect('bill_detail', pk=pk)
        else:
            amt = bill.amount_due

        # Validation check
        if amt <= 0:
            messages.warning(request, f'Cannot record a payment of ₹{amt}. Please enter an amount greater than zero.')
            return redirect('bill_detail', pk=pk)

        # Create Payment Record
        Payment.objects.create(
            customer=bill.customer, 
            bill=bill, 
            amount=amt,
            payment_method=p.get('method', 'cash'),
            reference_number=p.get('reference', ''),
            payment_date=datetime.date.today(),
            received_by=request.user,
        )

        # Recalculate Totals & Update Status
        paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        new_status = 'paid' if paid >= bill.grand_total else 'partial'
        
        Bill.objects.filter(pk=bill.pk).update(status=new_status)

        messages.success(request, f'Payment of ₹{amt} recorded for Bill #{bill.bill_number}')

    return redirect('bill_detail', pk=pk)


def _register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('Poppins',         '/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf'))
        pdfmetrics.registerFont(TTFont('Poppins-Bold',    '/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('Poppins-Medium',  '/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf'))
        pdfmetrics.registerFont(TTFont('Poppins-Light',   '/usr/share/fonts/truetype/google-fonts/Poppins-Light.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu',          '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold',     '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVuMono',      '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVuMono-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'))
        return True
    except Exception:
        return False   # fall back to Helvetica gracefully
 
_FONTS_OK = _register_fonts()
 
 
def _pf(poppins_name, fallback_name):
    return poppins_name if _FONTS_OK else fallback_name
 
 
# ── Colour Palette — warm cream + deep teal dairy theme ───────────────────────
C_CREAM      = colors.HexColor('#FFFBF2')
C_TEAL_DARK  = colors.HexColor('#0F4C5C')
C_TEAL       = colors.HexColor("#0180B1")
C_TEAL_LIGHT = colors.HexColor('#E8F5F7')
C_GOLD       = colors.HexColor('#D4A017')
C_GOLD_LIGHT = colors.HexColor('#FFF8E7')
C_WHITE      = colors.HexColor('#FFFFFF')
C_TEXT       = colors.HexColor('#1C2B2D')
C_TEXT_MED   = colors.HexColor('#3D5A5E')
C_MUTED      = colors.HexColor('#7A9EA3')
C_BORDER     = colors.HexColor('#C8DDE0')
C_STRIPE     = colors.HexColor('#F4FAFB')
C_GREEN      = colors.HexColor('#1A7A4A')
C_ORANGE     = colors.HexColor('#C45900')
C_ORANGE_BG  = colors.HexColor('#FFF3EA')
 
 
class MilkDivider(Flowable):
    """Decorative divider with a small circle in the centre."""
    def __init__(self, width, color=C_BORDER):
        super().__init__()
        self.width = width
        self.height = 10
        self._color = color
 
    def draw(self):
        c = self.canv
        mid = self.width / 2
        c.setStrokeColor(self._color)
        c.setFillColor(self._color)
        c.setLineWidth(0.5)
        c.line(0, 4, mid - 18, 4)
        c.line(mid + 18, 4, self.width, 4)
        c.circle(mid, 4, 5, fill=1, stroke=0)
        c.setFillColor(C_CREAM)
        c.circle(mid, 4, 2.5, fill=1, stroke=0)
 
 
def _s(name, font='Poppins', size=9, color=C_TEXT, bold=False,
        align=0, leading=None, space_after=0):
    fn = _pf(font + ('-Bold' if bold else ''), 'Helvetica' + ('-Bold' if bold else ''))
    ss = getSampleStyleSheet()
    return ParagraphStyle(name, parent=ss['Normal'],
                          fontName=fn, fontSize=size, textColor=color,
                          alignment=align, leading=leading or size * 1.4,
                          spaceAfter=space_after)
 
 
def _draw_bg(canvas_obj, doc):
    canvas_obj.saveState()
    canvas_obj.setFillColor(C_CREAM)
    canvas_obj.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas_obj.setFillColor(colors.HexColor('#DCF0F4'))
    canvas_obj.rect(0, 0, 0.3 * cm, A4[1], fill=1, stroke=0)
    canvas_obj.rect(A4[0] - 0.3 * cm, 0, 0.3 * cm, A4[1], fill=1, stroke=0)
    canvas_obj.restoreState()
 
 
@login_required
def bill_pdf(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
 
    # ── Recalculate totals live from delivery records ────────────────
    deliveries = DailyDelivery.objects.filter(
        customer=bill.customer,
        date__gte=bill.from_date,
        date__lte=bill.to_date,
        is_delivered=True,
    ).order_by('date').select_related('product')
 
    stats = deliveries.aggregate(actual_qty=Sum('quantity'), actual_amt=Sum('amount'))
    actual_total = stats['actual_amt'] or Decimal('0')
    net_amount   = actual_total - bill.discount
    grand_total  = net_amount + bill.previous_balance
 
    # Sync stale bill record back to DB
    if bill.grand_total != grand_total or bill.total_amount != actual_total:
        Bill.objects.filter(pk=bill.pk).update(
            total_amount=actual_total,
            total_quantity=stats['actual_qty'] or Decimal('0'),
            grand_total=grand_total,
        )
        bill.total_amount = actual_total
        bill.grand_total  = grand_total

    # ── FIXED: Calculate ALL payments (linked to this bill OR during bill period) ──
    linked_paid = (Payment.objects.filter(bill=bill)
                   .aggregate(t=Sum('amount'))['t'] or Decimal('0'))

    unlinked_paid = (Payment.objects.filter(
                        customer=bill.customer, 
                        bill__isnull=True,
                        payment_date__gte=bill.from_date,
                        payment_date__lte=bill.to_date,
                     ).aggregate(t=Sum('amount'))['t'] or Decimal('0'))

    amount_paid = linked_paid + unlinked_paid
    amount_due  = max(Decimal('0.00'), grand_total - amount_paid)

    # ── FIXED: Compute actual status dynamically based on total payments ──
    if grand_total <= 0 or amount_paid >= grand_total:
        actual_status = 'paid'
    elif amount_paid > 0:
        actual_status = 'partial'
    else:
        actual_status = 'unpaid'

    # Sync status back to database if it changed
    if bill.status != actual_status:
        Bill.objects.filter(pk=bill.pk).update(status=actual_status)
        bill.status = actual_status
 
    try:
        PAGE_W, PAGE_H = A4
        MARGIN    = 1.2 * cm
        CONTENT_W = PAGE_W - 2 * MARGIN
 
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=1.0 * cm, bottomMargin=1.0 * cm,
        )
 
        # ── Styles ────────────────────────────────────────────────────────────
        sty = {
            'brand'      : _s('brand',      'Poppins', 22, C_WHITE,     bold=True,  leading=26),
            'brand_tag'  : _s('brand_tag',  'Poppins',  8, C_TEAL_LIGHT,             leading=12),
            'inv_tag'    : _s('inv_tag',    'Poppins',  7, C_TEAL_LIGHT, align=2,   leading=10),
            'inv_no'     : _s('inv_no',     'Poppins', 18, C_WHITE,     bold=True,  leading=22, align=2),
            'inv_period' : _s('inv_period', 'Poppins',  8, C_TEAL_LIGHT, align=2,  leading=11),
            'sec_lbl'    : _s('sec_lbl',    'Poppins',  7, C_MUTED,     bold=True,  leading=10),
            'biz_name'   : _s('biz_name',   'Poppins', 10, C_TEAL_DARK, bold=True,  leading=14),
            'biz_det'    : _s('biz_det',    'Poppins',  8, C_TEXT_MED,               leading=13),
            'pay_lbl'    : _s('pay_lbl',    'Poppins',  7, C_MUTED,     bold=True,  leading=10),
            'pay_val'    : _s('pay_val',    'Poppins',  9, C_TEAL_DARK, bold=True,  leading=13),
            'cust_name'  : _s('cust_name',  'Poppins', 13, C_TEXT,      bold=True,  leading=17),
            'cust_det'   : _s('cust_det',   'Poppins',  8, C_TEXT_MED,               leading=13),
            'badge'      : _s('badge',      'Poppins',  7, C_WHITE,     bold=True,  leading=9, align=1),
            'th'         : _s('th',         'Poppins',  8, C_WHITE,     bold=True,  leading=11),
            'th_r'       : _s('th_r',       'Poppins',  8, C_WHITE,     bold=True,  leading=11, align=2),
            'td'         : _s('td',         'Poppins',  8, C_TEXT,                   leading=12),
            'td_r'       : _s('td_r',       'Poppins',  8, C_TEXT,                   leading=12, align=2),
            'td_mono_r'  : _s('tdmr',       'DejaVuMono', 8, C_TEXT,                 leading=12, align=2),
            'sum_lbl'    : _s('sum_lbl',    'Poppins',  7, C_MUTED,     bold=True,  leading=10, align=1),
            'sum_val'    : _s('sum_val',    'DejaVu',  12, C_TEXT,                   leading=16, align=1),
            'sum_val_b'  : _s('sum_val_b',  'DejaVu-Bold', 13, C_TEAL_DARK,         leading=16, align=1),
            'due_lbl'    : _s('due_lbl',    'Poppins',  7, C_ORANGE,    bold=True,  leading=10, align=1),
            'due_val'    : _s('due_val',    'DejaVu-Bold', 16, C_ORANGE,             leading=20, align=1),
            'paid_val'   : _s('paid_val',   'DejaVu-Bold', 13, C_GREEN,             leading=16, align=1),
            'footer'     : _s('footer',     'Poppins',  7, C_MUTED,                 leading=11, align=1),
            'footer_b'   : _s('footer_b',   'Poppins',  7, C_TEAL_DARK, bold=True,  leading=11, align=1),
            'gnote'      : _s('gnote',      'Poppins',  7, C_MUTED,                 leading=11, align=2),
        }
 
        story = []
        Rs = '\u20b9'

        # ── 1. HEADER ─────────────────────────────────────────────────────────
        month_label = bill.from_date.strftime('%B %Y')
        date_range  = (f"{bill.from_date.strftime('%d %b')} \u2013 "
                       f"{bill.to_date.strftime('%d %b %Y')}")
 
        hdr_data = [[
            [Paragraph('Milky Way Dairy', sty['brand']), Spacer(1, 3),
             Paragraph('Fresh from farm to your door every morning', sty['brand_tag'])],
            [Paragraph('INVOICE', sty['inv_tag']),
             Paragraph(f'# {bill.bill_number}', sty['inv_no']),
             Paragraph(f'{month_label}  \u2022  {date_range}', sty['inv_period'])],
        ]]
        ht = Table(hdr_data, colWidths=[CONTENT_W * 0.58, CONTENT_W * 0.42])
        ht.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), C_TEAL_DARK),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING',   (0,0), (0,0),   18),
            ('RIGHTPADDING',  (1,0), (1,0),   18),
            ('TOPPADDING',    (0,0), (-1,-1), 18),
            ('BOTTOMPADDING', (0,0), (-1,-1), 18),
            ('ROUNDEDCORNERS', [8,8,8,8]),
        ]))
        story.extend([ht, Spacer(1, 0.4*cm)])
 
        # ── 2. BUSINESS INFO + PAYMENT DETAILS ───────────────────────────────
        biz_col = [
            Paragraph('FROM', sty['sec_lbl']), Spacer(1, 3),
            Paragraph('Milky Way Dairy', sty['biz_name']),
            Paragraph('Venduvazhy Junction, Kothamangalam', sty['biz_det']),
            Paragraph('Ernakulam District, Kerala \u2014 686 691', sty['biz_det']),
        ]
        pay_inner = Table([
            [Paragraph('GPay / PhonePe', sty['pay_lbl'])],
            [Paragraph('9645311829', sty['pay_val'])],
            [Spacer(1,4)],
            [Paragraph('Account Name', sty['pay_lbl'])],
            [Paragraph('Adhil Najeeb', sty['pay_val'])],
            [Spacer(1,4)],
            [Paragraph('UPI ID', sty['pay_lbl'])],
            [Paragraph('adhilnajeeb469@okhdfcbank', sty['pay_val'])],
        ], colWidths=[CONTENT_W * 0.40],
           style=TableStyle([
               ('LEFTPADDING',   (0,0),(-1,-1), 12),
               ('RIGHTPADDING',  (0,0),(-1,-1), 12),
               ('TOPPADDING',    (0,0),(-1,-1), 1),
               ('BOTTOMPADDING', (0,0),(-1,-1), 1),
               ('BACKGROUND',    (0,0),(-1,-1), C_GOLD_LIGHT),
               ('LINELEFT',      (0,0),(-1,-1), 2, C_GOLD),
               ('TOPPADDING',    (0,0),(-1,0),  10),
               ('BOTTOMPADDING', (0,-1),(-1,-1),10),
           ]))
        pay_col = [Paragraph('PAYMENT DETAILS', sty['sec_lbl']), Spacer(1,4), pay_inner]
 
        info_tab = Table([[biz_col, pay_col]], colWidths=[CONTENT_W*0.52, CONTENT_W*0.48])
        info_tab.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
            ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),
        ]))
        story.extend([info_tab, Spacer(1,0.4*cm), MilkDivider(CONTENT_W), Spacer(1,0.4*cm)])
 
        # ── 3. CUSTOMER CARD ──────────────────────────────────────────────────
        st = bill.status
        badge_bg  = C_GREEN if st=='paid' else (colors.HexColor('#1A5C8A') if st=='partial' else C_ORANGE)
        badge_txt = bill.get_status_display().upper()
        pill = Table([[Paragraph(badge_txt, sty['badge'])]],
                     colWidths=[2.8*cm],
                     style=TableStyle([
                         ('BACKGROUND',(0,0),(-1,-1),badge_bg),
                         ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
                         ('ROUNDEDCORNERS',[5,5,5,5]),
                     ]))
        cust_left = [
            Paragraph('BILLED TO', sty['sec_lbl']), Spacer(1,4),
            Paragraph(bill.customer.name, sty['cust_name']),
            Paragraph(f'Mob: {bill.customer.phone}', sty['cust_det']),
            Paragraph(bill.customer.address[:100], sty['cust_det']),
        ]
        cust_right = [
            Paragraph('STATUS', sty['sec_lbl']), Spacer(1,6), pill, Spacer(1,8),
            Paragraph('BILL DATE', sty['sec_lbl']),
            Paragraph(datetime.date.today().strftime('%d %B %Y'), sty['cust_det']),
        ]
        ct = Table([[cust_left, cust_right]], colWidths=[CONTENT_W*0.65, CONTENT_W*0.35])
        ct.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),C_TEAL_LIGHT),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),14),('RIGHTPADDING',(0,0),(-1,-1),14),
            ('TOPPADDING',(0,0),(-1,-1),14),('BOTTOMPADDING',(0,0),(-1,-1),14),
            ('LINELEFT',(0,0),(0,-1),3,C_TEAL),
            ('ROUNDEDCORNERS',[6,6,6,6]),
        ]))
        story.extend([ct, Spacer(1,0.55*cm)])
 
        # ── 4. DELIVERY LOG ───────────────────────────────────────────────────
        story.append(Paragraph('DELIVERY LOG', sty['sec_lbl']))
        story.append(Spacer(1,4))
 
        COL = [2.5*cm, 1.6*cm, 6.8*cm, 2.3*cm, 2.5*cm, 3.0*cm]
        tbl_rows = [[
            Paragraph('DATE',    sty['th']), Paragraph('DAY',     sty['th']),
            Paragraph('PRODUCT', sty['th']), Paragraph('QTY',     sty['th_r']),
            Paragraph('RATE',    sty['th_r']),Paragraph('AMOUNT', sty['th_r']),
        ]]
        for i, d in enumerate(deliveries):
            pname = d.product.name if d.product else 'Dairy Product'
            tbl_rows.append([
                Paragraph(d.date.strftime('%d %b %Y'), sty['td']),
                Paragraph(d.date.strftime('%a'),        sty['td']),
                Paragraph(pname,                        sty['td']),
                Paragraph(f'{d.quantity} L',            sty['td_r']),
                Paragraph(f'{d.price_per_unit:.2f}',sty['td_mono_r']),
                Paragraph(f'{d.amount:.2f}',        sty['td_mono_r']),
            ])
 
        row_styles = [
            ('BACKGROUND',(0,0),(-1,0),C_TEAL),
            ('TOPPADDING',(0,0),(-1,0),8),('BOTTOMPADDING',(0,0),(-1,0),8),
            ('TOPPADDING',(0,1),(-1,-1),5),('BOTTOMPADDING',(0,1),(-1,-1),5),
            ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LINEBELOW',(0,0),(-1,-1),0.3,C_BORDER),
            ('ROUNDEDCORNERS',[5,5,5,5]),
        ]
        for i in range(1, len(tbl_rows)):
            row_styles.append(('BACKGROUND',(0,i),(-1,i), C_WHITE if i%2==1 else C_STRIPE))
        dt = Table(tbl_rows, colWidths=COL, repeatRows=1)
        dt.setStyle(TableStyle(row_styles))
        story.extend([dt, Spacer(1,0.6*cm)])
 
        # ── 5. SUMMARY CARDS ──────────────────────────────────────────────────
        CARD_W = CONTENT_W / 4
        sum_data = [
            [Paragraph('MONTH TOTAL',  sty['sum_lbl']), 
             Paragraph('PREV BALANCE', sty['sum_lbl']),
             Paragraph('AMOUNT PAID',  sty['sum_lbl']),
             Paragraph('AMOUNT DUE',   sty['due_lbl'])],
            [Paragraph(f'{actual_total:.2f}', sty['sum_val_b']),
             Paragraph(f'{bill.previous_balance:.2f}',sty['sum_val']),
             Paragraph(f'{amount_paid:.2f}',  sty['paid_val']),
             Paragraph(f'{amount_due:.2f}',   sty['due_val'])],
        ]
        sc = Table(sum_data, colWidths=[CARD_W]*4)
        sc.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(2,-1),C_TEAL_LIGHT),
            ('BACKGROUND',(3,0),(3,-1),C_ORANGE_BG),
            ('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
            ('LINEAFTER',(0,0),(2,-1),0.5,C_BORDER),
            ('LINELEFT',(3,0),(3,-1),2,C_ORANGE),
            ('ROUNDEDCORNERS',[6,6,6,6]),
        ]))
        story.append(KeepTogether([sc]))
        story.append(Spacer(1,0.3*cm))
        story.extend([Spacer(1,0.5*cm), MilkDivider(CONTENT_W), Spacer(1,0.3*cm)])
 
        # ── 6. FOOTER ─────────────────────────────────────────────────────────
        ft = Table([[
            Paragraph('Thank you for choosing\nMilky Way Dairy!', sty['footer_b']),
            Paragraph('Pay via GPay / PhonePe\n9645311829', sty['footer_b']),
            Paragraph('Fresh milk delivered daily\nwith love and care', sty['footer']),
        ]], colWidths=[CONTENT_W/3]*3)
        ft.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
            ('LINEAFTER',(0,0),(1,-1),0.4,C_BORDER),
        ]))
        story.append(ft)
 
        doc.build(story, onFirstPage=_draw_bg, onLaterPages=_draw_bg)
        buf.seek(0)
 
        resp = HttpResponse(buf, content_type='application/pdf')
        resp['Content-Disposition'] = (
            f'inline; filename="MilkyWay_Invoice_{bill.bill_number}.pdf"'
        )
        return resp
 
    except Exception as e:
        return HttpResponse(f'PDF generation error: {e}', status=500)
    
@login_required
def bill_whatsapp(request, pk):
    bill  = get_object_or_404(Bill, pk=pk)
    phone = bill.customer.phone.replace('+','').replace(' ','').replace('-','')
    if not phone.startswith('91') and len(phone) == 10:
        phone = '91' + phone
    msg = (f"Dear {bill.customer.name},\n"
           f"Your Milky Way bill for {bill.from_date.strftime('%B %Y')}:\n"
           f"Bill No: {bill.bill_number}\n"
           f"Total: Rs.{bill.net_amount}\nPrev Balance: Rs.{bill.previous_balance}\n"
           f"Grand Total: Rs.{bill.grand_total}\nStatus: {bill.get_status_display()}\n"
           f"Thank you!")
    return redirect(f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}")


@login_required
def api_bill_status(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    return JsonResponse({
        'bill_number': bill.bill_number, 'grand_total': float(bill.grand_total),
        'amount_paid': float(paid),
        'amount_due':  float(max(Decimal('0.00'), bill.grand_total - paid)),
        'status': bill.status
    })


# ── PAYMENTS ──────────────────────────────────────────────────────────────────
@login_required
def payment_add(request, customer_pk=None):
    customers    = Customer.objects.filter(status='active').order_by('name')
    customer     = get_object_or_404(Customer, pk=customer_pk) if customer_pk else None
    unpaid_bills = (Bill.objects.filter(customer=customer, status__in=['unpaid','partial'])
                    if customer else [])
    if request.method == 'POST':
        p    = request.POST
        cust = get_object_or_404(Customer, pk=p.get('customer'))
        amt  = _dec(p.get('amount','0'))
        if amt <= 0:
            messages.error(request, 'Amount must be greater than zero.')
            return redirect(request.path)
        pmt = Payment.objects.create(
            customer=cust, amount=amt,
            payment_method=p.get('payment_method','cash'),
            reference_number=p.get('reference_number',''),
            payment_date=_parse_date(p.get('payment_date')),
            notes=p.get('notes',''), received_by=request.user,
        )
        if p.get('bill_id'):
            try:
                b = Bill.objects.get(pk=p['bill_id'])
                pmt.bill = b; pmt.save()
                paid = Payment.objects.filter(bill=b).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                Bill.objects.filter(pk=b.pk).update(
                    status='paid' if paid >= b.grand_total else 'partial')
            except Bill.DoesNotExist:
                pass
        messages.success(request, f'Payment of 💸{pmt.amount} recorded for {cust.name}')
        return redirect('customer_detail', pk=cust.pk)
    return render(request, 'delivery/payment_form.html', {
        'customers': customers, 'customer': customer, 'unpaid_bills': unpaid_bills,
        'today': datetime.date.today(),
    })


@login_required
def payment_list(request):
    payments = Payment.objects.select_related('customer','bill').order_by('-payment_date')
    q = request.GET.get('q',''); method = request.GET.get('method','')
    month = request.GET.get('month',''); year = request.GET.get('year','')
    if q:      payments = payments.filter(Q(customer__name__icontains=q)|Q(reference_number__icontains=q))
    if method: payments = payments.filter(payment_method=method)
    if month:  payments = payments.filter(payment_date__month=int(month))
    if year:   payments = payments.filter(payment_date__year=int(year))
    total     = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    paginator = Paginator(payments, 25)
    page      = paginator.get_page(request.GET.get('page'))
    return render(request, 'delivery/payment_list.html', {
        'page_obj': page, 'q': q, 'method': method, 'month': month, 'year': year,
        'total': total,
        'months': [(i, datetime.date(2000,i,1).strftime('%B')) for i in range(1,13)],
        'method_choices': Payment.METHOD_CHOICES,
        'today': datetime.date.today(),
    })


@login_required
def payment_delete(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if request.method == 'POST':
        bill = payment.bill; amt = payment.amount; cust = payment.customer.name
        payment.delete()
        if bill:
            paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')
            Bill.objects.filter(pk=bill.pk).update(
                status=('paid' if paid >= bill.grand_total and bill.grand_total > 0
                        else 'partial' if paid > 0 else 'unpaid'))
        messages.success(request, f'Payment of 💸{amt} from {cust} deleted.')
        return redirect('payment_list')
    return render(request, 'delivery/confirm_delete.html', {
        'object': payment, 'type': 'Payment',
        'warning': 'This will update the linked bill status.',
    })


# ── PRODUCTS ──────────────────────────────────────────────────────────────────
@login_required
def product_list(request):
    products = MilkProduct.objects.all()
    return render(request, 'delivery/product_list.html', {'products': products})


@login_required
def product_add(request):
    if request.method == 'POST':
        p = request.POST
        if not p.get('name','').strip():
            messages.error(request, 'Product name is required.')
        else:
            MilkProduct.objects.create(
                name=p['name'].strip(), unit=p.get('unit','L'),
                default_price=_dec(p.get('default_price','0')),
                description=p.get('description',''))
            messages.success(request, 'Product added!')
            return redirect('product_list')
    return render(request, 'delivery/product_form.html', {
        'unit_choices': MilkProduct.UNIT_CHOICES, 'action': 'Add'})


@login_required
def product_edit(request, pk):
    product = get_object_or_404(MilkProduct, pk=pk)
    if request.method == 'POST':
        p = request.POST
        product.name          = p.get('name','').strip()
        product.unit          = p.get('unit','L')
        product.default_price = _dec(p.get('default_price','0'))
        product.description   = p.get('description','')
        product.is_active     = p.get('is_active') == 'on'
        product.save()
        messages.success(request, 'Product updated!')
        return redirect('product_list')
    return render(request, 'delivery/product_form.html', {
        'product': product, 'unit_choices': MilkProduct.UNIT_CHOICES, 'action': 'Edit'})


# ── EXPENSES ──────────────────────────────────────────────────────────────────
@login_required
def expense_list(request):
    today  = datetime.date.today()
    month  = int(request.GET.get('month', today.month))
    year   = int(request.GET.get('year',  today.year))
    cat_id = request.GET.get('cat','')
    pay    = request.GET.get('pay','')
    q      = request.GET.get('q','')

    qs = Expense.objects.select_related('category').filter(date__month=month, date__year=year)
    if cat_id: qs = qs.filter(category_id=cat_id)
    if pay:    qs = qs.filter(payment_mode=pay)
    if q:      qs = qs.filter(Q(title__icontains=q)|Q(vendor__icontains=q)|Q(description__icontains=q))
    qs = qs.order_by('-date','-created_at')

    total_amount = qs.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    by_cat       = list(qs.values('category__name','category__icon')
                        .annotate(total=Sum('amount'), count=Count('id')).order_by('-total'))
    categories   = ExpenseCategory.objects.filter(is_active=True)
    paginator    = Paginator(qs, 20)
    page         = paginator.get_page(request.GET.get('page'))

    return render(request, 'delivery/expense_list.html', {
        'page_obj': page, 'total_amount': total_amount,
        'by_cat': by_cat, 'categories': categories,
        'month': month, 'year': year, 'cat_id': cat_id, 'pay_mode': pay, 'q': q,
        'months': [(i, datetime.date(2000,i,1).strftime('%B')) for i in range(1,13)],
        'pay_choices': Expense.PAYMENT_CHOICES,
        'today': today,
    })


@login_required
def expense_add(request):
    categories = ExpenseCategory.objects.filter(is_active=True)
    today      = datetime.date.today()
    if request.method == 'POST':
        p     = request.POST
        title = p.get('title','').strip()
        if not title:
            messages.error(request, 'Title is required.')
        else:
            try:
                exp = Expense(
                    title=title, amount=_dec(p.get('amount','0')),
                    date=_parse_date(p.get('date'), today),
                    payment_mode=p.get('payment_mode','cash'),
                    vendor=p.get('vendor','').strip(),
                    invoice_no=p.get('invoice_no','').strip(),
                    description=p.get('description','').strip(),
                    is_recurring=p.get('is_recurring') == 'on',
                    added_by=request.user,
                )
                cat_id = p.get('category','').strip()
                exp.category_id = int(cat_id) if cat_id else None
                if 'receipt' in request.FILES:
                    exp.receipt = request.FILES['receipt']
                exp.save()
                messages.success(request, f'Expense "{exp.title}" of 💸{exp.amount} added!')
                return redirect('expense_list')
            except Exception as e:
                messages.error(request, f'Error: {e}')
    return render(request, 'delivery/expense_form.html', {
        'categories': categories, 'pay_choices': Expense.PAYMENT_CHOICES,
        'action': 'Add', 'today': today,
    })


@login_required
def expense_edit(request, pk):
    expense    = get_object_or_404(Expense, pk=pk)
    categories = ExpenseCategory.objects.filter(is_active=True)
    if request.method == 'POST':
        p     = request.POST
        title = p.get('title','').strip()
        if not title:
            messages.error(request, 'Title is required.')
        else:
            try:
                expense.title        = title
                expense.amount       = _dec(p.get('amount','0'))
                expense.date         = _parse_date(p.get('date'), expense.date)
                expense.payment_mode = p.get('payment_mode','cash')
                expense.vendor       = p.get('vendor','').strip()
                expense.invoice_no   = p.get('invoice_no','').strip()
                expense.description  = p.get('description','').strip()
                expense.is_recurring = p.get('is_recurring') == 'on'
                cat_id = p.get('category','').strip()
                expense.category_id = int(cat_id) if cat_id else None
                if 'receipt' in request.FILES:
                    expense.receipt = request.FILES['receipt']
                expense.save()
                messages.success(request, 'Expense updated!')
                return redirect('expense_list')
            except Exception as e:
                messages.error(request, f'Error: {e}')
    return render(request, 'delivery/expense_form.html', {
        'expense': expense, 'categories': categories,
        'pay_choices': Expense.PAYMENT_CHOICES, 'action': 'Edit',
        'today': datetime.date.today(),
    })


@login_required
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == 'POST':
        title = expense.title; expense.delete()
        messages.success(request, f'Expense "{title}" deleted.')
        return redirect('expense_list')
    return render(request, 'delivery/confirm_delete.html', {'object': expense, 'type': 'Expense'})


@login_required
def expense_category_list(request):
    categories = ExpenseCategory.objects.annotate(exp_count=Count('expense'))
    if request.method == 'POST':
        p    = request.POST
        name = p.get('name','').strip()
        if name:
            ExpenseCategory.objects.create(
                name=name, icon=p.get('icon','other'), color=p.get('color','#6b7280'))
            messages.success(request, f'Category "{name}" added!')
        return redirect('expense_category_list')
    icon_choices = [
        ('feed','🌾 Feed/Fodder'),('medicine','💊 Medicine'),('electricity','⚡ Electricity'),
        ('travel','🚗 Travel'),('maintenance','🔧 Maintenance'),('labour','👷 Labour'),
        ('milk','🥛 Milk Purchase'),('vet','🏥 Veterinary'),('packaging','📦 Packaging'),
        ('testing','🧪 Testing'),('water','💧 Water'),('other','🌿 Other'),
    ]
    return render(request, 'delivery/expense_categories.html', {
        'categories': categories, 'icon_choices': icon_choices,
    })


# ── REPORTS ───────────────────────────────────────────────────────────────────
@login_required
def reports(request):
    today = datetime.date.today()
    month = int(request.GET.get('month', today.month))
    year  = int(request.GET.get('year',  today.year))

    raw_deliveries = (DailyDelivery.objects
                      .filter(date__month=month, date__year=year, is_delivered=True)
                      .values('customer__name','customer__customer_id','product__name')
                      .annotate(qty=Sum('quantity'), amount=Sum('amount'), avg_price=Avg('price_per_unit'))
                      .order_by('customer__name'))

    processed_summary = {}
    for item in raw_deliveries:
        name = item['customer__name']
        if name not in processed_summary:
            processed_summary[name] = {
                'name': name, 'customer_id': item['customer__customer_id'],
                'products': [], 'total_revenue': Decimal('0')
            }
        processed_summary[name]['products'].append(item)
        processed_summary[name]['total_revenue'] += item['amount']

    monthly_summary_list = sorted(processed_summary.values(),
                                   key=lambda x: x['total_revenue'], reverse=True)

    num_days  = calendar.monthrange(year, month)[1]
    all_dates = [datetime.date(year, month, day) for day in range(1, num_days+1)]

    delivery_map = {d['date']: d for d in
                    DailyDelivery.objects.filter(date__month=month, date__year=year, is_delivered=True)
                    .values('date').annotate(qty=Sum('quantity'), amount=Sum('amount'))}
    expense_map  = {e['date']: e for e in
                    Expense.objects.filter(date__month=month, date__year=year)
                    .values('date').annotate(total=Sum('amount'))}

    full_daily_totals = [{
        'date':    d,
        'qty':     delivery_map.get(d, {}).get('qty', 0),
        'amount':  delivery_map.get(d, {}).get('amount', 0),
        'expense': expense_map.get(d, {}).get('total', 0),
    } for d in all_dates]

    total_revenue = sum(item['amount']  for item in full_daily_totals)
    total_qty     = sum(item['qty']     for item in full_daily_totals)
    total_expense = sum(item['expense'] for item in full_daily_totals)

    monthly_expenses = (Expense.objects.filter(date__month=month, date__year=year)
                        .values('category__name','category__icon')
                        .annotate(total=Sum('amount')).order_by('-total'))

    return render(request, 'delivery/reports.html', {
        'monthly_summary': monthly_summary_list,
        'daily_totals':    full_daily_totals,
        'monthly_expenses': monthly_expenses,
        'total_qty': total_qty, 'total_revenue': total_revenue,
        'total_expense': total_expense,
        'net_profit': total_revenue - total_expense,
        'month': month, 'year': year,
        'months': [(i, datetime.date(2000,i,1).strftime('%B')) for i in range(1,13)],
        'today': today,
    })


# ── API ───────────────────────────────────────────────────────────────────────
@login_required
def api_customer_price(request, pk):
    c    = get_object_or_404(Customer, pk=pk)
    subs = [{'product': str(s.product), 'product_id': s.product.pk,
              'qty': float(s.quantity), 'price': float(s.price)}
             for s in c.active_subscriptions]
    return JsonResponse({
        'price': float(c.price_per_unit),
        'default_qty': float(c.default_qty),
        'subscriptions': subs
    })