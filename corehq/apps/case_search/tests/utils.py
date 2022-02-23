from corehq.apps.case_search.models import criteria_dict_to_criteria_list
from corehq.apps.case_search.utils import CaseSearchQueryBuilder


def get_case_search_query(domain, case_types, criteria_dict):
    """Helper function for tests. In the future this will handle conversion
    of the criteria from a dict to a list of Criteria objects"""
    criteria = criteria_dict_to_criteria_list(criteria_dict)
    return CaseSearchQueryBuilder(domain, case_types).build_query(criteria)
