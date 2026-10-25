from django import template

from django_render.version import BUENOS_AIRES

register = template.Library()


@register.filter
def art_timestamp(value):
    """Format an aware timestamp in America/Buenos_Aires, labeled ART.

    The zone data uses a fixed UTC-3 fallback when the legacy zone name is
    absent. The label is the time the control row was written, not a bot ack.
    """
    if not value:
        return ""
    return value.astimezone(BUENOS_AIRES).strftime("%d/%m/%Y %H:%M ART")
