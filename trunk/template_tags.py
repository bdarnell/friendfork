import datetime

from google.appengine.ext.webapp import template

register = template.create_template_register()

@register.filter(name="isoparse")
def isoparse(s):
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')

@register.inclusion_tag('user.html')
def render_user(mapper, user):
    return {'user': user,
	    'group': mapper.get_group_for_user(user['nickname']),
	    'is_friend': mapper.is_friend(user['nickname']),
	    }
