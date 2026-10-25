from django.db import migrations


def freeze_search_criteria(apps, schema_editor):
    sources = apps.get_model('core', 'JobSource')
    profiles = apps.get_model('core', 'CandidateProfile')
    database = schema_editor.connection.alias
    for source in sources.objects.using(database).filter(kind='brave').iterator():
        profile = profiles.objects.using(database).filter(owner_id=source.owner_id).first()
        config = dict(source.config or {})
        config.setdefault('adaptive_search', False)
        config.setdefault('static_criteria', {
            field: getattr(profile, field, '' if field == 'location' else [])
            for field in ('target_roles', 'location', 'work_modes', 'authorized_countries')
        })
        source.config = config
        source.save(using=database, update_fields=['config'])


class Migration(migrations.Migration):
    dependencies = [('core', '0019_account_ai_and_application_fields')]
    operations = [migrations.RunPython(freeze_search_criteria, migrations.RunPython.noop)]
