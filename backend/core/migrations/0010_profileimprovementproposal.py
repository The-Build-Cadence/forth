from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0009_application_application_form_url'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProfileImprovementProposal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('status', models.CharField(choices=[('pending', 'Pending review'), ('applied', 'Applied'), ('rejected', 'Rejected'), ('superseded', 'Superseded')], db_index=True, default='pending', max_length=24)),
                ('source_score', models.PositiveSmallIntegerField(default=0)),
                ('suggestions', models.JSONField(blank=True, default=list)),
                ('decision', models.JSONField(blank=True, default=dict)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='profile_improvement_proposals', to='core.jobposting')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [models.Index(fields=['owner', 'job', 'status'], name='core_profil_owner_i_db5f73_idx')],
            },
        ),
    ]
