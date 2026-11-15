from django import template

from .. import seo as seo_helpers

register = template.Library()


@register.simple_tag(takes_context=True)
def canonical(context):
    request = context["request"]
    return request.build_absolute_uri(request.path)


@register.simple_tag(takes_context=True)
def absolute(context, path):
    return context["request"].build_absolute_uri(path)


@register.simple_tag
def jsonld(*objs):
    return seo_helpers.dumps([o for o in objs if o])
