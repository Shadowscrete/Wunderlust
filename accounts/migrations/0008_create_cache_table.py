from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # Shared cache used on Vercel (settings: CACHES → DatabaseCache 'wunderlust_cache').
    # Safe to run repeatedly: createcachetable skips tables that already exist.
    call_command('createcachetable', 'wunderlust_cache', database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0007_profile_notify_member_joins_profile_notify_system_and_more')]
    operations = [migrations.RunPython(create_cache_table, migrations.RunPython.noop)]
