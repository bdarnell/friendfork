import datetime

from django.template import defaultfilters

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
            # shorthand since django templates can't do 'if not', 
            # only 'if {} else'
	    'not_friend': not mapper.is_friend(user['nickname']),
	    }

@register.inclusion_tag('comment.html')
def render_comment(mapper, comment):
    user = comment['user']
    return {'mapper': mapper,
            'comment': comment,
            # TODO(bdarnell): how to factor these out?
            'is_friend': mapper.is_friend(user['nickname']),
            'not_friend': not mapper.is_friend(user['nickname']),
            }

@register.filter(name="comment_link_filter")
def comment_link_filter(body_string, is_friend):
    if is_friend:
        return body_string
    else:
        return body_string.replace('<a href=', '<a style="color:#77f" href=')

@register.simple_tag
def render_id(mapper, entry):
    """Returns an id for an entry, based on either the FF id and the latest
    interesting event (if any).

    Interesting events are:
    * Likes or comments on an entry posted by the current user.
    * Comments by a friend of the current user
    * Comments on an item that has been liked or commented by the current
      user.
    """
    posted_by_me = entry['user']['nickname'] == mapper.get_my_name()
    for i in entry['likes'] + entry['comments']:
        if i['user']['nickname'] == mapper.get_my_name():
            liked_or_commented_by_me = True
            break
    else:
        liked_or_commented_by_me = False
    
    want_likes = posted_by_me
    want_all_comments = posted_by_me or liked_or_commented_by_me

    def latest_timestamp(seq, init):
        """Given a sequence of json objects with a date field and an initial
        value, return the greatest date as a datetime object.
        """
        if not seq:
            return init
        ts = max((isoparse(o['date']) for o in seq))
        if init is None or ts > init:
            return ts
        else:
            return init

    timestamp = None
    if want_likes:
        timestamp = latest_timestamp(entry['likes'], timestamp)
    if want_all_comments:
        interesting_comments = entry['comments']
    else:
        interesting_comments = [c for c in entry['comments'] 
                                if mapper.is_friend(c['user']['nickname'])]
    timestamp = latest_timestamp(interesting_comments, timestamp)

    if timestamp is None:
        result = 'tag:friendfeed.com,2007:%s' % entry['id'] 
    else:
        result = 'tag:friendfork.appspot.com,2008:%s/%s' % (
            entry['id'], timestamp.isoformat())

    # Django templates must apparently return str objects (encoded in 
    # django.conf.settings.DEFAULT_CHARSET), not unicode objects (ugh).
    # See the implementation of django.template.VariableNode.
    # Our ids are just ascii, so use that instead of looking up the default
    # (which appears to be utf8)
    result = result.encode('ascii')
    
    # There shouldn't be any special characters in these ids, but run them
    # through escape() just to be safe.
    return defaultfilters.escape(result)
