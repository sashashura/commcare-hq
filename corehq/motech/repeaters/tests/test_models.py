from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from nose.tools import assert_in, assert_raises

from corehq.motech.const import ALGO_AES, BASIC_AUTH
from corehq.motech.models import ConnectionSettings
from corehq.motech.repeaters.dbaccessors import (
    delete_all_repeaters,
    get_all_repeater_docs,
)
from corehq.motech.utils import b64_aes_encrypt

from ..const import (
    MAX_ATTEMPTS,
    MAX_BACKOFF_ATTEMPTS,
    MIN_RETRY_WAIT,
    RECORD_CANCELLED_STATE,
    RECORD_FAILURE_STATE,
    RECORD_PENDING_STATE,
    RECORD_SUCCESS_STATE,
)
from ..models import (
    FormRepeater,
    RepeatRecord,
    Repeater,
    SQLFormRepeater,
    SQLRepeater,
    are_repeat_records_migrated,
    format_response,
    get_all_repeater_types,
    is_response,
)
from .data.repeaters import repeater_test_data

DOMAIN = 'test-domain'

ALL_REPEATERS = [
    'FormRepeater',
    'CaseRepeater',
    'CreateCaseRepeater',
    'UpdateCaseRepeater',
    'ReferCaseRepeater',
    'DataRegistryCaseUpdateRepeater',
    'ShortFormRepeater',
    'AppStructureRepeater',
    'UserRepeater',
    'LocationRepeater',
    'FHIRRepeater',
    'OpenmrsRepeater',
    'Dhis2Repeater',
    'Dhis2EntityRepeater',
    'CaseExpressionRepeater'
]


def test_get_all_repeater_types():
    types = get_all_repeater_types()
    for cls in settings.REPEATER_CLASSES:
        name = cls.split('.')[-1]
        assert_in(name, types)


class RepeaterTestCase(TestCase):

    def setUp(self):
        super().setUp()
        url = 'https://www.example.com/api/'
        self.conn = ConnectionSettings.objects.create(domain=DOMAIN, name=url, url=url)
        self.repeater = FormRepeater(
            domain=DOMAIN,
            url=url,
        )
        self.repeater.save(sync_to_sql=False)
        self.sql_repeater = SQLFormRepeater(
            domain=DOMAIN,
            repeater_id=self.repeater.get_id,
            connection_settings=self.conn,
        )
        self.sql_repeater.save(sync_to_couch=False)

    def tearDown(self):
        self.repeater.delete()
        super().tearDown()


class RepeaterConnectionSettingsTests(RepeaterTestCase):

    def test_create_connection_settings(self):
        self.assertIsNone(self.repeater.connection_settings_id)
        conn = self.repeater.connection_settings

        self.assertIsNotNone(self.repeater.connection_settings_id)
        self.assertEqual(conn.name, self.repeater.url)

    def test_notify_addresses(self):
        self.repeater.notify_addresses_str = "admin@example.com"
        conn = self.repeater.connection_settings
        self.assertEqual(conn.notify_addresses, ["admin@example.com"])

    def test_notify_addresses_none(self):
        self.repeater.notify_addresses_str = None
        conn = self.repeater.connection_settings
        self.assertEqual(conn.notify_addresses, [])

    def test_password_encrypted(self):
        self.repeater.auth_type = BASIC_AUTH
        self.repeater.username = "terry"
        self.repeater.password = "Don't save me decrypted!"
        conn = self.repeater.connection_settings

        self.assertEqual(self.repeater.plaintext_password, conn.plaintext_password)
        # repeater.password was saved decrypted; conn.password is not:
        self.assertNotEqual(self.repeater.password, conn.password)

    def test_password_bug(self):
        self.repeater.auth_type = BASIC_AUTH
        self.repeater.username = "terry"
        plaintext = "Don't save me decrypted!"
        ciphertext = b64_aes_encrypt(plaintext)
        bytestring_repr = f"b'{ciphertext}'"  # bug fixed by commit 3a900068
        self.repeater.password = f'${ALGO_AES}${bytestring_repr}'
        conn = self.repeater.connection_settings

        self.assertEqual(conn.plaintext_password, self.repeater.plaintext_password)


class TestSoftDeleteRepeaters(RepeaterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.all_sql_repeaters = [self.sql_repeater]
        for i in range(5):
            r = SQLFormRepeater(domain=DOMAIN, connection_settings=self.conn)
            self.all_sql_repeaters.append(r)

    def test_soft_deletion(self):
        for r in self.all_sql_repeaters:
            r.repeater_id = uuid4().hex
            r.save(sync_to_couch=False)
        self.assertEqual(SQLFormRepeater.objects.all().count(), 6)
        self.all_sql_repeaters[1].is_deleted = True
        self.all_sql_repeaters[1].save(sync_to_couch=False)
        self.all_sql_repeaters[0].is_deleted = True
        self.all_sql_repeaters[0].save(sync_to_couch=False)
        self.assertEqual(SQLFormRepeater.objects.all().count(), 4)
        self.assertEqual(
            set(SQLFormRepeater.objects.all().values_list('repeater_id', flat=True)),
            set([r.repeater_id for r in self.all_sql_repeaters if not r.is_deleted])
        )

    def test_repeatrs_retired_from_sql(self):
        for r in self.all_sql_repeaters:
            r.save()
        self.all_sql_repeaters[0].retire()
        self.all_sql_repeaters[4].retire()
        couch_repeater_count = len(get_all_repeater_docs())
        sql_repeater_count = SQLRepeater.objects.all().count()
        self.assertEqual(couch_repeater_count, sql_repeater_count)

    def test_repeatrs_retired_from_couch(self):
        for r in self.all_sql_repeaters:
            r.save()
        self.all_sql_repeaters[1].repeater.retire()
        self.all_sql_repeaters[2].repeater.retire()
        self.all_sql_repeaters[3].repeater.retire()

        couch_repeater_count = len(get_all_repeater_docs())
        sql_repeater_count = SQLRepeater.objects.all().count()
        self.assertEqual(couch_repeater_count, sql_repeater_count)

    def tearDown(self) -> None:
        delete_all_repeaters()
        return super().tearDown()


class TestRepeaterName(RepeaterTestCase):

    def test_migrated_name(self):
        """
        When ConnectionSettings are migrated from an old Repeater,
        ConnectionSettings.name is set to Repeater.url
        """
        connection_settings = self.repeater.connection_settings
        self.assertEqual(connection_settings.name, self.repeater.url)
        self.assertEqual(self.repeater.name, connection_settings.name)

    def test_repeater_name(self):
        connection_settings = ConnectionSettings.objects.create(
            domain=DOMAIN,
            name='Example Server',
            url='https://example.com/api/',
        )
        self.repeater.connection_settings_id = connection_settings.id
        self.repeater.save()

        self.assertEqual(self.repeater.name, connection_settings.name)


class TestSQLRepeatRecordOrdering(RepeaterTestCase):

    def setUp(self):
        super().setUp()
        self.sql_repeater.repeat_records.create(
            domain=DOMAIN,
            payload_id='eve',
            registered_at='1970-02-01',
        )

    def test_earlier_record_created_later(self):
        self.sql_repeater.repeat_records.create(
            domain=self.sql_repeater.domain,
            payload_id='lilith',
            # If Unix time starts on 1970-01-01, then I guess 1970-01-06
            # is Unix Rosh Hashanah, the sixth day of Creation, the day
            # [Lilith][1] and Adam were created from clay.
            # [1] https://en.wikipedia.org/wiki/Lilith
            registered_at='1970-01-06',
        )
        repeat_records = self.sql_repeater.repeat_records.all()
        self.assertEqual(repeat_records[0].payload_id, 'lilith')
        self.assertEqual(repeat_records[1].payload_id, 'eve')

    def test_later_record_created_later(self):
        self.sql_repeater.repeat_records.create(
            domain=self.sql_repeater.domain,
            payload_id='cain',
            registered_at='1995-01-06',
        )
        repeat_records = self.sql_repeater.repeat_records.all()
        self.assertEqual(repeat_records[0].payload_id, 'eve')
        self.assertEqual(repeat_records[1].payload_id, 'cain')


class TestConnectionSettingsSoftDelete(TestCase):

    def setUp(self):
        self.conn_1 = ConnectionSettings.objects.create(domain=DOMAIN, url='http://dummy1.com')
        self.conn_2 = ConnectionSettings.objects.create(domain=DOMAIN, url='http://dummy2.com')
        return super().setUp()

    def test_soft_delete(self):
        self.conn_1.soft_delete()
        self.assertEqual(ConnectionSettings.objects.all().count(), 1)
        self.assertEqual(ConnectionSettings.objects.all()[0].id, self.conn_2.id)


class RepeaterManagerTests(RepeaterTestCase):

    def test_all_ready_no_repeat_records(self):
        sql_repeaters = SQLRepeater.objects.all_ready()
        self.assertEqual(len(sql_repeaters), 0)

    def test_all_ready_pending_repeat_record(self):
        with make_repeat_record(self.sql_repeater, RECORD_PENDING_STATE):
            sql_repeaters = SQLRepeater.objects.all_ready()
            self.assertEqual(len(sql_repeaters), 1)
            self.assertEqual(sql_repeaters[0].id, self.sql_repeater.id)

    def test_all_ready_failed_repeat_record(self):
        with make_repeat_record(self.sql_repeater, RECORD_FAILURE_STATE):
            sql_repeaters = SQLRepeater.objects.all_ready()
            self.assertEqual(len(sql_repeaters), 1)
            self.assertEqual(sql_repeaters[0].id, self.sql_repeater.id)

    def test_all_ready_succeeded_repeat_record(self):
        with make_repeat_record(self.sql_repeater, RECORD_SUCCESS_STATE):
            sql_repeaters = SQLRepeater.objects.all_ready()
            self.assertEqual(len(sql_repeaters), 0)

    def test_all_ready_cancelled_repeat_record(self):
        with make_repeat_record(self.sql_repeater, RECORD_CANCELLED_STATE):
            sql_repeaters = SQLRepeater.objects.all_ready()
            self.assertEqual(len(sql_repeaters), 0)

    def test_all_ready_paused(self):
        with make_repeat_record(self.sql_repeater, RECORD_PENDING_STATE), \
                pause(self.sql_repeater):
            sql_repeaters = SQLRepeater.objects.all_ready()
            self.assertEqual(len(sql_repeaters), 0)

    def test_all_ready_next_future(self):
        in_five_mins = timezone.now() + timedelta(minutes=5)
        with make_repeat_record(self.sql_repeater, RECORD_PENDING_STATE), \
                set_next_attempt_at(self.sql_repeater, in_five_mins):
            sql_repeaters = SQLRepeater.objects.all_ready()
            self.assertEqual(len(sql_repeaters), 0)

    def test_all_ready_next_past(self):
        five_mins_ago = timezone.now() - timedelta(minutes=5)
        with make_repeat_record(self.sql_repeater, RECORD_PENDING_STATE), \
                set_next_attempt_at(self.sql_repeater, five_mins_ago):
            sql_repeaters = SQLRepeater.objects.all_ready()
            self.assertEqual(len(sql_repeaters), 1)
            self.assertEqual(sql_repeaters[0].id, self.sql_repeater.id)


@contextmanager
def make_repeat_record(sql_repeater, state):
    repeat_record = sql_repeater.repeat_records.create(
        domain=sql_repeater.domain,
        payload_id=str(uuid4()),
        state=state,
        registered_at=timezone.now()
    )
    try:
        yield repeat_record
    finally:
        repeat_record.delete()


@contextmanager
def pause(sql_repeater):
    sql_repeater.is_paused = True
    sql_repeater.save()
    try:
        yield
    finally:
        sql_repeater.is_paused = False
        sql_repeater.save()


@contextmanager
def set_next_attempt_at(sql_repeater, when):
    sql_repeater.next_attempt_at = when
    sql_repeater.save()
    try:
        yield
    finally:
        sql_repeater.next_attempt_at = None
        sql_repeater.save()


class ResponseMock:
    pass


class IsResponseTests(SimpleTestCase):

    def test_has_text(self):
        resp = ResponseMock()
        resp.text = '<h1>Hello World</h1>'
        self.assertFalse(is_response(resp))

    def test_has_status_code(self):
        resp = ResponseMock()
        resp.status_code = 504
        self.assertFalse(is_response(resp))

    def test_has_reason(self):
        resp = ResponseMock()
        resp.reason = 'Gateway Timeout'
        self.assertFalse(is_response(resp))

    def test_has_status_code_and_reason(self):
        resp = ResponseMock()
        resp.status_code = 504
        resp.reason = 'Gateway Timeout'
        self.assertTrue(is_response(resp))


class FormatResponseTests(SimpleTestCase):

    def test_non_response(self):
        resp = ResponseMock()
        self.assertIsNone(format_response(resp))

    def test_no_text(self):
        resp = ResponseMock()
        resp.status_code = 504
        resp.reason = 'Gateway Timeout'
        self.assertEqual(format_response(resp), '504: Gateway Timeout')

    def test_with_text(self):
        resp = ResponseMock()
        resp.status_code = 200
        resp.reason = 'OK'
        resp.text = '<h1>Hello World</h1>'
        self.assertEqual(format_response(resp), '200: OK\n'
                                                '<h1>Hello World</h1>')


class AddAttemptsTests(RepeaterTestCase):

    def setUp(self):
        super().setUp()
        self.just_now = timezone.now()
        self.sql_repeater.next_attempt_at = self.just_now
        self.sql_repeater.save()
        self.repeat_record = self.sql_repeater.repeat_records.create(
            domain=DOMAIN,
            payload_id='eggs',
            registered_at=timezone.now(),
        )

    def test_add_success_attempt_true(self):
        self.repeat_record.add_success_attempt(response=True)
        self.assertEqual(self.repeat_record.state, RECORD_SUCCESS_STATE)
        self.assertIsNone(self.sql_repeater.next_attempt_at)
        self.assertEqual(self.repeat_record.num_attempts, 1)
        self.assertEqual(self.repeat_record.attempts[0].state,
                         RECORD_SUCCESS_STATE)
        self.assertEqual(self.repeat_record.attempts[0].message, '')

    def test_add_success_attempt_200(self):
        resp = ResponseMock()
        resp.status_code = 200
        resp.reason = 'OK'
        resp.text = '<h1>Hello World</h1>'
        self.repeat_record.add_success_attempt(response=resp)
        self.assertEqual(self.repeat_record.state, RECORD_SUCCESS_STATE)
        self.assertIsNone(self.sql_repeater.next_attempt_at)
        self.assertEqual(self.repeat_record.num_attempts, 1)
        self.assertEqual(self.repeat_record.attempts[0].state,
                         RECORD_SUCCESS_STATE)
        self.assertEqual(self.repeat_record.attempts[0].message,
                         format_response(resp))

    def test_add_server_failure_attempt_fail(self):
        message = '504: Gateway Timeout'
        self.repeat_record.add_server_failure_attempt(message=message)
        self.assertEqual(self.repeat_record.state, RECORD_FAILURE_STATE)
        self.assertGreater(self.sql_repeater.last_attempt_at, self.just_now)
        self.assertEqual(self.sql_repeater.next_attempt_at,
                         self.sql_repeater.last_attempt_at + MIN_RETRY_WAIT)
        self.assertEqual(self.repeat_record.num_attempts, 1)
        self.assertEqual(self.repeat_record.attempts[0].state,
                         RECORD_FAILURE_STATE)
        self.assertEqual(self.repeat_record.attempts[0].message, message)
        self.assertEqual(self.repeat_record.attempts[0].traceback, '')

    def test_add_server_failure_attempt_cancel(self):
        message = '504: Gateway Timeout'
        while self.repeat_record.state != RECORD_CANCELLED_STATE:
            self.repeat_record.add_server_failure_attempt(message=message)

        self.assertGreater(self.sql_repeater.last_attempt_at, self.just_now)
        # Interval is MIN_RETRY_WAIT because attempts were very close together
        self.assertEqual(self.sql_repeater.next_attempt_at,
                         self.sql_repeater.last_attempt_at + MIN_RETRY_WAIT)
        self.assertEqual(self.repeat_record.num_attempts,
                         MAX_BACKOFF_ATTEMPTS + 1)
        attempts = list(self.repeat_record.attempts)
        expected_states = ([RECORD_FAILURE_STATE] * MAX_BACKOFF_ATTEMPTS
                           + [RECORD_CANCELLED_STATE])
        self.assertEqual([a.state for a in attempts], expected_states)
        self.assertEqual(attempts[-1].message, message)
        self.assertEqual(attempts[-1].traceback, '')

    def test_add_client_failure_attempt_fail(self):
        message = '409: Conflict'
        self.repeat_record.add_client_failure_attempt(message=message)
        self.assertEqual(self.repeat_record.state, RECORD_FAILURE_STATE)
        self.assertIsNone(self.sql_repeater.last_attempt_at)
        self.assertIsNone(self.sql_repeater.next_attempt_at)
        self.assertEqual(self.repeat_record.num_attempts, 1)
        self.assertEqual(self.repeat_record.attempts[0].state,
                         RECORD_FAILURE_STATE)
        self.assertEqual(self.repeat_record.attempts[0].message, message)
        self.assertEqual(self.repeat_record.attempts[0].traceback, '')

    def test_add_client_failure_attempt_cancel(self):
        message = '409: Conflict'
        while self.repeat_record.state != RECORD_CANCELLED_STATE:
            self.repeat_record.add_client_failure_attempt(message=message)
        self.assertIsNone(self.sql_repeater.last_attempt_at)
        self.assertIsNone(self.sql_repeater.next_attempt_at)
        self.assertEqual(self.repeat_record.num_attempts,
                         MAX_ATTEMPTS + 1)
        attempts = list(self.repeat_record.attempts)
        expected_states = ([RECORD_FAILURE_STATE] * MAX_ATTEMPTS
                           + [RECORD_CANCELLED_STATE])
        self.assertEqual([a.state for a in attempts], expected_states)
        self.assertEqual(attempts[-1].message, message)
        self.assertEqual(attempts[-1].traceback, '')

    def test_add_client_failure_attempt_no_retry(self):
        message = '422: Unprocessable Entity'
        while self.repeat_record.state != RECORD_CANCELLED_STATE:
            self.repeat_record.add_client_failure_attempt(message=message, retry=False)
        self.assertIsNone(self.sql_repeater.last_attempt_at)
        self.assertIsNone(self.sql_repeater.next_attempt_at)
        self.assertEqual(self.repeat_record.num_attempts, 1)
        self.assertEqual(self.repeat_record.attempts[0].state, RECORD_CANCELLED_STATE)
        self.assertEqual(self.repeat_record.attempts[0].message, message)
        self.assertEqual(self.repeat_record.attempts[0].traceback, '')

    def test_add_payload_exception_attempt(self):
        message = 'ValueError: Schema validation failed'
        tb_str = 'Traceback ...'
        self.repeat_record.add_payload_exception_attempt(message=message,
                                                         tb_str=tb_str)
        self.assertEqual(self.repeat_record.state, RECORD_CANCELLED_STATE)
        # Note: Our payload issues do not affect how we deal with their
        #       server issues:
        self.assertEqual(self.sql_repeater.next_attempt_at, self.just_now)
        self.assertEqual(self.repeat_record.num_attempts, 1)
        self.assertEqual(self.repeat_record.attempts[0].state,
                         RECORD_CANCELLED_STATE)
        self.assertEqual(self.repeat_record.attempts[0].message, message)
        self.assertEqual(self.repeat_record.attempts[0].traceback, tb_str)


class TestAreRepeatRecordsMigrated(RepeaterTestCase):

    def setUp(self):
        super().setUp()
        are_repeat_records_migrated.clear(DOMAIN)

    def test_no(self):
        is_migrated = are_repeat_records_migrated(DOMAIN)
        self.assertFalse(is_migrated)

    def test_yes(self):
        with make_repeat_record(self.sql_repeater, RECORD_PENDING_STATE):
            is_migrated = are_repeat_records_migrated(DOMAIN)
        self.assertTrue(is_migrated)


class TestSQLRepeaterConnectionSettings(RepeaterTestCase):

    def test_connection_settings_are_accessible(self):
        self.assertEqual(self.sql_repeater.connection_settings.url, 'https://www.example.com/api/')

    def test_used_connection_setting_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.sql_repeater.connection_settings.delete()


def test_attempt_forward_now_kwargs():
    rr = RepeatRecord()
    with assert_raises(TypeError):
        rr.attempt_forward_now(True)


def _create_repeater_data_map():
    repeater_map = {}
    for r in deepcopy(repeater_test_data):
        doc_type = r['doc_type']
        if not repeater_map.get(doc_type):
            couch_repeater = Repeater.wrap(r)
            couch_repeater.save()
            repeater_map[doc_type] = {
                'couch': couch_repeater,
                'sql': couch_repeater.sql_repeater
            }
    return repeater_map


class TestSQLRepeaterToJSON(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.conn = ConnectionSettings.objects.create(id=1, url='http://fake.com')
        cls.repeater_map = _create_repeater_data_map()

    @classmethod
    def tearDownClass(cls):
        for type, rep in cls.repeater_map.items():
            rep['couch'].delete()
        return super().tearDownClass()

    @classmethod
    def _clean_couch_json(cls, couch_json):
        couch_json['repeater_type'] = couch_json.pop('doc_type')
        couch_json['repeater_id'] = couch_json.pop('_id')
        couch_json['is_paused'] = couch_json.pop('paused')
        props_to_be_removed = [
            'base_doc', '_rev', 'url', 'auth_type', 'username', 'password', 'skip_cert_verify',
            'notify_addresses_str', 'last_success_at', 'failure_streak', 'started_at'
        ]
        for prop in props_to_be_removed:
            couch_json.pop(prop, None)
        return couch_json

    def test_repeater_config(self):
        for repeater_type in ALL_REPEATERS:
            couch_repeater = self.repeater_map[repeater_type]['couch']
            sql_repeater = self.repeater_map[repeater_type]['sql']
            sql_data = sql_repeater.to_json()
            couch_data = self._clean_couch_json(couch_repeater.to_json())

            self.assertEqual(sql_data, couch_data)
