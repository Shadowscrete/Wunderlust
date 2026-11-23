import secrets

import django.db.models.deletion
import trips.models
from django.db import migrations, models


def populate_invite_codes(apps, schema_editor):
    GroupTrip = apps.get_model('trips', 'GroupTrip')
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    for group_trip in GroupTrip.objects.filter(invite_code='').iterator():
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(10))
            if not GroupTrip.objects.filter(invite_code=code).exists():
                group_trip.invite_code = code
                group_trip.save(update_fields=('invite_code',))
                break


class Migration(migrations.Migration):
    dependencies = [('trips', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='trip', name='country', field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='trip', name='airline', field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='activity', name='is_recommended', field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='checklist', name='is_mandatory', field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='checklist', name='is_custom', field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='checklist', name='quantity', field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='grouptrip', name='invite_code', field=models.CharField(blank=True, default='', max_length=10),
        ),
        migrations.RunPython(populate_invite_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='grouptrip', name='invite_code',
            field=models.CharField(default=trips.models.create_trip_code, editable=False, max_length=10, unique=True),
        ),
        migrations.CreateModel(
            name='TripPlace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=180)),
                ('visit_order', models.PositiveIntegerField(default=0)),
                ('trip', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='places', to='trips.trip')),
            ],
            options={'ordering': ('visit_order', 'name')},
        ),
        migrations.AddConstraint(
            model_name='trip',
            constraint=models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F('start_date')),
                name='trip_end_on_or_after_start',
            ),
        ),
    ]
