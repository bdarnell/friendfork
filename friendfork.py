import datetime 
import os
import random
import wsgiref.handlers

from django.utils.simplejson import decoder

from google.appengine.api import urlfetch
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

DEFAULT_GROUP_NAME = "Other"
UNKNOWN_GROUP_NAME = "Strangers"

class GroupMapper:
    def __init__(self, desc, profile_json):
	# self.__map = {groupname: [username, username...]}
	self.__map = {}
	# self.__index = {username: groupname}
	self.__index = {}
	# self.__group_index = {int index: groupname}
	self.__group_index = {}
	# self.__friends = {username: None}
	self.__friends = {}

	if profile_json:
	    for friend in profile_json['subscriptions']:
		self.__friends[friend['nickname']] = None

	if desc is None:
	    return
	group_index = 0
	current_group = None
	for line in desc.split('\n'):
	    if ':' in line:
		current_group, names = line.split(':', 1)
		current_group = current_group.strip()
		self.__group_index[current_group] = group_index
		group_index = group_index + 1
	    else:
		names = line
	    for name in (s.strip() for s in names.split(',')):
		if name:
		    self.__map.setdefault(current_group, []).append(name)
		    self.__index[name] = current_group
	self.__group_index[DEFAULT_GROUP_NAME] = group_index
	group_index = group_index + 1
	self.__group_index[UNKNOWN_GROUP_NAME] = group_index
	group_index = group_index + 1

    def get_group_for_user(self, user):
	if not user in self.__friends:
	    return UNKNOWN_GROUP_NAME
	if user in self.__index:
	    return self.__index[user]
	else:
	    return DEFAULT_GROUP_NAME

    def min_group(self, g1, g2):
	if self.__group_index[g1] <= self.__group_index[g2]:
	    return g1
	else:
	    return g2

    def is_friend(self, user):
	return user in self.__friends

class BaseHandler(webapp.RequestHandler):
    def base_template_vars(self):
	template_vars = {
	    'user': users.get_current_user(),
	    'login_url': users.create_login_url(self.request.uri),
	    'logout_url': users.create_logout_url(self.request.uri),
	    }
	return template_vars

    def require_login(self):
	"""Checks that the user is logged in.

	If no user is logged in, redirects to the login page and returns
	False.  Otherwise returns True.
	"""
	if users.get_current_user():
	    return True
	else:
	    self.redirect(users.create_login_url(self.request.uri))
	    return False

    def get_current_user_config(self):
	return UserConfig.gql('where user = :1', users.get_current_user()).get()

    def fetch_json_with_auth(self, config, url):
	"""Fetches url using friendfeed auth from config and parses as json.

	Returns None if auth is not configured.  Throws an exception if
	auth is configured but there is an error fetching or parsing."""
	if config.friendfeed_nickname and config.friendfeed_remote_key:
	    encoded_auth = ('%s:%s' % (config.friendfeed_nickname,
				       config.friendfeed_remote_key)).encode('base64')
	    # python's str.encode('base64') "helpfully" adds a newline
	    encoded_auth = encoded_auth.strip()
	    result = urlfetch.fetch(
		url,
		headers={'Authorization': 'Basic ' + encoded_auth})
	    if result.status_code == 200:
		return decoder.JSONDecoder().decode(result.content)
	    else:
		print result
		raise RuntimeError("http error: %d" % result.status_code)
	else:
	    return None


class MainPage(BaseHandler):
    def get(self):
	self.response.out.write(template.render('root.html', 
						self.base_template_vars()))

class UserConfig(db.Model):
    user = db.UserProperty()
    friendfeed_nickname = db.StringProperty()
    friendfeed_remote_key = db.StringProperty()
    friend_group_spec = db.TextProperty()
    url_token = db.StringProperty()

class ManagePage(BaseHandler):
    def get(self):
	if not self.require_login():
	    return
	template_vars = self.base_template_vars()

	config = self.get_current_user_config()
	template_vars['config'] = config
	if config and config.friendfeed_nickname:
	    profile_json = self.fetch_json_with_auth(
		config, ('http://friendfeed.com/api/user/%s/profile'
			 % config.friendfeed_nickname))
	    if profile_json:
		mapper = GroupMapper(config.friend_group_spec, profile_json)
		friend_groups = {}
		for friend in profile_json['subscriptions']:
		    group = mapper.get_group_for_user(friend['nickname'])
		    friend_groups.setdefault(group, []).append(friend)
		template_vars['friend_groups'] = friend_groups
	self.response.out.write(template.render('manage.html', template_vars))

class SavePage(BaseHandler):
    def post(self):
	if not self.require_login():
	    return
	config = self.get_current_user_config()
	if not config:
	    config = UserConfig()
	    config.user = users.get_current_user()
	if not config.url_token:
	    config.url_token = '%016x' % random.randint(0, 2**62)
	config.friendfeed_nickname = self.request.get('friendfeed_nickname')
	config.friendfeed_remote_key = self.request.get('friendfeed_remote_key')
	config.friend_group_spec = db.Text(self.request.get('friend_group_spec'))
	config.put()
	self.redirect('/manage')
	

class FeedPage(BaseHandler):
    def get(self):
	config = UserConfig.gql('where url_token = :1', 
				self.request.get('id')).get()
	if not config:
	    raise RuntimeError("no token or invalid token")
	feed_json = self.fetch_json_with_auth(
	    config, 'http://friendfeed.com/api/feed/home')
	profile_json = self.fetch_json_with_auth(
	    config, ('http://friendfeed.com/api/user/%s/profile'
		     % config.friendfeed_nickname))
	mapper = GroupMapper(config.friend_group_spec, profile_json)
	entries = []
	reader_users = {}
	for entry in feed_json['entries']:
	    user_group = mapper.get_group_for_user(entry['user']['nickname'])
	    group = user_group
	    for action in (entry['likes'] + entry['comments']):
		group = mapper.min_group(
		    group, mapper.get_group_for_user(action['user']['nickname']))
	    if group == self.request.get('group'):
		if (entry['service']['id'] == 'googlereader' and
		    not entry['likes'] and
		    not entry['comments'] and
		    user_group == group):
		    reader_users[entry['service']['profileUrl'].rsplit(
			    '/', 1)[1]] = entry['user']
		else:
		    entries.append(entry)
	    
	self.response.headers['Content-Type'] = 'application/atom+xml'
	self.response.out.write(template.render(
		'feed.atom',
		{ 'group_name': self.request.get('group'),
		  'entries': entries,
		  'reader_users': reader_users,
		  'mapper': mapper,
		  }))

def main():
    template.register_template_library('template_tags')
    application = webapp.WSGIApplication(
	[('/', MainPage),
	 ('/feed', FeedPage),
	 ('/manage', ManagePage),
	 ('/save', SavePage),
	],
	debug = True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
