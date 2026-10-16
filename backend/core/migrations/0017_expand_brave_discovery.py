from django.db import migrations


def expand_brave_discovery(apps, schema_editor):
    JobSource = apps.get_model('core', 'JobSource')
    for source in JobSource.objects.using(schema_editor.connection.alias).filter(kind='brave').iterator():
        config = dict(source.config or {})
        config['results_per_query'] = 20
        # Five was hard-coded by the UI. Preserve other explicit import limits.
        if config.get('max_candidates') in (None, 5):
            config['max_candidates'] = 20
        source.config = config
        source.save(update_fields=['config'], using=schema_editor.connection.alias)


class Migration(migrations.Migration):
    dependencies = [('core', '0016_jobposting_materials_started_at_and_more')]
    operations = [migrations.RunPython(expand_brave_discovery, migrations.RunPython.noop)]
