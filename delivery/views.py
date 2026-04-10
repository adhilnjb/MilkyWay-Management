from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db.models import Sum, Count, Q, Prefetch
from django.core.paginator import Paginator
from decimal import Decimal, ROUND_HALF_UP
import datetime, json, calendar, io
from django.db.models import Sum, Count, Avg

from .models import (Customer, CustomerSubscription, DailyDelivery,
                     Bill, Payment, MilkProduct, Notification,
                     Expense, ExpenseCategory)


# ── helpers ──────────────────────────────────────────────────────────────────
def _dec(val, default='0'):
    try:
        v = Decimal(str(val).strip())
        return v if v >= 0 else Decimal(default)
    except Exception:
        return Decimal(default)


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
    today_qty         = today_deliveries.aggregate(q=Sum('quantity'))['q'] or Decimal('0')
    today_revenue     = today_deliveries.aggregate(r=Sum('amount'))['r']   or Decimal('0')

    month_deliveries  = DailyDelivery.objects.filter(date__month=month, date__year=year, is_delivered=True)
    month_qty         = month_deliveries.aggregate(q=Sum('quantity'))['q'] or Decimal('0')
    month_revenue     = month_deliveries.aggregate(r=Sum('amount'))['r']   or Decimal('0')

    pending_bills     = Bill.objects.filter(status__in=['unpaid','partial']).count()
    pending_amount    = Bill.objects.filter(status__in=['unpaid','partial']).aggregate(t=Sum('grand_total'))['t'] or Decimal('0')

    month_expenses    = Expense.objects.filter(date__month=month, date__year=year).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    # 7-day chart — single query, grouped by date
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

    area_data = Customer.objects.filter(status='active').values('area').annotate(c=Count('id'))

    # expense breakdown (this month)
    exp_by_cat = (Expense.objects
                  .filter(date__month=month, date__year=year)
                  .values('category__name')
                  .annotate(total=Sum('amount'))
                  .order_by('-total')[:5])

    recent_deliveries = DailyDelivery.objects.select_related('customer', 'product').order_by('created_at')[:10]
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
    qs       = Customer.objects.select_related('default_product').prefetch_related(
        Prefetch('subscriptions', queryset=CustomerSubscription.objects.filter(is_active=True).select_related('product'))
    )
    q        = request.GET.get('q','')
    status   = request.GET.get('status','')
    area     = request.GET.get('area','')
    schedule = request.GET.get('schedule','')

    if q:        qs = qs.filter(Q(name__icontains=q)|Q(phone__icontains=q)|Q(customer_id__icontains=q))
    if status:   qs = qs.filter(status=status)
    if area:     qs = qs.filter(area=area)
    if schedule: qs = qs.filter(delivery_schedule=schedule)

    all_c = Customer.objects.all()
    paginator = Paginator(qs.order_by('name'), 20)
    page = paginator.get_page(request.GET.get('page'))
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
        'status_choices': Customer.STATUS_CHOICES,
        'area_choices':   Customer.AREA_CHOICES,
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
        'status_choices': Customer.STATUS_CHOICES,
        'area_choices':   Customer.AREA_CHOICES,
        'schedule_choices': Customer.SCHEDULE_CHOICES,
        'existing_subs': existing_subs,
    })


def _create_or_update_customer(p, customer=None, user=None):
    if customer is None:
        customer = Customer()
        customer.created_by = user

    customer.name            = p.get('name','').strip()
    customer.phone           = p.get('phone','').strip()
    customer.alternate_phone = p.get('alternate_phone','').strip()
    customer.email           = p.get('email','').strip()
    customer.address         = p.get('address','').strip()
    customer.area            = p.get('area','central')
    customer.landmark        = p.get('landmark','').strip()
    customer.pincode         = p.get('pincode','').strip()
    customer.delivery_schedule = p.get('delivery_schedule','daily')
    customer.delivery_time   = p.get('delivery_time','06:00') or '06:00'
    customer.delivery_days   = p.get('delivery_days','1,2,3,4,5,6,7')
    customer.opening_balance = _dec(p.get('opening_balance','0'))
    customer.credit_limit    = _dec(p.get('credit_limit','5000'),'5000')
    customer.status          = p.get('status','active')
    customer.notes           = p.get('notes','').strip()
    customer.joining_date    = _parse_date(p.get('joining_date'))

    # legacy single product support
    prod_id = p.get('default_product','').strip()
    customer.default_product = MilkProduct.objects.filter(pk=prod_id).first() if prod_id else None
    customer.default_qty     = _dec(p.get('default_qty','1'), '1')
    cp = p.get('custom_price','').strip()
    customer.custom_price    = _dec(cp) if cp else None

    customer.save()
    return customer


def _save_subscriptions(customer, p):
    """Parse and save multi-product subscriptions from POST data."""
    # POST sends: sub_product_0, sub_qty_0, sub_price_0 ... for each row
    # Also accepts sub_product[], sub_qty[], sub_price[]
    prod_ids = p.getlist('sub_product')
    qtys     = p.getlist('sub_qty')
    prices   = p.getlist('sub_price')
    actives  = p.getlist('sub_active')  # checkboxes

    if not prod_ids:
        return  # no subscription data submitted

    # Deactivate all existing, then re-create
    customer.subscriptions.all().update(is_active=False)

    for i, pid in enumerate(prod_ids):
        pid = pid.strip()
        if not pid:
            continue
        try:
            product = MilkProduct.objects.get(pk=pid)
        except MilkProduct.DoesNotExist:
            continue

        qty   = _dec(qtys[i] if i < len(qtys) else '1', '1')
        price_raw = prices[i].strip() if i < len(prices) else ''
        price = _dec(price_raw) if price_raw else None
        is_active = True  # all submitted rows are active

        CustomerSubscription.objects.update_or_create(
            customer=customer, product=product,
            defaults={
                'quantity':    qty,
                'custom_price': price,
                'is_active':   is_active,
            }
        )


@login_required
def customer_detail(request, pk):
    customer    = get_object_or_404(Customer, pk=pk)
    today       = datetime.date.today()
    month, year = today.month, today.year
    subscriptions = customer.subscriptions.filter(is_active=True).select_related('product')
    deliveries  = DailyDelivery.objects.filter(customer=customer).select_related('product').order_by('-date')[:30]
    bills       = Bill.objects.filter(customer=customer).order_by('-year','-month')
    payments    = Payment.objects.filter(customer=customer).order_by('-payment_date')[:10]
    month_qs    = DailyDelivery.objects.filter(customer=customer, date__month=month, date__year=year, is_delivered=True)
    month_qty   = month_qs.aggregate(q=Sum('quantity'))['q'] or Decimal('0')
    month_amt   = month_qs.aggregate(a=Sum('amount'))['a']   or Decimal('0')
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
        name = customer.name; customer.delete()
        messages.success(request, f'Customer {name} deleted.')
        return redirect('customer_list')
    return render(request, 'delivery/confirm_delete.html', {'object': customer, 'type': 'Customer'})


# ── SUBSCRIPTIONS ─────────────────────────────────────────────────────────────
@login_required
def subscription_toggle(request, pk):
    """AJAX: toggle a subscription active/inactive"""
    sub = get_object_or_404(CustomerSubscription, pk=pk)
    if request.method == 'POST':
        sub.is_active = not sub.is_active
        sub.save()
        return JsonResponse({'success': True, 'is_active': sub.is_active})
    return JsonResponse({'success': False})


# ── DAILY DELIVERY ────────────────────────────────────────────────────────────
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

    customers = (Customer.objects.filter(status='active')
                 .select_related('default_product')
                 .prefetch_related(
                     Prefetch('subscriptions',
                              queryset=CustomerSubscription.objects.filter(is_active=True).select_related('product'))
                 ).order_by('area','name'))

    if filter_area:     customers = customers.filter(area=filter_area)
    if filter_search:   customers = customers.filter(Q(name__icontains=filter_search)|Q(phone__icontains=filter_search)|Q(customer_id__icontains=filter_search))
    if filter_schedule: customers = customers.filter(delivery_schedule=filter_schedule)

    # Map: (customer_id, product_id) -> DailyDelivery
    deliveries_map = {}
    for d in DailyDelivery.objects.filter(date=sel_date).select_related('customer','product'):
        deliveries_map[(d.customer_id, d.product_id)] = d

    rows = []
    for c in customers:
        scheduled = c.should_deliver_on(sel_date)
        subs = list(c.active_subscriptions)

        if not subs:
            # Fall back to legacy single product
            if c.default_product:
                class _FakeSub:
                    pass
                fs = _FakeSub()
                fs.id = None
                fs.product = c.default_product
                fs.quantity = c.default_qty
                fs.price = c.price_per_unit
                subs = [fs]

        sub_rows = []
        for sub in subs:
            key = (c.id, sub.product.id if sub.product else None)
            existing = deliveries_map.get(key)
            sub_rows.append({'sub': sub, 'delivery': existing})

        row = {'customer': c, 'scheduled': scheduled, 'sub_rows': sub_rows}
        if filter_status == 'delivered':
            if not any(sr['delivery'] and sr['delivery'].is_delivered for sr in sub_rows):
                continue
        elif filter_status == 'pending':
            if all(sr['delivery'] and sr['delivery'].is_delivered for sr in sub_rows):
                continue
        rows.append(row)

    total_delivered = sum(1 for r in rows if any(sr['delivery'] and sr['delivery'].is_delivered for sr in r['sub_rows']))
    total_qty       = sum(float(sr['delivery'].quantity) for r in rows for sr in r['sub_rows'] if sr['delivery'] and sr['delivery'].is_delivered)
    total_amount    = sum(float(sr['delivery'].amount)   for r in rows for sr in r['sub_rows'] if sr['delivery'] and sr['delivery'].is_delivered)
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
        'area_choices': Customer.AREA_CHOICES,
        'schedule_choices': Customer.SCHEDULE_CHOICES,
    })


@login_required
def delivery_bulk_update(request):
    if request.method != 'POST':
        return redirect('delivery_today')

    # 1. Parse Date
    date_str = request.POST.get('date', datetime.date.today().strftime('%Y-%m-%d'))
    sel_date = _parse_date(date_str) # Your helper to convert string to date object
    
    updated_count = 0
    to_update = []
    to_create = []

    # 2. Extract unique (Customer, Product) keys from POST data
    # We look for 'qty_CUSTID_PRODID' to identify which rows were submitted
    keys = set()
    for key in request.POST:
        if key.startswith('qty_'):
            parts = key[4:].split('_')
            if len(parts) == 2:
                keys.add((parts[0], parts[1]))

    # 3. Optimized Database Fetching
    # Load all relevant customers and products in one go to avoid N+1 queries
    customers_map = {str(c.pk): c for c in Customer.objects.filter(
        pk__in=[k[0] for k in keys]
    )}
    products_map = {str(p.pk): p for p in MilkProduct.objects.filter(
        pk__in=[k[1] for k in keys]
    )}
    
    # Map existing records for this specific date
    existing_records = {
        (str(d.customer_id), str(d.product_id)): d
        for d in DailyDelivery.objects.filter(
            date=sel_date,
            customer_id__in=[k[0] for k in keys],
            product_id__in=[k[1] for k in keys]
        )
    }

    # 4. Process each Item
    for cid, pid in keys:
        customer = customers_map.get(cid)
        product = products_map.get(pid)
        if not customer or not product:
            continue

        # Construct form keys
        del_key = f'delivered_{cid}_{pid}'
        qty_key = f'qty_{cid}_{pid}'
        rsn_key = f'reason_{cid}_{pid}'

        # Get values from POST
        is_delivered = request.POST.get(del_key) in ('on', 'true', '1', 'yes')
        qty_raw = request.POST.get(qty_key, '').strip()
        reason = request.POST.get(rsn_key, '')

        # Quantity Logic: Use input qty, or fallback to customer default if marking delivered
        qty = Decimal(qty_raw) if qty_raw else (customer.default_qty if is_delivered else Decimal('0'))
        qty = max(Decimal('0'), qty)

        # Price Logic: Priority to specific Subscription price, then Product default
        sub = CustomerSubscription.objects.filter(customer=customer, product=product, is_active=True).first()
        price = sub.custom_price if (sub and sub.custom_price) else product.default_price
        
        # Dashboard Fix: Amount must be calculated here because bulk_update skips save() signals
        amount = (qty * price) if is_delivered else Decimal('0')

        existing = existing_records.get((cid, pid))
        
        if existing:
            # Prepare for bulk_update
            existing.quantity = qty
            existing.price_per_unit = price
            existing.amount = amount
            existing.is_delivered = is_delivered
            existing.not_delivered_reason = reason if not is_delivered else ""
            existing.recorded_by = request.user
            to_update.append(existing)
        else:
            # Prepare for bulk_create
            to_create.append(DailyDelivery(
                customer=customer,
                product=product,
                date=sel_date,
                quantity=qty,
                price_per_unit=price,
                amount=amount,
                is_delivered=is_delivered,
                not_delivered_reason=reason if not is_delivered else "",
                recorded_by=request.user,
            ))
        updated_count += 1

    # 5. Database Execution
    if to_update:
        DailyDelivery.objects.bulk_update(to_update, [
            'quantity', 'price_per_unit', 'amount', 
            'is_delivered', 'not_delivered_reason', 'recorded_by'
        ])
    
    if to_create:
        DailyDelivery.objects.bulk_create(to_create, ignore_conflicts=True)

    # 6. Success Message with Fresh Totals
    # This ensures the user sees immediate confirmation of the revenue update
    day_stats = DailyDelivery.objects.filter(
        date=sel_date, 
        is_delivered=True
    ).aggregate(q=Sum('quantity'), r=Sum('amount'))
    
    messages.success(request, 
        f"Successfully updated {updated_count} items for {sel_date.strftime('%d %b %Y')}. "
        f"Total: {day_stats['q'] or 0:.1f}L | Revenue: ₹{day_stats['r'] or 0:,.2f}"
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
    qs        = DailyDelivery.objects.select_related('customer','product').order_by('-date')
    date_from = request.GET.get('from','')
    date_to   = request.GET.get('to','')
    customer_q= request.GET.get('customer','')
    if date_from:  qs = qs.filter(date__gte=date_from)
    if date_to:    qs = qs.filter(date__lte=date_to)
    if customer_q: qs = qs.filter(Q(customer__name__icontains=customer_q)|Q(customer__customer_id__icontains=customer_q))
    totals    = qs.filter(is_delivered=True).aggregate(qty=Sum('quantity'), rev=Sum('amount'))
    paginator = Paginator(qs, 25)
    page      = paginator.get_page(request.GET.get('page'))
    return render(request, 'delivery/delivery_list.html', {
        'page_obj': page, 'date_from': date_from, 'date_to': date_to,
        'customer_q': customer_q, 'totals': totals,
    })


# ── BILLING ───────────────────────────────────────────────────────────────────
from django.db.models import Q, Sum

from django.db.models import Q, Sum
from decimal import Decimal

@login_required
def bill_list(request):
    # 1. Base Query with optimization
    bills = Bill.objects.select_related('customer').order_by('-year', '-month', 'customer__name')
    
    # 2. Filtering Logic
    status = request.GET.get('status', '')
    q      = request.GET.get('q', '')
    month  = request.GET.get('month', '')
    year   = request.GET.get('year', '')
    
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
    if year and year.isdigit():   
        bills = bills.filter(year=int(year))

    # 3. Pagination Setup
    paginator = Paginator(bills, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # --- 4. THE AUTO-SYNC LOGIC ---
    # We update the grand_total for only the bills visible on the current page
    # This fixes the bug where grand_total doesn't reflect previous balance changes
    for b in page_obj:
        # Calculate what the total SHOULD be right now
        # Grand Total = (Monthly Amount - Discount) + Previous Balance
        fresh_grand_total = (b.total_amount - b.discount) + b.previous_balance
        
        # If the database value is different from the fresh calculation, update it
        if b.grand_total != fresh_grand_total:
            Bill.objects.filter(pk=b.pk).update(grand_total=fresh_grand_total)
            b.grand_total = fresh_grand_total # Update object in memory for the template

    # 5. Global Stats (Calculated after any potential updates)
    total_receivable = bills.filter(status__in=['unpaid', 'partial']).aggregate(
        res=Sum('grand_total')
    )['res'] or 0
    
    today = datetime.date.today()
    
    return render(request, 'delivery/bill_list.html', {
        'page_obj': page_obj,
        'status': status,
        'q': q,
        'month': month,
        'year': year,
        'total_receivable': total_receivable,
        'months': [(i, datetime.date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
        'today': today,
    })

@login_required
def bill_generate(request):
    customers = Customer.objects.filter(status='active').order_by('name')
    today = datetime.date.today()
    
    if request.method == 'POST':
        cust_ids = request.POST.getlist('customers')
        month = int(request.POST.get('month', today.month))
        year = int(request.POST.get('year', today.year))
        discount_pct = _dec(request.POST.get('discount_pct', '0'))
        
        from_date = datetime.date(year, month, 1)
        to_date = datetime.date(year, month, calendar.monthrange(year, month)[1])

        if not cust_ids:
            messages.warning(request, 'Select at least one customer.')
            return redirect('bill_generate')

        generated = updated_existing = skipped = 0
        
        for cid in cust_ids:
            customer = get_object_or_404(Customer, pk=cid)
            
            # 1. Calculate Current Month Deliveries
            deliveries = DailyDelivery.objects.filter(
                customer=customer, date__gte=from_date, date__lte=to_date, is_delivered=True
            )
            total_qty = deliveries.aggregate(q=Sum('quantity'))['q'] or Decimal('0')
            total_amount = deliveries.aggregate(a=Sum('amount'))['a'] or Decimal('0')

            if total_qty == 0:
                skipped += 1
                continue

            # 2. Fix: Accurate Previous Balance Logic
            # Find the immediate previous bill to carry forward debt correctly
            last_bill = Bill.objects.filter(
                customer=customer, 
                to_date__lt=from_date
            ).order_by('-to_date').first()

            prev_balance = Decimal('0')
            if last_bill:
                # Calculate unpaid portion of the last bill
                last_paid = Payment.objects.filter(bill=last_bill).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                prev_balance = last_bill.grand_total - last_paid
                
                # Subtract unlinked payments made after that bill but before this month
                extra = Payment.objects.filter(
                    customer=customer, bill__isnull=True,
                    payment_date__gt=last_bill.generated_at.date(),
                    payment_date__lt=from_date
                ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                prev_balance -= extra
            else:
                # No previous bills - check for older unlinked payments
                old_unlinked = Payment.objects.filter(
                    customer=customer, bill__isnull=True, payment_date__lt=from_date
                ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                prev_balance = -old_unlinked

            # 3. Calculate Discount
            discount = (total_amount * discount_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            # 4. Update or Create the Bill
            existing_bill = Bill.objects.filter(customer=customer, month=month, year=year).first()
            
            bill, created = Bill.objects.update_or_create(
                customer=customer, month=month, year=year,
                defaults={
                    'from_date': from_date, 
                    'to_date': to_date,
                    'total_quantity': total_qty, 
                    'total_amount': total_amount,
                    'discount': discount, 
                    'previous_balance': prev_balance,
                    'generated_by': request.user,
                    'status': existing_bill.status if existing_bill else 'unpaid',
                }
            )

            # 5. Sync status with actual payments
            paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')
            # If total is 0 or less, mark paid; otherwise check against grand_total
            if bill.grand_total <= 0:
                new_status = 'paid'
            else:
                new_status = 'paid' if paid >= bill.grand_total else ('partial' if paid > 0 else 'unpaid')
            
            Bill.objects.filter(pk=bill.pk).update(status=new_status)

            if created:
                generated += 1
            else:
                updated_existing += 1

        # 6. Final Message
        period_str = from_date.strftime('%B %Y')
        messages.success(request, f'{period_str}: {generated} generated, {updated_existing} updated, {skipped} skipped.')
        return redirect('bill_list')

    # GET logic
    sel_month = int(request.GET.get('month', today.month))
    sel_year = int(request.GET.get('year', today.year))
    existing_ids = set(Bill.objects.filter(month=sel_month, year=sel_year).values_list('customer_id', flat=True))
    
    return render(request, 'delivery/bill_generate.html', {
        'customers': customers, 
        'today': today,
        'months': [(i, datetime.date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
        'existing_bill_cust_ids': existing_ids, 
        'sel_month': sel_month, 
        'sel_year': sel_year,
    })


@login_required
def bill_detail(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    
    # Fetch deliveries and payments
    deliveries = DailyDelivery.objects.filter(
        customer=bill.customer, 
        date__gte=bill.from_date,
        date__lte=bill.to_date, 
        is_delivered=True
    ).order_by('date').select_related('product')
    
    payments = Payment.objects.filter(bill=bill).order_by('-payment_date')

    # 1. Recalculate current month's delivery total to check for drift
    # This ensures that if a delivery was edited, the detail page shows the true current total
    current_delivery_stats = deliveries.aggregate(
        actual_qty=Sum('quantity'), 
        actual_amt=Sum('amount')
    )
    
    # 2. Amount paid against THIS specific bill
    amount_paid = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    
    # 3. CRITICAL: Handle the "Grand Total" based on current reality
    # Use bill.grand_total for the official record, 
    # but sync it if the underlying deliveries changed.
    actual_grand_total = (current_delivery_stats['actual_amt'] or Decimal('0')) - bill.discount + bill.previous_balance
    
    # If there is a mismatch between the stored total and actual deliveries, update it
    if bill.grand_total != actual_grand_total:
        Bill.objects.filter(pk=bill.pk).update(
            total_quantity=current_delivery_stats['actual_qty'] or Decimal('0'),
            total_amount=current_delivery_stats['actual_amt'] or Decimal('0'),
            grand_total=actual_grand_total
        )
        bill.grand_total = actual_grand_total

    # 4. Final Balance Calculation
    amount_due = max(Decimal('0'), bill.grand_total - amount_paid)

    # 5. Sync bill status
    if bill.grand_total <= 0:
        expected_status = 'paid'
    elif amount_paid >= bill.grand_total:
        expected_status = 'paid'
    elif amount_paid > 0:
        expected_status = 'partial'
    else:
        expected_status = 'unpaid'

    if bill.status != expected_status:
        Bill.objects.filter(pk=bill.pk).update(status=expected_status)
        bill.status = expected_status

    return render(request, 'delivery/bill_detail.html', {
        'bill': bill, 
        'deliveries': deliveries, 
        'payments': payments,
        'amount_paid': amount_paid, 
        'amount_due': amount_due,
    })

@login_required
def bill_edit(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    
    if request.method == 'POST':
        p = request.POST
        
        # 1. Update the base values from the form
        bill.discount = _dec(p.get('discount', '0'))
        bill.previous_balance = _dec(p.get('previous_balance', '0'))
        bill.notes = p.get('notes', '')
        bill.status = p.get('status', bill.status)

        # 2. THE FIX: Recalculate Grand Total manually
        # This ensures the new 'previous_balance' is actually added to the total
        bill.grand_total = (bill.total_amount - bill.discount) + bill.previous_balance
        
        # 3. Save the bill (This updates previous_balance and grand_total)
        bill.save()

        # 4. Sync Payment Status
        # We check if the existing payments now cover the RECALCULATED grand_total
        paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')
        
        if bill.grand_total <= 0:
            new_status = 'paid'
        elif paid >= bill.grand_total:
            new_status = 'paid'
        elif paid > 0:
            new_status = 'partial'
        else:
            new_status = 'unpaid'
            
        # 5. Forced Update to database to ensure all fields are locked in
        Bill.objects.filter(pk=bill.pk).update(
            status=new_status, 
            grand_total=bill.grand_total
        )

        messages.success(request, f'Bill #{bill.bill_number} updated. New Total: Rs. {bill.grand_total:.2f}')
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


@login_required
def bill_mark_paid(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    if request.method == 'POST':
        p   = request.POST
        amt = _dec(p.get('amount_override','').strip()) if p.get('amount_override','').strip() else bill.amount_due
        if amt <= 0:
            messages.warning(request, 'Bill is already fully paid.')
            return redirect('bill_detail', pk=pk)
        Payment.objects.create(
            customer=bill.customer, bill=bill, amount=amt,
            payment_method=p.get('method','cash'),
            reference_number=p.get('reference',''),
            payment_date=datetime.date.today(),
            received_by=request.user,
        )
        paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')
        Bill.objects.filter(pk=bill.pk).update(
            status='paid' if paid >= bill.grand_total else 'partial')
        messages.success(request, f'Payment Rs.{amt} recorded for Bill #{bill.bill_number}')
    return redirect('bill_detail', pk=pk)


@login_required
def bill_pdf(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    # Added select_related('product') to ensure we get the full product name accurately
    deliveries = DailyDelivery.objects.filter(
        customer=bill.customer, 
        date__gte=bill.from_date, 
        date__lte=bill.to_date, 
        is_delivered=True
    ).order_by('date').select_related('product')
    
    payments = Payment.objects.filter(bill=bill)
    amount_paid = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    # Updated amount_due calculation
    amount_due = max(Decimal('0'), bill.grand_total - amount_paid)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                        Paragraph, Spacer)
        import io

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, margin=1*cm)
        ss = getSampleStyleSheet()
        
        # --- Milky Way Color Palette (Unchanged) ---
        brand_navy = colors.HexColor('#0f172a') 
        brand_soft = colors.HexColor('#f8fafc')
        accent_grn = colors.HexColor('#10b981')
        accent_red = colors.HexColor('#ef4444')

        # --- Defined Styles (Unchanged) ---
        title_s = ParagraphStyle('T', parent=ss['Normal'], textColor=colors.white, fontSize=22, fontName='Helvetica-Bold', leading=26)
        period_s = ParagraphStyle('P', parent=ss['Normal'], textColor=colors.white, fontSize=10, fontName='Helvetica-Bold', leading=14, backColor=colors.green, borderPadding=4, borderRadius=4)
        tagline_s = ParagraphStyle('Tag', parent=ss['Normal'], textColor=colors.white, fontSize=9, leading=12)
        label_s = ParagraphStyle('L', parent=ss['Normal'], textColor=colors.HexColor('#64748b'), fontSize=7, fontName='Helvetica-Bold', textTransform='uppercase')
        norm_s = ParagraphStyle('N', parent=ss['Normal'], textColor=brand_navy, fontSize=9, leading=13)
        f_label = ParagraphStyle('FL', parent=ss['Normal'], textColor=colors.white, fontSize=8, fontName='Helvetica-Bold', alignment=1)
        f_val = ParagraphStyle('FV', parent=ss['Normal'], textColor=colors.white, fontSize=16, fontName='Helvetica-Bold', alignment=1)

        story = []

        # ── 1. TOP CARD (UI Unchanged) ──
        month_name = bill.from_date.strftime('%B %Y').upper()
        date_range = f"{bill.from_date.strftime('%d %b')} - {bill.to_date.strftime('%d %b %Y')}"
        header_data = [[
            [Paragraph("MILKY WAY", title_s), Paragraph("Venduvazhy, Kothamangalam", tagline_s), Paragraph(f"<b>GPAY: 9645311829</b>", tagline_s)],
            [Paragraph(month_name, period_s), Spacer(1, 5), Paragraph(f"<b>INVOICE: #{bill.bill_number}</b>", tagline_s.clone('inv', alignment=2)), Paragraph(date_range, tagline_s.clone('dt', alignment=2, fontSize=8))]
        ]]
        head_tab = Table(header_data, colWidths=[10*cm, 8*cm])
        head_tab.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), brand_navy), ('ROUNDEDCORNERS', [12, 12, 12, 12]), ('LEFTPADDING', (0,0), (-1,-1), 20), ('RIGHTPADDING', (0,0), (-1,-1), 20), ('TOPPADDING', (0,0), (-1,-1), 20), ('BOTTOMPADDING', (0,0), (-1,-1), 20), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        story.append(head_tab)
        story.append(Spacer(1, 0.6*cm))

        # ── 2. CUSTOMER INFO CARD (UI Unchanged) ──
        customer_data = [[[Paragraph("BILL TO", label_s), Spacer(1, 2), Paragraph(f"<b>{bill.customer.name}</b>", norm_s.clone('cn', fontSize=12)), Paragraph(bill.customer.phone, norm_s), Paragraph(bill.customer.address[:80], norm_s)]]]
        ct = Table(customer_data, colWidths=[18*cm])
        ct.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), brand_soft), ('ROUNDEDCORNERS', [8, 8, 8, 8]), ('LEFTPADDING', (0,0), (-1,-1), 15), ('TOPPADDING', (0,0), (-1,-1), 12), ('BOTTOMPADDING', (0,0), (-1,-1), 12)]))
        story.append(ct)
        story.append(Spacer(1, 0.8*cm))

        # ── 3. DELIVERY TABLE (UPDATED FOR PRODUCT NAME) ──
        rows_data = [['DATE', 'DAY', 'PRODUCT', 'QTY', 'RATE', 'SUBTOTAL']]
        for d in deliveries:
            # FIX: Changed "MILK" to d.product.name to show the actual product name
            product_name = d.product.name.upper() if d.product else "DAIRY PRODUCT"
            rows_data.append([
                d.date.strftime('%d %b'), 
                d.date.strftime('%a').upper(), 
                product_name, 
                f"{d.quantity} L", 
                f"{d.price_per_unit}", 
                f"{d.amount:.2f}"
            ])
        
        dt = Table(rows_data, colWidths=[2.5*cm, 2*cm, 7*cm, 2*cm, 2*cm, 3*cm])
        dt.setStyle(TableStyle([('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,0), 8), ('LINEBELOW', (0,0), (-1,0), 1, brand_navy), ('ALIGN', (3,0), (-1,-1), 'RIGHT'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, brand_soft]), ('TOPPADDING',(0,0),(-1,-1),8), ('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        story.append(dt)
        story.append(Spacer(1, 1.5*cm))

        # ── 4. SETTLEMENT CARD (UPDATED LABELS & LOGIC) ──
        summary_card_data = [
            [Paragraph("This Month Total", f_label), Paragraph("Previous Balance", f_label), Paragraph("Final Total Due", f_label)],
            [
                Paragraph(f"Rs. {bill.net_amount:.2f}", f_val), 
                Paragraph(f"Rs. {bill.previous_balance:.2f}", f_val), 
                # FIX: Ensures the Final Balance Due reflects the Grand Total after payments/discounts
                Paragraph(f"Rs. {bill.grand_total:.2f}", f_val.clone('due', textColor=colors.yellow))
            ]
        ]
        
        sc = Table(summary_card_data, colWidths=[6.3*cm, 6.3*cm, 6.3*cm])
        sc.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), brand_navy), ('ROUNDEDCORNERS', [12, 12, 12, 12]), ('TOPPADDING', (0,0), (-1,-1), 12), ('BOTTOMPADDING', (0,0), (-1,-1), 12), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        story.append(sc)

        # ── 5. FOOTER ──
        story.append(Spacer(1, 1*cm))
        story.append(Paragraph("THANK YOU FOR CHOOSING MILKY WAY • QUALITY IN EVERY DROP", ParagraphStyle('f', parent=norm_s, alignment=1, fontSize=8, letterSpacing=2, textColor=colors.gray)))

        doc.build(story)
        buf.seek(0)
        resp = HttpResponse(buf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="MilkyWay_{bill.bill_number}.pdf"'
        return resp

    except Exception as e:
        return HttpResponse(f"PDF Error: {e}", status=500)


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
    import urllib.parse
    return redirect(f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}")


@login_required
def api_bill_status(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    paid = bill.payment_set.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    return JsonResponse({'bill_number': bill.bill_number, 'grand_total': float(bill.grand_total),
                         'amount_paid': float(paid), 'amount_due': float(max(Decimal('0'), bill.grand_total-paid)), 'status': bill.status})


# ── PAYMENTS ──────────────────────────────────────────────────────────────────
@login_required
def payment_add(request, customer_pk=None):
    customers    = Customer.objects.filter(status='active').order_by('name')
    customer     = get_object_or_404(Customer, pk=customer_pk) if customer_pk else None
    unpaid_bills = Bill.objects.filter(customer=customer, status__in=['unpaid','partial']) if customer else []
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
                Bill.objects.filter(pk=b.pk).update(status='paid' if paid >= b.grand_total else 'partial')
            except Bill.DoesNotExist:
                pass
        messages.success(request, f'Payment of Rs.{pmt.amount} recorded for {cust.name}')
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
    total = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    paginator = Paginator(payments, 25)
    page = paginator.get_page(request.GET.get('page'))
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
            Bill.objects.filter(pk=bill.pk).update(status='paid' if paid >= bill.grand_total and bill.grand_total>0 else ('partial' if paid > 0 else 'unpaid'))
        messages.success(request, f'Payment of Rs.{amt} from {cust} deleted.')
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
            MilkProduct.objects.create(name=p['name'].strip(), unit=p.get('unit','L'),
                default_price=_dec(p.get('default_price','0')), description=p.get('description',''))
            messages.success(request, 'Product added!')
            return redirect('product_list')
    return render(request, 'delivery/product_form.html', {'unit_choices': MilkProduct.UNIT_CHOICES, 'action': 'Add'})


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
        'product': product, 'unit_choices': MilkProduct.UNIT_CHOICES, 'action': 'Edit'
    })


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
    by_cat = list(qs.values('category__name','category__icon').annotate(total=Sum('amount'),count=Count('id')).order_by('-total'))

    categories = ExpenseCategory.objects.filter(is_active=True)
    paginator  = Paginator(qs, 20)
    page       = paginator.get_page(request.GET.get('page'))

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
    today = datetime.date.today()
    if request.method == 'POST':
        p = request.POST
        title = p.get('title','').strip()
        if not title:
            messages.error(request, 'Title is required.')
        else:
            try:
                exp = Expense(
                    title        = title,
                    amount       = _dec(p.get('amount','0')),
                    date         = _parse_date(p.get('date'), today),
                    payment_mode = p.get('payment_mode','cash'),
                    vendor       = p.get('vendor','').strip(),
                    invoice_no   = p.get('invoice_no','').strip(),
                    description  = p.get('description','').strip(),
                    is_recurring = p.get('is_recurring') == 'on',
                    added_by     = request.user,
                )
                cat_id = p.get('category','').strip()
                exp.category_id = int(cat_id) if cat_id else None
                if 'receipt' in request.FILES:
                    exp.receipt = request.FILES['receipt']
                exp.save()
                messages.success(request, f'Expense "{exp.title}" of Rs.{exp.amount} added!')
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
        p = request.POST
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
            ExpenseCategory.objects.create(name=name, icon=p.get('icon','other'), color=p.get('color','#6b7280'))
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

    # --- 1. Customer & Product Split Logic ---
    # We fetch raw data grouped by customer and product
    raw_deliveries = (DailyDelivery.objects.filter(date__month=month, date__year=year, is_delivered=True)
                      .values('customer__name', 'customer__customer_id', 'product__name')
                      .annotate(qty=Sum('quantity'), amount=Sum('amount'), avg_price=Avg('price_per_unit'))
                      .order_by('customer__name'))

    # Grouping in Python to bypass template limitations
    processed_summary = {}
    for item in raw_deliveries:
        name = item['customer__name']
        if name not in processed_summary:
            processed_summary[name] = {
                'name': name,
                'customer_id': item['customer__customer_id'],
                'products': [],
                'total_revenue': Decimal('0')
            }
        processed_summary[name]['products'].append(item)
        processed_summary[name]['total_revenue'] += item['amount']

    # Sort list by top revenue (Most spending customers first)
    monthly_summary_list = sorted(processed_summary.values(), key=lambda x: x['total_revenue'], reverse=True)

    # --- 2. Full Monthly Calendar Logic (No Gaps) ---
    num_days = calendar.monthrange(year, month)[1]
    all_dates = [datetime.date(year, month, day) for day in range(1, num_days + 1)]
    
    delivery_map = {d['date']: d for d in DailyDelivery.objects.filter(date__month=month, date__year=year, is_delivered=True)
                    .values('date').annotate(qty=Sum('quantity'), amount=Sum('amount'))}
    expense_map  = {e['date']: e for e in Expense.objects.filter(date__month=month, date__year=year)
                    .values('date').annotate(total=Sum('amount'))}

    full_daily_totals = []
    for d in all_dates:
        full_daily_totals.append({
            'date': d,
            'qty': delivery_map.get(d, {}).get('qty', 0),
            'amount': delivery_map.get(d, {}).get('amount', 0),
            'expense': expense_map.get(d, {}).get('total', 0),
        })

    # --- 3. Final Aggregates ---
    total_revenue = sum(item['amount'] for item in full_daily_totals)
    total_qty = sum(item['qty'] for item in full_daily_totals)
    total_expense = sum(item['expense'] for item in full_daily_totals)
    
    monthly_expenses = (Expense.objects.filter(date__month=month, date__year=year)
                        .values('category__name','category__icon')
                        .annotate(total=Sum('amount')).order_by('-total'))

    return render(request, 'delivery/reports.html', {
        'monthly_summary': monthly_summary_list,
        'daily_totals': full_daily_totals,
        'monthly_expenses': monthly_expenses,
        'total_qty': total_qty, 
        'total_revenue': total_revenue,
        'total_expense': total_expense, 
        'net_profit': total_revenue - total_expense,
        'month': month, 'year': year,
        'months': [(i, datetime.date(2000,i,1).strftime('%B')) for i in range(1,13)],
        'today': today,
    })
# ── API ───────────────────────────────────────────────────────────────────────
@login_required
def api_customer_price(request, pk):
    c = get_object_or_404(Customer, pk=pk)
    subs = [{'product': str(s.product), 'product_id': s.product.pk, 'qty': float(s.quantity), 'price': float(s.price)}
            for s in c.active_subscriptions]
    return JsonResponse({'price': float(c.price_per_unit), 'default_qty': float(c.default_qty), 'subscriptions': subs})
