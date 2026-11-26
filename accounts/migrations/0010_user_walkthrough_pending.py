from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0009_profile_notify_new_followers_report_follow')]

    operations = [
        migrations.AddField(
            model_name='user',
            name='walkthrough_pending',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='user',
            name='walkthrough_pending',
            field=models.BooleanField(default=True),
        ),
    ]
