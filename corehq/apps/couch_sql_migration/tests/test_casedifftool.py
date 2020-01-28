from contextlib import contextmanager
from datetime import timedelta

import attr
from gevent.pool import Pool
from mock import patch

from corehq.apps.domain.shortcuts import create_domain
from corehq.apps.tzmigration.timezonemigration import MISSING
from corehq.form_processor.utils.general import (
    clear_local_domain_sql_backend_override,
)
from corehq.util.test_utils import capture_log_output

from .test_migration import BaseMigrationTestCase, Diff, make_test_form
from .. import casediff
from .. import casedifftool as mod
from ..statedb import open_state_db


class TestCouchSqlDiff(BaseMigrationTestCase):

    @classmethod
    def setUpClass(cls):
        cls.pool_mock = patch.object(mod, "Pool", MockPool)
        cls.pool_mock.start()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.pool_mock.stop()

    def test_diff(self):
        self.submit_form(make_test_form("form-1", case_id="case-1"))
        self._do_migration(case_diff="none")
        clear_local_domain_sql_backend_override(self.domain_name)
        with self.augmented_couch_case("case-1") as case:
            case.age = '35'
            case.save()
            self.do_case_diffs()
        self._compare_diffs([
            ('CommCareCase', Diff('diff', ['age'], old='35', new='27')),
        ])

    def test_diff_specific_case(self):
        self.submit_form(make_test_form("form-1", case_id="case-1"))
        self._do_migration(case_diff="none")
        clear_local_domain_sql_backend_override(self.domain_name)
        with self.augmented_couch_case("case-1") as case:
            case.age = '35'
            case.save()
            self.do_case_diffs(cases="case-1")
        self._compare_diffs([
            ('CommCareCase', Diff('diff', ['age'], old='35', new='27')),
        ])

    def test_pending_diff(self):
        def diff_none(case_ids, log_cases=None):
            return casediff.DiffData([])
        self.submit_form(make_test_form("form-1", case_id="case-1"))
        self._do_migration(case_diff='none')
        clear_local_domain_sql_backend_override(self.domain_name)
        with self.augmented_couch_case("case-1") as case:
            case.age = '35'
            case.save()
            with patch("corehq.apps.couch_sql_migration.casediff.diff_cases", diff_none):
                result = self.do_case_diffs()
            self.assertEqual(result, mod.PENDING_WARNING)
            self.do_case_diffs(cases="pending")
        self._compare_diffs([
            ('CommCareCase', Diff('diff', ['age'], old='35', new='27')),
        ])

    def test_live_diff(self):
        # do not diff case modified since most recent case created in SQL
        self.submit_form(make_test_form("form-1", case_id="case-1"), timedelta(minutes=-90))
        self.submit_form(make_test_form("form-2", case_id="case-1", age=35))
        self._do_migration(live=True, chunk_size=1, case_diff="none")
        self.assert_backend("sql")
        case = self._get_case("case-1")
        self.assertEqual(case.dynamic_case_properties()["age"], '27')
        self.do_case_diffs(live=True)
        self._compare_diffs([])

    def test_failed_diff(self):
        self.pool_mock.stop()
        self.addCleanup(self.pool_mock.start)
        self.submit_form(make_test_form("form-1", case_id="case-1"))
        self._do_migration(case_diff="none")
        # patch init_worker to make subprocesses use the same database
        # connections as this process (which is operating in a transaction)
        init_worker_path = "corehq.apps.couch_sql_migration.casedifftool.init_worker"
        with patch(init_worker_path, mod.global_diff_state), \
                patch("corehq.apps.couch_sql_migration.casediff.diff_case") as mock, \
                capture_log_output("corehq.apps.couch_sql_migration.parallel") as log:
            mock.side_effect = Exception("diff failed!")
            self.do_case_diffs()
        logs = log.get_output()
        self.assertIn("error processing item in worker", logs)
        self.assertIn("Exception: diff failed!", logs)
        self._compare_diffs([])
        db = open_state_db(self.domain_name, self.state_dir)
        self.assertEqual(list(db.iter_undiffed_case_ids()), ["case-1"])

    def test_reconcile_transaction_order(self):
        from ..rebuildcase import SortTransactionsRebuild
        form1 = make_test_form("form-1", age="33", date="2016-08-04T18:25:56.656Z")
        form2 = make_test_form("form-2", age="32", date="2015-08-04T18:25:56.656Z")
        self.submit_form(form1)
        self.submit_form(form2)
        self.assertEqual(self._get_case("test-case").age, "33")
        with self.diff_without_rebuild():
            self._do_migration(case_diff="local")
        self._compare_diffs([
            ('CommCareCase', Diff('diff', ['age'], old='33', new='32')),
        ])
        clear_local_domain_sql_backend_override(self.domain_name)
        self.do_case_diffs()
        sql_case = self._get_case("test-case")
        self.assertEqual(sql_case.dynamic_case_properties()["age"], "33")
        self._compare_diffs([], ignore_fail=True)
        details = sql_case.transactions[-1].details
        self.assertEqual(details["reason"], SortTransactionsRebuild._REASON)
        server_dates = details["original_server_dates"]
        self.assertEqual(len(server_dates), 1, server_dates)

    def test_couch_with_missing_forms(self):
        form1 = make_test_form("form-1", age="33", date="2016-08-04T18:25:56.656Z")
        form2 = make_test_form("form-2", age="32", date="2015-08-04T18:25:56.656Z")
        self.submit_form(THING_FORM)
        self.submit_form(form1)
        self.submit_form(form2)
        case = self._get_case("test-case")
        self.assertEqual(case.age, "33")
        self.assertEqual(case.thing, "1")
        del case.thing
        case.actions = [a for a in case.actions if a.form_id != "thing"]
        case.save()
        with self.assertRaises(AttributeError):
            self._get_case("test-case").thing
        with self.diff_without_rebuild():
            self._do_migration(case_diff="local")
        self._compare_diffs([
            ('CommCareCase', Diff('diff', ['age'], old='33', new='32')),
            ('CommCareCase', Diff('missing', ['thing'], old=MISSING, new='1')),
        ])
        clear_local_domain_sql_backend_override(self.domain_name)
        self.do_case_diffs()
        sql_case = self._get_case("test-case")
        self.assertEqual(sql_case.dynamic_case_properties()["age"], "33")
        self._compare_diffs([], ignore_fail=True)

    def test_diff_case_with_wrong_domain(self):
        wrong_domain = create_domain("wrong")
        self.addCleanup(wrong_domain.delete)
        self.submit_form(make_test_form("form-1"), domain="wrong")
        self._do_migration(case_diff="none", domain="wrong")
        self._do_migration(case_diff="none")
        clear_local_domain_sql_backend_override(self.domain_name)
        with capture_log_output("corehq.apps.couch_sql_migration") as log, \
                self.augmented_couch_case("test-case") as case:
            # modify case so it would have a diff (if it were diffed)
            case.age = '35'
            case.save()
            # try to diff case in wrong domain
            self.do_case_diffs(cases="test-case")
        self._compare_diffs([
            ('CommCareCase', Diff('diff', ['domain'], old='wrong', new=self.domain_name)),
        ])
        logs = log.get_output()
        self.assertIn("couch case test-case has wrong domain: wrong", logs)

    def do_case_diffs(self, live=False, cases=None):
        migrator = mod.get_migrator(self.domain_name, self.state_dir, live)
        return mod.do_case_diffs(migrator, cases, stop=False, batch_size=100)

    @contextmanager
    def augmented_couch_case(self, case_id):
        case = self._get_case(case_id)
        with self.diff_without_rebuild():
            yield case


@attr.s
class MockPool:
    """Pool that uses greenlets rather than processes"""
    initializer = attr.ib()  # not used
    initargs = attr.ib()
    processes = attr.ib(default=None)
    maxtasksperchild = attr.ib(default=None)
    pool = attr.ib(factory=Pool, init=False)

    def imap_unordered(self, *args, **kw):
        with mod.global_diff_state(*self.initargs):
            yield from self.pool.imap_unordered(*args, **kw)


THING_FORM = """
<?xml version="1.0" ?>
<data
    name="Thing"
    uiVersion="1"
    version="11"
    xmlns="http://openrosa.org/formdesigner/thing-form"
    xmlns:jrm="http://dev.commcarehq.org/jr/xforms"
>
    <thing>1</thing>
    <n0:case
        case_id="test-case"
        date_modified="2014-08-04T18:25:56.656Z"
        user_id="a362027f228d"
        xmlns:n0="http://commcarehq.org/case/transaction/v2"
    >
        <n0:create>
            <n0:case_name>Thing</n0:case_name>
            <n0:owner_id>a362027f228d</n0:owner_id>
            <n0:case_type>testing</n0:case_type>
        </n0:create>
        <n0:update>
            <n0:thing>1</n0:thing>
        </n0:update>
    </n0:case>
    <n1:meta xmlns:n1="http://openrosa.org/jr/xforms">
        <n1:deviceID>cloudcare</n1:deviceID>
        <n1:timeStart>2014-07-13T11:20:11.381Z</n1:timeStart>
        <n1:timeEnd>2014-08-04T18:25:56.656Z</n1:timeEnd>
        <n1:username>thing-1</n1:username>
        <n1:userID>a362027f228d</n1:userID>
        <n1:instanceID>thing</n1:instanceID>
        <n2:appVersion xmlns:n2="http://commcarehq.org/xforms">2.0</n2:appVersion>
    </n1:meta>
</data>
""".strip()
