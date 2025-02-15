from dimagi.utils.chunked import chunked
from dimagi.utils.couch.database import iter_bulk_delete

from corehq.util.couch_helpers import paginate_view
from corehq.util.quickcache import quickcache
from corehq.util.test_utils import unit_testing_only


def count_fixture_data_types(domain):
    from corehq.apps.fixtures.models import FixtureDataType
    num_fixtures = FixtureDataType.get_db().view(
        'by_domain_doc_type_date/view',
        startkey=[domain, 'FixtureDataType'],
        endkey=[domain, 'FixtureDataType', {}],
        reduce=True,
        group_level=2,
    ).first()
    return num_fixtures['value'] if num_fixtures is not None else 0


@quickcache(['domain'], timeout=30 * 60, skip_arg='bypass_cache')
def get_fixture_data_types(domain, bypass_cache=False):
    from corehq.apps.fixtures.models import FixtureDataType
    return list(FixtureDataType.view(
        'by_domain_doc_type_date/view',
        endkey=[domain, 'FixtureDataType'],
        startkey=[domain, 'FixtureDataType', {}],
        reduce=False,
        include_docs=True,
        descending=True,
    ))


def get_fixture_data_type_by_tag(domain, tag):
    data_types = get_fixture_data_types(domain)
    for data_type in data_types:
        if data_type.tag == tag:
            return data_type
    return None


@quickcache(['domain', 'data_type_id'], timeout=60 * 60, memoize_timeout=60, skip_arg='bypass_cache')
def get_fixture_items_for_data_type(domain, data_type_id, bypass_cache=False):
    from corehq.apps.fixtures.models import FixtureDataItem
    return list(FixtureDataItem.view(
        'fixtures/data_items_by_domain_type',
        startkey=[domain, data_type_id],
        endkey=[domain, data_type_id, {}],
        reduce=False,
        include_docs=True,
    ))


def delete_fixture_items_for_data_type(domain, data_type_id):
    from corehq.apps.fixtures.models import FixtureDataItem, LookupTableRow
    db = FixtureDataItem.get_db()
    items = paginate_view(
        db,
        'fixtures/data_items_by_domain_type',
        chunk_size=1000,
        startkey=[domain, data_type_id],
        endkey=[domain, data_type_id, {}],
        reduce=False,
    )
    for chunk in chunked(items, 1000, list):
        ids = [i["id"] for i in chunk]
        iter_bulk_delete(db, ids)
        LookupTableRow.objects.filter(id__in=ids).delete()


def iter_fixture_items_for_data_type(domain, data_type_id, wrap=True):
    from corehq.apps.fixtures.models import FixtureDataItem
    for row in paginate_view(
            FixtureDataItem.get_db(),
            'fixtures/data_items_by_domain_type',
            chunk_size=1000,
            startkey=[domain, data_type_id],
            endkey=[domain, data_type_id, {}],
            reduce=False,
            include_docs=True
    ):
        if wrap:
            yield FixtureDataItem.wrap(row['doc'])
        else:
            yield row['doc']


def count_fixture_items(domain, data_type_id):
    from corehq.apps.fixtures.models import FixtureDataItem
    return FixtureDataItem.view(
        'fixtures/data_items_by_domain_type',
        startkey=[domain, data_type_id],
        endkey=[domain, data_type_id, {}],
        reduce=True,
    ).first()['value']


def get_owner_ids_by_type(domain, owner_type, data_item_id):
    from corehq.apps.fixtures.models import FixtureOwnership
    assert owner_type in FixtureOwnership.owner_type.choices, \
        "Owner type must be in {}".format(FixtureOwnership.owner_type.choices)
    return FixtureOwnership.get_db().view(
        'fixtures/ownership',
        key=[domain, '{} by data_item'.format(owner_type), data_item_id],
        reduce=False,
        wrapper=lambda r: r['value']
    )


@unit_testing_only
def delete_all_fixture_data_types():
    from corehq.apps.fixtures.models import FixtureDataType

    results = FixtureDataType.get_db().view('fixtures/data_types_by_domain_tag', reduce=False).all()
    for result in results:
        try:
            fixture_data_type = FixtureDataType.get(result['id'])
        except Exception:
            pass
        else:
            fixture_data_type.delete()


@unit_testing_only
def delete_all_fixture_data(domain_name=None):
    from .couchmodels import FixtureDataType, FixtureDataItem, FixtureOwnership

    def delete_all(doc_class):
        view, key = get_view_and_key(doc_class)
        db = doc_class.get_db()
        docs = [r["doc"] for r in db.view(
            view,
            startkey=key,
            endkey=key + [{}],
            include_docs=True,
            reduce=False
        ).all()]
        if docs:
            db.bulk_delete(docs, empty_on_delete=False)

    if domain_name:
        def get_view_and_key(doc_class):
            return "by_domain_doc_type_date/view", [domain_name, doc_class.__name__]
    else:
        def get_view_and_key(doc_class):
            return "all_docs/by_doc_type", [doc_class.__name__]

    delete_all(FixtureOwnership),
    delete_all(FixtureDataItem),
    delete_all(FixtureDataType),
