# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-26 18:22
from __future__ import unicode_literals

from __future__ import absolute_import
from couchdbkit.exceptions import ResourceNotFound
from django.db import migrations

from corehq.apps.app_manager.models import Application
from corehq.dbaccessors.couchapps.all_docs import get_all_docs_with_doc_types


def _populate_master_domain(apps, schema_editor):
    app_db = Application.get_db()
    for app in get_all_docs_with_doc_types(app_db, ['LinkedApplication']):
        if not app.get('master_domain', None):
            master_domain = app.pop('remote_domain', None)
            if not master_domain:
                try:
                    master_app = app_db.get(app['master'])
                    master_domain = master_app['domain']
                except ResourceNotFound:
                    pass
            app['master_domain'] = master_domain
            app_db.save_doc(app)


def _reverse_noop(app, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(_populate_master_domain, reverse_code=_reverse_noop),
    ]
