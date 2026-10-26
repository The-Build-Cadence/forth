import re

from django.db import migrations, models
from django.utils import timezone


def backfill(apps, schema_editor):
    Application = apps.get_model('core', 'Application')
    Event = apps.get_model('core', 'ApplicationEvent')
    alias = schema_editor.connection.alias
    for application in Application.objects.using(alias).all().iterator():
        # Old code did not record every transition. Only trust an event explicitly
        # naming the current status; otherwise label the last-edit baseline estimated.
        event = Event.objects.using(alias).filter(application_id=application.pk, event_type='status_changed').order_by('-happened_at', '-id').first()
        exact = bool(event and re.fullmatch(r"Status changed from \w+ to " + re.escape(application.status) + r"\.", event.notes))
        entered = event.happened_at if exact else application.updated_at
        Application.objects.using(alias).filter(pk=application.pk).update(status_entered_at=entered, status_age_estimated=not exact)


class Migration(migrations.Migration):
    dependencies = [('core', '0021_account_document_design')]
    operations = [
        migrations.AddField(model_name='application', name='status_entered_at', field=models.DateTimeField(default=timezone.now, editable=False)),
        migrations.AddField(model_name='application', name='status_age_estimated', field=models.BooleanField(default=False, editable=False)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
