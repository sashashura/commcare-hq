from dimagi.utils.couch.database import iter_bulk_delete

from corehq.util.couch_helpers import paginate_view
from corehq.util.test_utils import unit_testing_only


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
