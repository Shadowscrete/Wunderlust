from django.db import migrations


def promote_existing_superusers(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(is_superuser=True).update(role='ADMINISTRATOR')


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_alter_user_managers'),
    ]

    operations = [
        migrations.RunPython(promote_existing_superusers, migrations.RunPython.noop),
    ]
