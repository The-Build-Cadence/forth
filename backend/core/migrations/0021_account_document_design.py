from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0020_static_search_criteria')]
    operations = [migrations.AddField(
        model_name='accountsettings', name='document_design',
        field=models.JSONField(default=dict, blank=True),
    )]
