from dimagi.utils.couch.database import iter_bulk_delete

from corehq.util.couch_helpers import paginate_view


def get_fixture_items_for_data_type(domain, data_type_id):
    from .couchmodels import FixtureDataItem
    return list(FixtureDataItem.view(
        'fixtures/data_items_by_domain_type',
        startkey=[domain, data_type_id],
        endkey=[domain, data_type_id, {}],
        reduce=False,
        include_docs=True,
    ))


def delete_fixture_items_for_data_type(domain, data_type_id):
    from .couchmodels import FixtureDataItem
    iter_bulk_delete(FixtureDataItem.get_db(), [
        i["_id"] for i in iter_fixture_items_for_data_type(domain, data_type_id)
    ])


def iter_fixture_items_for_data_type(domain, data_type_id, wrap=True):
    from .couchmodels import FixtureDataItem
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
