"""Per-account provider accounting. Never store prompts, queries, or API keys."""
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from functools import wraps
from inspect import signature

from django.conf import settings
from django.db import connection
from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

_context = ContextVar('provider_usage_owner', default=None)


@contextmanager
def usage_context(owner, origin='web', operation=''):
    token = _context.set((owner, origin, operation))
    try:
        yield
    finally:
        _context.reset(token)


def current_owner_id():
    owner = (_context.get() or (None,))[0]
    owner = owner() if callable(owner) else owner
    return owner if isinstance(owner, int) else getattr(owner, 'pk', None)


def metered_task(model=None, argument='owner_id'):
    """Resolve ownership from persisted records, including jobs launched by Beat."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            values = signature(function).bind(*args, **kwargs)
            values.apply_defaults()
            identifier = values.arguments[argument]
            owner_id = model.objects.values_list('owner_id', flat=True).get(pk=identifier) if model else identifier
            with usage_context(owner_id, values.arguments.get('origin', 'background'), function.__name__):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def ledger():
    from .models import ProviderUsage
    # PostgreSQL gets a separate autocommit connection to the SAME database.
    # Charges survive a surrounding workflow rollback or a worker being killed.
    alias = getattr(settings, 'USAGE_DATABASE_ALIAS', 'usage' if connection.vendor == 'postgresql' else 'default')
    return ProviderUsage.objects.using(alias)


def begin_request(provider, operation, model='', owner=None):
    context_owner, origin, context_operation = _context.get() or (None, 'internal', '')
    owner = owner if owner is not None else context_owner
    owner = owner() if callable(owner) else owner
    owner_id = owner if isinstance(owner, int) else getattr(owner, 'pk', None)
    if not owner_id:
        raise ValueError('Provider requests require an account usage context.')
    from .account_ai import account_config
    config = account_config() if provider == 'openai' else None
    return ledger().create(owner_id=owner_id, provider=provider, operation=operation,
                           credential_source='personal' if config and config.use_personal_ai else 'shared',
                           model=model, origin=origin, workflow=context_operation)


def value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def finish_openai(entry, response):
    usage = value(response, 'usage')
    model = value(response, 'model') or entry.model
    rates = settings.OPENAI_USAGE_RATES.get(model)
    # Dated snapshots share their base model's rates; arbitrary prefixes do not.
    if rates is None:
        import re
        rates = settings.OPENAI_USAGE_RATES.get(re.sub(r'-\d{4}-\d{2}-\d{2}$', '', model))
    incoming = value(usage, 'input_tokens', value(usage, 'prompt_tokens'))
    outgoing = value(usage, 'output_tokens', 0)
    cached = value(value(usage, 'input_tokens_details'), 'cached_tokens', 0)
    cost = None
    if incoming is not None and rates is not None:
        incoming, outgoing = int(incoming), int(outgoing or 0)
        cached = min(incoming, max(0, int(cached or 0)))
        cost = (Decimal(incoming - cached) * Decimal(str(rates[0])) +
                Decimal(cached) * Decimal(str(rates[1])) +
                Decimal(outgoing) * Decimal(str(rates[2]))) / Decimal(1000000)
    ledger().filter(pk=entry.pk).update(
        status='succeeded', model=model, input_tokens=incoming, output_tokens=outgoing,
        cached_tokens=cached, cost_usd=cost, rates=rates or [],
        provider_request_id=str(value(response, '_request_id', '') or '')[:200],
    )


def fail_request(entry, error):
    # Timeouts can be billed upstream. Missing usage is unknown, never zero.
    ledger().filter(pk=entry.pk).update(status='failed', error_type=type(error).__name__[:80])


def openai_request(create, *, operation, **kwargs):
    entry = begin_request('openai', operation, kwargs.get('model', ''))
    try:
        response = create(**kwargs)
    except Exception as exc:
        fail_request(entry, exc)
        raise
    finish_openai(entry, response)
    return response


def brave_request(get, *, owner, **kwargs):
    entry = begin_request('brave', 'web_search', owner=owner)
    try:
        response = get(**kwargs)
        response.raise_for_status()
    except Exception as exc:
        fail_request(entry, exc)
        raise
    rate = Decimal(settings.BRAVE_COST_PER_1000_REQUESTS)
    ledger().filter(pk=entry.pk).update(status='succeeded', cost_usd=rate / 1000, rates=[str(rate)])
    return response


def usage_summary(owner):
    from .models import ProviderUsage
    rows = ProviderUsage.objects.filter(owner=owner)
    month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = {'currency': 'USD', 'estimated': True, 'month_start': month,
              'first_request_at': rows.aggregate(first=Min('created_at'))['first'], 'providers': {}}
    for provider in ('openai', 'brave'):
        totals = rows.filter(provider=provider).aggregate(
            requests=Count('id'), total_cost_usd=Sum('cost_usd'),
            month_cost_usd=Sum('cost_usd', filter=Q(created_at__gte=month)),
            month_requests=Count('id', filter=Q(created_at__gte=month)),
            unknown_cost_requests=Count('id', filter=Q(cost_usd__isnull=True)),
            background_requests=Count('id', filter=Q(origin__in=['background', 'scheduled'])),
            input_tokens=Sum('input_tokens'), output_tokens=Sum('output_tokens'),
        )
        totals['cost_usd'] = totals.pop('total_cost_usd')
        for key in ('cost_usd', 'month_cost_usd'):
            totals[key] = format(totals[key] or Decimal(0), '.8f')
        result['providers'][provider] = totals
    return result
