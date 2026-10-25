from copy import deepcopy


SEARCH_FIELDS = ('target_roles', 'location', 'work_modes', 'authorized_countries')


def static_search_criteria(owner):
    profile = getattr(owner, 'candidate_profile', None)
    return {field: deepcopy(getattr(profile, field, '' if field == 'location' else [])) for field in SEARCH_FIELDS}
