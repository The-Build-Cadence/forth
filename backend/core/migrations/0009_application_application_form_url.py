from django.db import migrations, models


def populate_application_form_urls(apps, schema_editor):
    Application = apps.get_model('core', 'Application')
    for application in Application.objects.select_related('job').iterator():
        application.application_form_url = application.job.application_url or application.job.source_url
        application.save(update_fields=['application_form_url'])


class Migration(migrations.Migration):
    dependencies = [('core', '0008_candidateprofile_minimum_match_score')]

    operations = [
        migrations.AddField(
            model_name='application',
            name='application_form_url',
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.RunPython(populate_application_form_urls, migrations.RunPython.noop),
    ]
