from corehq.apps.fixtures.dbaccessors import (
    delete_all_fixture_data,
    delete_fixture_items_for_data_type,
    get_fixture_items_for_data_type,
)
from corehq.apps.fixtures.models import (
    FieldList,
    FixtureDataItem,
    FixtureItemField,
    LookupTable,
    TypeField,
)
from corehq.apps.fixtures.upload.run_upload import clear_fixture_quickcache
from corehq.apps.fixtures.utils import clear_fixture_cache
from corehq.apps.linked_domain.exceptions import UnsupportedActionError
from corehq.apps.linked_domain.tests.test_linked_apps import BaseLinkedDomainTest
from corehq.apps.linked_domain.updates import update_fixture


class TestUpdateFixtures(BaseLinkedDomainTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.table = LookupTable(
            domain=cls.domain,
            tag='moons',
            is_global=True,
            fields=[
                TypeField(name="name"),
                TypeField(name="planet"),
            ],
        )
        cls.table.save()
        cls.addClassCleanup(delete_all_fixture_data)

    def setUp(self):
        # Reset table content for each test
        for item in [
            FixtureDataItem(
                domain=self.domain,
                data_type_id=self.table._migration_couch_id,
                fields={
                    'name': FieldList(field_list=[FixtureItemField(field_value='Io')]),
                    'planet': FieldList(field_list=[FixtureItemField(field_value='Jupiter')]),
                },
            ),
            FixtureDataItem(
                domain=self.domain,
                data_type_id=self.table._migration_couch_id,
                fields={
                    'name': FieldList(field_list=[FixtureItemField(field_value='Europa')]),
                    'planet': FieldList(field_list=[FixtureItemField(field_value='Jupiter')]),
                },
            ),
            FixtureDataItem(
                domain=self.domain,
                data_type_id=self.table._migration_couch_id,
                fields={
                    'name': FieldList(field_list=[FixtureItemField(field_value='Callisto')]),
                    'planet': FieldList(field_list=[FixtureItemField(field_value='Jupiter')]),
                },
            ),
        ]:
            item.save()

    def tearDown(self):
        delete_fixture_items_for_data_type(self.domain, self.table._migration_couch_id)

    def test_update_fixture(self):
        self.assertFalse(LookupTable.objects.by_domain(self.linked_domain).count())

        # Update linked domain
        update_fixture(self.domain_link, self.table.tag)

        # Linked domain should now have master domain's table and rows
        linked_types = LookupTable.objects.by_domain(self.linked_domain)
        self.assertEqual({'moons'}, {t.tag for t in linked_types})
        self.assertEqual({self.linked_domain}, {t.domain for t in linked_types})
        items = get_fixture_items_for_data_type(self.linked_domain, linked_types[0]._migration_couch_id)
        self.assertEqual({self.linked_domain}, {i.domain for i in items})
        self.assertEqual({linked_types[0]._migration_couch_id}, {i.data_type_id for i in items})
        self.assertEqual([
            'Callisto', 'Europa', 'Io', 'Jupiter', 'Jupiter', 'Jupiter',
        ], sorted([
            i.fields[field_name].field_list[0].field_value for i in items for field_name in i.fields.keys()
        ]))

        # Master domain's table and rows should be untouched
        master_types = LookupTable.objects.by_domain(self.domain)
        self.assertEqual({'moons'}, {t.tag for t in master_types})
        self.assertEqual({self.domain}, {t.domain for t in master_types})
        master_items = get_fixture_items_for_data_type(self.domain, master_types[0]._migration_couch_id)
        self.assertEqual([
            'Callisto', 'Europa', 'Io', 'Jupiter', 'Jupiter', 'Jupiter',
        ], sorted([
            i.fields[field_name].field_list[0].field_value
            for i in master_items
            for field_name in i.fields.keys()
        ]))

        # Update rows in master table and re-update linked domain
        master_items[-1].delete()       # Callisto
        FixtureDataItem(
            domain=self.domain,
            data_type_id=self.table._migration_couch_id,
            fields={
                'name': FieldList(field_list=[FixtureItemField(field_value='Thalassa')]),
                'planet': FieldList(field_list=[FixtureItemField(field_value='Neptune')]),
            },
        ).save()
        FixtureDataItem(
            domain=self.domain,
            data_type_id=self.table._migration_couch_id,
            fields={
                'name': FieldList(field_list=[FixtureItemField(field_value='Naiad')]),
                'planet': FieldList(field_list=[FixtureItemField(field_value='Neptune')]),
            },
        ).save()
        clear_fixture_quickcache(self.domain, LookupTable.objects.by_domain(self.domain))
        clear_fixture_cache(self.domain)
        update_fixture(self.domain_link, self.table.tag)

        # Linked domain should still have one table, with the new rows
        linked_types = LookupTable.objects.by_domain(self.linked_domain)
        self.assertEqual(1, len(linked_types))
        self.assertEqual('moons', linked_types[0].tag)
        items = get_fixture_items_for_data_type(self.linked_domain, linked_types[0]._migration_couch_id)
        self.assertEqual(4, len(items))
        self.assertEqual([
            'Europa', 'Io', 'Jupiter', 'Jupiter', 'Naiad', 'Neptune', 'Neptune', 'Thalassa',
        ], sorted([
            i.fields[field_name].field_list[0].field_value for i in items for field_name in i.fields.keys()
        ]))

    def test_update_global_only(self):
        other_table = LookupTable(
            domain=self.domain,
            tag='jellyfish',
            is_global=False,
            fields=[
                TypeField(name="genus"),
                TypeField(name="species"),
            ],
        )
        other_table.save()
        clear_fixture_quickcache(self.domain, LookupTable.objects.by_domain(self.domain))
        clear_fixture_cache(self.domain)

        with self.assertRaises(UnsupportedActionError):
            update_fixture(self.domain_link, 'jellyfish')
