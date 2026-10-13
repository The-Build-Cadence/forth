from django.db import migrations


def disable_legacy_sources(apps, schema_editor):
    JobSource = apps.get_model('core', 'JobSource')
    JobSource.objects.exclude(kind='brave').update(
        enabled=False,
        last_status='retired',
        last_message='Retired: discovery now uses Brave web search only.',
    )


class Migration(migrations.Migration):
    dependencies = [('core', '0011_simplify_sources_to_brave')]

    operations = [migrations.RunPython(disable_legacy_sources, migrations.RunPython.noop)]
