# Generated by Django 2.2.16 on 2021-03-04 12:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('hqwebapp', '0006_create_user_access_log'),
    ]

    operations = [
        migrations.AlterField(
            model_name='useraccesslog',
            name='user_agent',
            field=models.ForeignKey(
                db_column='user_agent_id',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='hqwebapp.UserAgent'
            ),
        ),
        migrations.RenameField(
            model_name='useraccesslog',
            old_name='user_agent',
            new_name='user_agent_fk',
        ),
    ]
