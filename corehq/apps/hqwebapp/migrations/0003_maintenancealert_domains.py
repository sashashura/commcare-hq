# Generated by Django 1.11.17 on 2018-12-25 19:26

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hqwebapp', '0002_auto_20171121_1803'),
    ]

    operations = [
        migrations.AddField(
            model_name='maintenancealert',
            name='domains',
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=126),
                null=True,
                size=None
            ),
        ),
    ]
