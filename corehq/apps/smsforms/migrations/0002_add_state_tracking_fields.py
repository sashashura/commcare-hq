# Generated by Django 1.11.8 on 2018-01-11 17:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smsforms', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='sqlxformssession',
            name='current_action_due',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='sqlxformssession',
            name='current_reminder_num',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='sqlxformssession',
            name='expire_after',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='sqlxformssession',
            name='include_case_updates_in_partial_submissions',
            field=models.BooleanField(null=True),
        ),
        migrations.AddField(
            model_name='sqlxformssession',
            name='phone_number',
            field=models.CharField(max_length=126, null=True),
        ),
        migrations.AddField(
            model_name='sqlxformssession',
            name='reminder_intervals',
            field=models.JSONField(null=True),
        ),
        migrations.AddField(
            model_name='sqlxformssession',
            name='session_is_open',
            field=models.BooleanField(null=True),
        ),
        migrations.AddField(
            model_name='sqlxformssession',
            name='submit_partially_completed_forms',
            field=models.BooleanField(null=True),
        ),
        migrations.AlterIndexTogether(
            name='sqlxformssession',
            index_together=set([('session_is_open', 'connection_id'), ('session_is_open', 'current_action_due')]),
        ),
    ]
