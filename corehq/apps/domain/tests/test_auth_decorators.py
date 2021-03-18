import base64
from functools import wraps

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, TestCase, RequestFactory
from mock import mock

from corehq.apps.domain.decorators import _login_or_challenge, api_auth
from corehq.apps.domain.shortcuts import create_domain
from corehq.apps.users.models import WebUser, CommCareUser

SUCCESS = 'it worked!'
CHECK_FAILED = 'check failed'


def sample_view(request, *args, **kwargs):
    return SUCCESS


def challenge(check, user):
    def decorator(view):
        def wrapper(request, *args, **kwargs):
            auth = check(request)
            if auth:
                if user:
                    request.user = user
                return view(request, *args, **kwargs)

            return CHECK_FAILED
        return wrapper
    return decorator


def get_passing_decorator(user=None):
    return challenge(lambda request: True, user)


def get_failing_decorator(user=None):
    return challenge(lambda request: False, user)


passing_decorator = get_passing_decorator()
failing_decorator = get_failing_decorator()


class LoginOrChallengeTest(SimpleTestCase):

    def test_challenge(self):
        request = object()

        test = passing_decorator(sample_view)
        self.assertEqual(SUCCESS, test(request))

    def test_failing_challenge(self):
        request = object()
        test = failing_decorator(sample_view)
        self.assertEqual(CHECK_FAILED, test(request))


def _get_request(user=AnonymousUser()):
    request = RequestFactory().get('/foobar/')
    # because of session auth,  we still have to populate an AnonymousUser user on the request
    # in all scenarios because the challenge decorator isn't actually called before the user is accessed
    request.user = user
    return request


class AuthTestMixin:

    def assertForbidden(self, result):
        self.assertNotEqual(SUCCESS, result)


class LoginOrChallengeDBTest(TestCase, AuthTestMixin):
    domain_name = 'auth-challenge-test'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.domain = create_domain(cls.domain_name)
        cls.web_user = WebUser.create(cls.domain_name, 'test@dimagi.com', 'secret', None, None)
        cls.web_django_user = cls.web_user.get_django_user()
        cls.commcare_user = CommCareUser.create(cls.domain_name, 'test', 'secret', None, None)
        cls.commcare_django_user = cls.commcare_user.get_django_user()

    @classmethod
    def tearDownClass(cls):
        # domain deletion also deletes users and such
        cls.domain.delete()
        super().tearDownClass()

    def _get_test_for_web_user(self, allow_cc_users, allow_sessions, require_domain=True):
        web_decorator = _login_or_challenge(get_passing_decorator(self.web_django_user),
                                            allow_cc_users=allow_cc_users,
                                            allow_sessions=allow_sessions,
                                            require_domain=require_domain)
        return web_decorator(sample_view)

    def _get_test_for_cc_user(self, allow_cc_users, allow_sessions, require_domain=True):
        cc_decorator = _login_or_challenge(get_passing_decorator(self.commcare_django_user),
                                           allow_cc_users=allow_cc_users,
                                           allow_sessions=allow_sessions,
                                           require_domain=require_domain)
        return cc_decorator(sample_view)

    def test_no_user_set(self):
        # no matter what, no user = no success
        for allow_cc_users in (True, False):
            for allow_sessions in (True, False):
                for require_domain in (True, False):
                    decorator = _login_or_challenge(passing_decorator,
                                                    allow_cc_users=allow_cc_users,
                                                    allow_sessions=allow_sessions,
                                                    require_domain=require_domain)
                    test = decorator(sample_view)
                    request = _get_request()
                    self.assertForbidden(test(request, self.domain_name))

    def test_no_cc_users_no_sessions(self):
        allow_cc_users = False
        allow_sessions = False
        web_test = self._get_test_for_web_user(allow_cc_users=allow_cc_users, allow_sessions=allow_sessions)
        mobile_test = self._get_test_for_cc_user(allow_cc_users=allow_cc_users, allow_sessions=allow_sessions)

        self.assertEqual(SUCCESS, web_test(_get_request(), self.domain_name))

        self.assertForbidden(mobile_test(_get_request(), self.domain_name))

    def test_no_cc_users_with_sessions(self):
        # with sessions, we just assume the user is already on the request, so the decorator doesn't matter
        decorator = _login_or_challenge(passing_decorator, allow_cc_users=False, allow_sessions=True)
        test = decorator(sample_view)
        web_request = _get_request(self.web_django_user)
        mobile_request = _get_request(self.commcare_django_user)

        self.assertEqual(SUCCESS, test(web_request, self.domain_name))
        # note: this behavior is surprising and arguably incorrect, but just documenting it here for now
        self.assertEqual(SUCCESS, test(mobile_request, self.domain_name))

    def test_with_cc_users(self):
        with_sessions = _login_or_challenge(passing_decorator, allow_cc_users=True, allow_sessions=True)
        no_sessions = _login_or_challenge(passing_decorator, allow_cc_users=True, allow_sessions=False)
        for decorator in [with_sessions, no_sessions]:
            test = decorator(sample_view)
            request = _get_request(self.web_django_user)
            self.assertEqual(SUCCESS, test(request, self.domain_name))

            request = _get_request(self.commcare_django_user)
            self.assertEqual(SUCCESS, test(request, self.domain_name))

    def test_no_domain_no_sessions(self):
        allow_cc_users = True
        allow_sessions = False
        require_domain = False
        web_test = self._get_test_for_web_user(allow_cc_users=allow_cc_users, allow_sessions=allow_sessions,
                                               require_domain=require_domain)
        mobile_test = self._get_test_for_cc_user(allow_cc_users=allow_cc_users, allow_sessions=allow_sessions,
                                                 require_domain=require_domain)

        self.assertEqual(SUCCESS, web_test(_get_request()))
        self.assertEqual(SUCCESS, mobile_test(_get_request()))

    def test_no_domain_with_sessions(self):
        decorator = _login_or_challenge(passing_decorator, allow_cc_users=True, allow_sessions=True,
                                        require_domain=False)
        test = decorator(sample_view)

        request = _get_request(self.web_django_user)
        self.assertEqual(SUCCESS, test(request))

        request = _get_request(self.commcare_django_user)
        self.assertEqual(SUCCESS, test(request))


def mock_successful_auth(allow_cc_users=False, allow_sessions=True, require_domain=True):
    def _outer(fn):
        @wraps(fn)
        def inner(request, *args, **kwargs):
            return fn(request, *args, **kwargs)

        return inner
    return _outer


class ApiAuthTest(SimpleTestCase, AuthTestMixin):
    domain_name = 'api-auth-test'

    def test_api_auth_no_auth(self):
        decorated_view = api_auth(sample_view)
        request = _get_request()
        # result = decorated_view(request, self.domain_name)
        self.assertForbidden(decorated_view(request, self.domain_name))

    @mock.patch('corehq.apps.domain.decorators.login_or_oauth2_ex', mock_successful_auth)
    def test_api_auth_oauth(self):
        decorated_view = api_auth(sample_view)
        request = _get_request()
        # fake oauth header
        request.META['HTTP_AUTHORIZATION'] = 'bearer myToken'
        self.assertEqual(SUCCESS, decorated_view(request, self.domain_name))
