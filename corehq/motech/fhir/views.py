from django.http import JsonResponse
from django.views.decorators.http import require_GET

from corehq import toggles
from corehq.apps.domain.decorators import (
    login_and_domain_required,
    require_superuser,
)
from corehq.form_processor.exceptions import CaseNotFound
from corehq.form_processor.interfaces.dbaccessors import CaseAccessors
from corehq.motech.fhir.models import FHIRResourceType, build_fhir_resource
from corehq.util.view_utils import absolute_reverse


@require_GET
@login_and_domain_required
@require_superuser
@toggles.FHIR_INTEGRATION.required_decorator()
def get_view(request, domain, resource_type, resource_id):
    try:
        case = CaseAccessors(domain).get_case(resource_id)
        if case.is_deleted:
            return JsonResponse(status=400, data={'message': f"Resource with ID {resource_id} was removed"})
    except CaseNotFound:
        return JsonResponse(status=400, data={'message': f"Could not find resource with ID {resource_id}"})

    if case.type not in (FHIRResourceType.objects.filter(domain=domain, name=resource_type).
                         values_list('case_type__name', flat=True)):
        return JsonResponse(status=400, data={'message': "Invalid Resource Type"})
    response = {
        'resourceType': resource_type,
        'id': resource_id
    }
    response.update(build_fhir_resource(case))
    return JsonResponse(response)


@require_GET
@login_and_domain_required
@require_superuser
@toggles.FHIR_INTEGRATION.required_decorator()
def search_view(request, domain, resource_type):
    patient_case_id = request.GET.get('patient_id')
    if not patient_case_id:
        return JsonResponse(status=400, data={'message': "Please pass patient_id"})
    case_accessor = CaseAccessors(domain)
    try:
        patient_case = case_accessor.get_case(patient_case_id)
        if patient_case.is_deleted:
            return JsonResponse(status=400, data={'message': f"Patient with ID {patient_case_id} was removed"})
    except CaseNotFound:
        return JsonResponse(status=400, data={'message': f"Could not find patient with ID {patient_case_id}"})

    case_types_for_resource_type = list(FHIRResourceType.objects.filter(domain=domain, name=resource_type).
                                        values_list('case_type__name', flat=True))
    if not case_types_for_resource_type:
        return JsonResponse(status=400,
                            data={'message': f"Resource type {resource_type} not available on {domain}"})

    cases = case_accessor.get_reverse_indexed_cases([patient_case_id],
                                                    case_types=case_types_for_resource_type, is_closed=False)
    response = {
        'resourceType': "Bundle",
        "type": "searchset",
        "entry": []
    }
    for case in cases:
        response["entry"].append({
            "fullUrl": absolute_reverse(get_view, args=(domain, resource_type, case.case_id)),
            "search": {
                "mode": "match"
            }
        })
    return JsonResponse(response)
