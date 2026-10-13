from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0010_profileimprovementproposal')]

    operations = [
        migrations.AlterField(
            model_name='jobsource',
            name='kind',
            field=models.CharField(
                choices=[('brave', 'Brave web discovery')],
                db_index=True,
                default='brave',
                max_length=32,
            ),
        ),
    ]
