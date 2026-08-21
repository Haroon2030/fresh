"""قالب الموقع — قيم مشتركة من التهيئة."""


def branch_defaults(request):
    from .models import Branch

    return {
        'default_branch': Branch.default_name(),
    }
