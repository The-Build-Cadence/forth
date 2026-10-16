"""Read-only check for inconsistent ownership in persisted relationships."""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F


class Command(BaseCommand):
    help = 'Check owner-bearing relations for cross-account links without exposing user data.'

    def handle(self, *args, **options):
        checked = violations = 0
        for model in apps.get_app_config('core').get_models():
            if not any(field.name == 'owner' for field in model._meta.fields):
                continue
            for field in model._meta.fields:
                related = field.related_model
                if not related or not any(f.name == 'owner' for f in related._meta.fields):
                    continue
                checked += 1
                count = model.objects.filter(**{f'{field.name}__isnull': False}).exclude(
                    owner_id=F(f'{field.name}__owner_id'),
                ).count()
                if count:
                    violations += count
                    self.stdout.write(f'{model._meta.label}.{field.name}: {count} inconsistent links')
        self.stdout.write(f'Checked {checked} owner-bearing relationships; {violations} inconsistent links.')
        if violations:
            raise CommandError('Ownership inconsistencies found; investigate before sharing this deployment.')
