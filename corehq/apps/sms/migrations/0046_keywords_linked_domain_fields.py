# Generated by Django 2.2.13 on 2020-08-21 20:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sms', '0045_auto_20200821_2051'),
    ]

    operations = [
        migrations.AddField(
            model_name='keyword',
            name='master_id',
            field=models.CharField(max_length=126, null=True),
        ),
        migrations.AddField(
            model_name='keywordaction',
            name='master_id',
            field=models.CharField(max_length=126, null=True),
        ),
    ]
