from datetime import datetime
from xml.etree import cElementTree as ElementTree

from django.db import models

from couchdbkit.exceptions import ResourceConflict, ResourceNotFound
from memoized import memoized

from dimagi.ext.couchdbkit import (
    BooleanProperty,
    DictProperty,
    Document,
    DocumentSchema,
    IntegerProperty,
    SchemaListProperty,
    StringListProperty,
    StringProperty,
)
from dimagi.utils.chunked import chunked
from dimagi.utils.couch.bulk import CouchTransaction

from corehq.apps.cachehq.mixins import QuickCachedDocumentMixin
from corehq.apps.fixtures.dbaccessors import (
    get_fixture_data_types_in_domain,
    get_fixture_items_for_data_type,
    get_owner_ids_by_type,
)
from corehq.apps.fixtures.exceptions import (
    FixtureException,
    FixtureTypeCheckError,
    FixtureVersionError,
)
from corehq.apps.fixtures.utils import (
    clean_fixture_field_name,
    get_fields_without_attributes,
    remove_deleted_ownerships,
)
from corehq.apps.groups.models import Group
from corehq.apps.locations.models import SQLLocation
from corehq.apps.users.models import CommCareUser
from corehq.util.xml_utils import serialize

FIXTURE_BUCKET = 'domain-fixtures'


class FixtureTypeField(DocumentSchema):
    field_name = StringProperty()
    properties = StringListProperty()
    is_indexed = BooleanProperty(default=False)


class FixtureDataType(QuickCachedDocumentMixin, Document):
    domain = StringProperty()
    is_global = BooleanProperty(default=False)
    tag = StringProperty()
    fields = SchemaListProperty(FixtureTypeField)
    item_attributes = StringListProperty()
    description = StringProperty()
    copy_from = StringProperty()

    @classmethod
    def wrap(cls, obj):
        if not obj["doc_type"] == "FixtureDataType":
            raise ResourceNotFound
        # Migrate fixtures without attributes on item-fields to fields with attributes
        if obj["fields"] and isinstance(obj['fields'][0], str):
            obj['fields'] = [{'field_name': f, 'properties': []} for f in obj['fields']]

        # Migrate fixtures without attributes on items to items with attributes
        if 'item_attributes' not in obj:
            obj['item_attributes'] = []

        return super(FixtureDataType, cls).wrap(obj)

    # support for old fields
    @property
    def fields_without_attributes(self):
        return get_fields_without_attributes(self.fields)

    @property
    def is_indexed(self):
        return any(f.is_indexed for f in self.fields)

    @classmethod
    def total_by_domain(cls, domain):
        from corehq.apps.fixtures.dbaccessors import \
            get_number_of_fixture_data_types_in_domain
        return get_number_of_fixture_data_types_in_domain(domain)

    @classmethod
    def by_domain(cls, domain):
        from corehq.apps.fixtures.dbaccessors import \
            get_fixture_data_types_in_domain
        return get_fixture_data_types_in_domain(domain)

    @classmethod
    def by_domain_tag(cls, domain, tag):
        return cls.view('fixtures/data_types_by_domain_tag', key=[domain, tag], reduce=False, include_docs=True, descending=True)

    @classmethod
    def fixture_tag_exists(cls, domain, tag):
        fdts = FixtureDataType.by_domain(domain)
        for fdt in fdts:
            if tag == fdt.tag:
                return fdt
        return False

    def recursive_delete(self, transaction):
        item_ids = []
        for item in FixtureDataItem.by_data_type(self.domain, self.get_id):
            transaction.delete(item)
            item_ids.append(item.get_id)
        for item_id_chunk in chunked(item_ids, 1000):
            transaction.delete_all(FixtureOwnership.for_all_item_ids(item_id_chunk, self.domain))
        transaction.delete(self)

    @classmethod
    def delete_fixtures_by_domain(cls, domain, transaction):
        for type in FixtureDataType.by_domain(domain):
            type.recursive_delete(transaction)

    def clear_caches(self):
        super(FixtureDataType, self).clear_caches()
        get_fixture_data_types_in_domain.clear(self.domain)


class FixtureItemField(DocumentSchema):
    """
        "field_value": "Delhi_IN_HIN",
        "properties": {"lang": "hin"}
    """
    field_value = StringProperty()
    properties = DictProperty()


class FieldList(DocumentSchema):
    """
        List of fields for different combinations of properties
    """
    field_list = SchemaListProperty(FixtureItemField)

    def to_api_json(self):
        value = self.to_json()
        del value['doc_type']
        for field in value['field_list']:
            del field['doc_type']
        return value


class FixtureDataItem(Document):
    """
    Example old Item:
        domain = "hq-domain"
        data_type_id = <id of state FixtureDataType>
        fields = {
            "country": "India",
            "state_name": "Delhi",
            "state_id": "DEL"
        }

    Example new Item with attributes:
        domain = "hq-domain"
        data_type_id = <id of state FixtureDataType>
        fields = {
            "country": {"field_list": [
                {"field_value": "India", "properties": {}},
            ]},
            "state_name": {"field_list": [
                {"field_value": "Delhi_IN_ENG", "properties": {"lang": "eng"}},
                {"field_value": "Delhi_IN_HIN", "properties": {"lang": "hin"}},
            ]},
            "state_id": {"field_list": [
                {"field_value": "DEL", "properties": {}}
            ]}
        }
    If one of field's 'properties' is an empty 'dict', the field has no attributes
    """
    domain = StringProperty()
    data_type_id = StringProperty()
    fields = DictProperty(FieldList)
    item_attributes = DictProperty()
    sort_key = IntegerProperty()

    @classmethod
    def wrap(cls, obj):
        if not obj["doc_type"] == "FixtureDataItem":
            raise ResourceNotFound
        if not obj["fields"]:
            return super(FixtureDataItem, cls).wrap(obj)

        # Migrate old basic fields to fields with attributes

        is_of_new_type = False
        fields_dict = {}

        def _is_new_type(field_val):
            old_types = (str, int, float)
            return field_val is not None and not isinstance(field_val, old_types)

        for field in obj['fields']:
            field_val = obj['fields'][field]
            if _is_new_type(field_val):
                # assumes all-or-nothing conversion of old types to new
                is_of_new_type = True
                break
            fields_dict[field] = {
                "field_list": [{
                    'field_value': str(field_val) if not isinstance(field_val, str) else field_val,
                    'properties': {}
                }]
            }
        if not is_of_new_type:
            obj['fields'] = fields_dict

        # Migrate fixture-items to have attributes
        if 'item_attributes' not in obj:
            obj['item_attributes'] = {}

        return super(FixtureDataItem, cls).wrap(obj)

    @property
    def fields_without_attributes(self):
        fields = {}
        for field in self.fields:
            # if the field has properties, a unique field_val can't be generated for FixtureItem
            if len(self.fields[field].field_list) > 1:
                raise FixtureVersionError("This method is not supported for fields with properties."
                                          " field '%s' has properties" % field)
            fields[field] = self.fields[field].field_list[0].field_value
        return fields

    @property
    def try_fields_without_attributes(self):
        """This is really just for the API"""
        try:
            return self.fields_without_attributes
        except FixtureVersionError:
            return {key: value.to_api_json()
                    for key, value in self.fields.items()}

    @property
    def data_type(self):
        if not hasattr(self, '_data_type'):
            self._data_type = FixtureDataType.get(self.data_type_id)
        return self._data_type

    def add_owner(self, owner, owner_type, transaction=None):
        assert(owner.domain == self.domain)
        with transaction or CouchTransaction() as transaction:
            o = FixtureOwnership(domain=self.domain, owner_type=owner_type, owner_id=owner.get_id, data_item_id=self.get_id)
            transaction.save(o)
        return o

    def remove_owner(self, owner, owner_type):
        for ownership in FixtureOwnership.view('fixtures/ownership',
            key=[self.domain, 'by data_item and ' + owner_type, self.get_id, owner.get_id],
            reduce=False,
            include_docs=True
        ):
            try:
                ownership.delete()
            except ResourceNotFound:
                # looks like it was already deleted
                pass
            except ResourceConflict:
                raise FixtureException((
                    "couldn't remove ownership {owner_id} for item {fixture_id} of type "
                    "{data_type_id} in domain {domain}. It was updated elsewhere"
                ).format(
                    owner_id=ownership._id,
                    fixture_id=self._id,
                    data_type_id=self.data_type_id,
                    domain=self.domain
                ))

    def add_user(self, user, transaction=None):
        return self.add_owner(user, 'user', transaction=transaction)

    def remove_user(self, user):
        return self.remove_owner(user, 'user')

    def add_group(self, group, transaction=None):
        return self.add_owner(group, 'group', transaction=transaction)

    def remove_group(self, group):
        return self.remove_owner(group, 'group')

    def add_location(self, location, transaction=None):
        return self.add_owner(location, 'location', transaction=transaction)

    def remove_location(self, location):
        return self.remove_owner(location, 'location')

    def type_check(self):
        fields = set(self.fields.keys())
        for field in self.data_type.fields:
            if field.field_name in fields:
                fields.remove(field)
            else:
                raise FixtureTypeCheckError("field %s not in fixture data %s" % (field.field_name, self.get_id))
        if fields:
            raise FixtureTypeCheckError("fields %s from fixture data %s not in fixture data type" % (', '.join(fields), self.get_id))

    def to_xml(self):
        xData = ElementTree.Element(self.data_type.tag)
        for attribute in self.data_type.item_attributes:
            try:
                xData.attrib[attribute] = serialize(self.item_attributes[attribute])
            except KeyError as e:
                # This should never occur, buf if it does, the OTA restore on mobile will fail and
                # this error would have been raised and email-logged.
                raise FixtureTypeCheckError(
                    "Table with tag %s has an item with id %s that doesn't have an attribute as defined in its types definition"
                    % (self.data_type.tag, self.get_id)
                )
        for field in self.data_type.fields:
            escaped_field_name = clean_fixture_field_name(field.field_name)
            if field.field_name not in self.fields:
                xField = ElementTree.SubElement(xData, escaped_field_name)
                xField.text = ""
            else:
                for field_with_attr in self.fields[field.field_name].field_list:
                    xField = ElementTree.SubElement(xData, escaped_field_name)
                    xField.text = serialize(field_with_attr.field_value)
                    for attribute in field_with_attr.properties:
                        val = field_with_attr.properties[attribute]
                        xField.attrib[attribute] = serialize(val)

        return xData

    def get_groups(self, wrap=True):
        group_ids = get_owner_ids_by_type(self.domain, 'group', self.get_id)
        if wrap:
            return set(Group.view(
                '_all_docs',
                keys=list(group_ids),
                include_docs=True,
            ))
        else:
            return set(group_ids)

    @property
    @memoized
    def groups(self):
        return self.get_groups()

    def get_users(self, wrap=True, include_groups=False):
        user_ids = set(get_owner_ids_by_type(self.domain, 'user', self.get_id))
        if include_groups:
            group_ids = self.get_groups(wrap=False)
        else:
            group_ids = set()
        users_in_groups = [
            group.get_users(only_commcare=True)
            for group in Group.view(
                '_all_docs',
                keys=list(group_ids),
                include_docs=True)]
        if wrap:
            return set(CommCareUser.view('_all_docs', keys=list(user_ids), include_docs=True)).union(*users_in_groups)
        else:
            return user_ids | set([user.get_id for user in users_in_groups])

    def get_all_users(self, wrap=True):
        return self.get_users(wrap=wrap, include_groups=True)

    @property
    @memoized
    def users(self):
        return self.get_users()

    @property
    @memoized
    def locations(self):
        loc_ids = get_owner_ids_by_type(self.domain, 'location', self.get_id)
        return SQLLocation.objects.filter(location_id__in=loc_ids)

    @classmethod
    def by_user(cls, user, wrap=True):
        group_ids = Group.by_user_id(user.user_id, wrap=False)
        loc_ids = user.sql_location.path if user.sql_location else []

        def make_keys(owner_type, ids):
            return [[user.domain, 'data_item by {}'.format(owner_type), id_]
                    for id_ in ids]

        fixture_ids = set(
            FixtureOwnership.get_db().view('fixtures/ownership',
                keys=(make_keys('user', [user.user_id]) +
                      make_keys('group', group_ids) +
                      make_keys('location', loc_ids)),
                reduce=False,
                wrapper=lambda r: r['value'],
            )
        )
        if wrap:
            results = cls.get_db().view('_all_docs', keys=list(fixture_ids), include_docs=True)

            # sort the results into those corresponding to real documents
            # and those corresponding to deleted or non-existent documents
            docs = []
            deleted_fixture_ids = set()

            for result in results:
                if result.get('doc'):
                    docs.append(cls.wrap(result['doc']))
                elif result.get('error'):
                    assert result['error'] == 'not_found'
                    deleted_fixture_ids.add(result['key'])
                else:
                    assert result['value']['deleted'] is True
                    deleted_fixture_ids.add(result['id'])
            if deleted_fixture_ids:
                # delete ownership documents pointing deleted/non-existent fixture documents
                # this cleanup is necessary since we used to not do this
                remove_deleted_ownerships.delay(list(deleted_fixture_ids), user.domain)
            return docs
        else:
            return fixture_ids

    @classmethod
    def by_group(cls, group, wrap=True):
        fixture_ids = cls.get_db().view('fixtures/ownership',
            key=[group.domain, 'data_item by group', group.get_id],
            reduce=False,
            wrapper=lambda r: r['value'],
            descending=True
        ).all()

        return cls.view('_all_docs', keys=list(fixture_ids), include_docs=True) if wrap else fixture_ids

    @classmethod
    def by_data_type(cls, domain, data_type, bypass_cache=False):
        return get_fixture_items_for_data_type(domain, _id_from_doc(data_type), bypass_cache)

    @classmethod
    def by_domain(cls, domain):
        return cls.view('fixtures/data_items_by_domain_type',
            startkey=[domain, {}],
            endkey=[domain],
            reduce=False,
            include_docs=True,
            descending=True
        )

    @classmethod
    def by_field_value(cls, domain, data_type, field_name, field_value):
        data_type_id = _id_from_doc(data_type)
        return cls.view('fixtures/data_items_by_field_value', key=[domain, data_type_id, field_name, field_value],
                        reduce=False, include_docs=True)

    @classmethod
    def get_item_list(cls, domain, tag):
        data_type = FixtureDataType.by_domain_tag(domain, tag).one()
        return cls.by_data_type(domain, data_type)

    @classmethod
    def get_indexed_items(cls, domain, tag, index_field):
        """
        Looks up an item list and converts to mapping from `index_field`
        to a dict of all fields for that item.

            fixtures = FixtureDataItem.get_indexed_items('my_domain',
                'item_list_tag', 'index_field')
            result = fixtures['index_val']['result_field']
        """
        fixtures = cls.get_item_list(domain, tag)
        return dict((f.fields_without_attributes[index_field], f.fields_without_attributes) for f in fixtures)

    def delete_ownerships(self, transaction):
        ownerships = FixtureOwnership.by_item_id(self.get_id, self.domain)
        transaction.delete_all(ownerships)

    def recursive_delete(self, transaction):
        self.delete_ownerships(transaction)
        transaction.delete(self)


def _id_from_doc(doc_or_doc_id):
    if isinstance(doc_or_doc_id, str):
        doc_id = doc_or_doc_id
    else:
        doc_id = doc_or_doc_id.get_id if doc_or_doc_id else None
    return doc_id


class FixtureOwnership(Document):
    domain = StringProperty()
    data_item_id = StringProperty()
    owner_id = StringProperty()
    owner_type = StringProperty(choices=['user', 'group', 'location'])

    @classmethod
    def by_item_id(cls, item_id, domain):
        ownerships = cls.view('fixtures/ownership',
            key=[domain, 'by data_item', item_id],
            include_docs=True,
            reduce=False,
        ).all()

        return ownerships

    @classmethod
    def for_all_item_ids(cls, item_ids, domain):
        ownerships = FixtureOwnership.view('fixtures/ownership',
            keys=[[domain, 'by data_item', item_id] for item_id in item_ids],
            include_docs=True,
            reduce=False
        ).all()

        return ownerships


class UserFixtureType(object):
    LOCATION = 1
    CHOICES = (
        (LOCATION, "Location"),
    )


class UserFixtureStatus(models.Model):
    """Keeps track of when a user needs to re-sync a fixture"""
    user_id = models.CharField(max_length=100, db_index=True)
    fixture_type = models.PositiveSmallIntegerField(choices=UserFixtureType.CHOICES)
    last_modified = models.DateTimeField()

    DEFAULT_LAST_MODIFIED = datetime.min

    class Meta(object):
        app_label = 'fixtures'
        unique_together = ("user_id", "fixture_type")
