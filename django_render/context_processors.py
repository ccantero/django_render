from django_render.version import current_release_info


def deploy_version(request):
    info = current_release_info()
    return {"deploy_version_display": info["display"]}
