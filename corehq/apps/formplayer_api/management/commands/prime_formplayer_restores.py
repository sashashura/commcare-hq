import csv
import inspect
import sys
from argparse import RawTextHelpFormatter
from concurrent import futures
from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand

from casexml.apps.phone.models import SyncLogSQL
from corehq.apps.formplayer_api.exceptions import FormplayerResponseException
from corehq.apps.formplayer_api.sync_db import sync_db
from corehq.apps.users.models import CouchUser
from corehq.apps.users.util import format_username, raw_username
from corehq.util.argparse_types import validate_integer
from corehq.util.log import with_progress_bar


class Command(BaseCommand):
    help = inspect.cleandoc(
        """Call the Formplayer sync API for users from CSV or matching criteria.
        Usage:
        
        Redirect stdout to file to allow viewing progress bar:
        %(prog)s [args] > output.csv

        ### With users in a CSV file ###
        
        CSV Columns: "domain, username, as_user"
        
        %(prog)s --from-csv path/to/users.csv
        
        ### Query DB for users ###
        
        %(prog)s --domains a b c --last-synced-days 2 --min-cases 500 --limit 1000
        
        Use "--dry-run" and "--dry-run-count" to gauge impact of command.
        """
    )

    def create_parser(self, *args, **kwargs):
        # required to get nice output from `--help`
        parser = super(Command, self).create_parser(*args, **kwargs)
        parser.formatter_class = RawTextHelpFormatter
        return parser

    def add_arguments(self, parser):
        parser.add_argument('--from-csv',
                            help='Path to CSV file. Columns "domain, username, as_user". When this is supplied '
                                 'only users in this file will be synced.')

        parser.add_argument('--domains', nargs='*', help='Match users in these domains.')
        parser.add_argument('--last-synced-days', action=validate_integer(gt=0, lt=31), default=1,
                            help='Match users who have synced within the given window. '
                                 'Defaults to 1 day ago. Max = 30.')
        parser.add_argument('--min-cases', action=validate_integer(gt=0),
                            help='Match users with this many cases or more.')

        parser.add_argument('--limit', action=validate_integer(gt=0), help='Limit the number of users matched.')
        parser.add_argument('-t', '--threads', action=validate_integer(gt=0), default=10,
                            help='Number of threads to use.')
        parser.add_argument('--dry-run', action='store_true', help='Only print the list of users.')
        parser.add_argument('--dry-run-count', action='store_true', help='Only print the count of matched users.')

    def handle(self, from_csv=None, domains=None, last_synced_days=None, min_cases=None, limit=None, **options):
        pool_size = options['threads']
        dry_run = options['dry_run']
        dry_run_count = options['dry_run_count']

        validate = True
        if from_csv:
            users = _get_users_from_csv(from_csv)
            if dry_run_count:
                print(f"\n{len(list(users))} users in CSV file '{from_csv}'")
                return
        else:
            domains = [domain.strip() for domain in domains if domain.strip()] if domains else None
            date_cutoff = datetime.utcnow().date() - relativedelta(days=last_synced_days)
            if dry_run_count:
                query = _get_user_db_query(domains, date_cutoff, min_cases, limit)
                print(f"\nMatched {query.count()} users for filters:")
                print(f"\tDomains: {domains or '---'}")
                print(f"\tSynced after: {date_cutoff}")
                print(f"\tMin cases: {min_cases or '---'}")
                print(f"\tLimit: {limit or '---'}")
                return

            users = _get_users_from_db(domains, date_cutoff, min_cases, limit)
            validate = False

        results = []
        with futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
            for user in users:
                results.append(executor.submit(process_row, user, validate, dry_run))

            for _ in with_progress_bar(futures.as_completed(results), length=len(results), stream=sys.stderr):
                pass

        if not results:
            print("\nNo users processed")


def process_row(row, validate, dry_run):
    def _log_message(msg, is_error=True):
        status = 'ERROR' if is_error else 'SUCCESS'
        row_csv = ','.join(row)
        print(f'{row_csv},{status},"{msg}"')

    domain, username, as_user = row
    if validate:
        user = CouchUser.get_by_username(username)
        if not user:
            _log_message("unknown username")
            return

        if as_user:
            as_username = format_username(as_user, domain) if '@' not in as_user else as_user
            restore_as_user = CouchUser.get_by_username(as_username)
            if not restore_as_user:
                _log_message("unknown as_user")

            if domain != restore_as_user.domain:
                _log_message("domain mismatch with as_user")

    if dry_run:
        _log_message("dry run success", is_error=False)
        return

    try:
        sync_db(domain, username, as_user or None)
    except FormplayerResponseException as e:
        _log_message(f"{e.response_json['exception']}")
    except Exception as e:
        _log_message(f"{e}")


def _get_users_from_csv(path):
    with open(path, 'r') as file:
        reader = csv.reader(file)

        for row in reader:
            if row != ["domain", "username", "as_user"]:  # skip header
                yield row


def _get_user_db_query(domains, date_cutoff, min_cases, limit):
    query = SyncLogSQL.objects.values(
        "domain", "user_id", "request_user_id"
    ).filter(date__gt=date_cutoff, is_formplayer=True).order_by("date")

    if domains:
        query = query.filter(domain__in=domains)

    if min_cases:
        query = query.filter(case_count__gte=min_cases)

    if limit:
        query = query[:limit]

    return query


def _get_users_from_db(domains, last_synced_days, min_cases, limit):
    query = _get_user_db_query(domains, last_synced_days, min_cases, limit)
    for row in query.iterator():
        request_user = CouchUser.get_by_user_id(row["request_user_id"]).username

        as_username = None
        if row["user_id"] == row["request_user_id"]:
            as_user = CouchUser.get_by_user_id(row["user_id"])
            as_username = raw_username(as_user.username) if as_user else None

        yield row["domain"], request_user, as_username
