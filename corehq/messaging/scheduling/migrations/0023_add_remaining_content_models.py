# Generated by Django 1.11.14 on 2018-08-08 12:16

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0022_add_stop_date_case_property_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='SMSCallbackContent',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.JSONField(default=dict)),
                ('reminder_intervals', models.JSONField(default=list)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='ivrsurveycontent',
            name='include_case_updates_in_partial_submissions',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='ivrsurveycontent',
            name='max_question_attempts',
            field=models.IntegerField(default=5),
        ),
        migrations.AddField(
            model_name='ivrsurveycontent',
            name='reminder_intervals',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='ivrsurveycontent',
            name='submit_partially_completed_forms',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='alertevent',
            name='sms_callback_content',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='scheduling.SMSCallbackContent'),
        ),
        migrations.AddField(
            model_name='casepropertytimedevent',
            name='sms_callback_content',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='scheduling.SMSCallbackContent'),
        ),
        migrations.AddField(
            model_name='randomtimedevent',
            name='sms_callback_content',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='scheduling.SMSCallbackContent'),
        ),
        migrations.AddField(
            model_name='timedevent',
            name='sms_callback_content',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='scheduling.SMSCallbackContent'),
        ),
    ]
