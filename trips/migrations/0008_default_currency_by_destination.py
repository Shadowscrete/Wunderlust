from collections import defaultdict

from django.db import migrations, models

from trips.currencies import COUNTRY_CURRENCY


def set_destination_currency(apps, schema_editor):
    Trip = apps.get_model('trips', 'Trip')
    by_currency = defaultdict(list)
    for country, currency in COUNTRY_CURRENCY.items():
        if currency != 'USD':
            by_currency[currency].append(country)
    unused_defaults = Trip.objects.using(schema_editor.connection.alias).filter(
        currency='USD', expenses__isnull=True, settlements__isnull=True,
    )
    unused_defaults.filter(country__in=[country for names in by_currency.values() for country in names]).update(
        currency=models.Case(*(
            models.When(country__in=countries, then=models.Value(currency))
            for currency, countries in by_currency.items()
        ), output_field=models.CharField()),
    )


class Migration(migrations.Migration):
    dependencies = [('trips', '0007_trip_currency_expense_expenseshare_settlement_and_more')]

    operations = [migrations.RunPython(set_destination_currency, migrations.RunPython.noop)]
