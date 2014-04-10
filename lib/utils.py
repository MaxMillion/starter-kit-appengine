#!/usr/bin/env python

from json import dumps as to_json, loads as from_json
from os   import environ

from google.appengine.api.datastore_errors import BadValueError
from google.appengine.api.validation       import ValidationError
from google.appengine.ext                  import ndb
import webapp2



DEBUG   = ('Development' in environ.get('SERVER_SOFTWARE', 'Production'))
ORIGINS = '*'



class BaseModel(ndb.Model):
	_excludes   = []
	_fetch_keys = True

	def to_dict(self, excludes=None, fetch_keys=None):
		if excludes is None:
			excludes = []
		if fetch_keys is None:
			fetch_keys = self._fetch_keys
		excludes.extend(self._excludes)
		props = {}
		if 'id' not in excludes:
			props['id'] = self.key.id()
		for key, prop in self._properties.iteritems():
			if key not in excludes:
				value = getattr(self, key)
				if isinstance(value, ndb.Key):
					if fetch_keys:
						value = value.get().to_dict()
					else:
						value = value.id()
				elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], ndb.Key):
					if fetch_keys:
						value = [e.to_dict() for e in ndb.get_multi(value)]
					else:
						value = [k.id() for k in value]
				props[key] = value
		return props



class BaseHandler(webapp2.RequestHandler):
	def initialize(self, *args, **kwargs):
		value = super(BaseHandler, self).initialize(*args, **kwargs)
		try:
			body_params = from_json(self.request.body)
		except:
			body_params = {}
		self.params = {}
		self.params.update(self.request.params)
		self.params.update(body_params)
		return value

	def handle_exception(self, exception, debug):
		logging.exception(exception)
		if isinstance(exception, BadValueError) or isinstance(exception, ValidationError):
			self.response.set_status(400)
		else:
			self.response.set_status(500)
		self.response.write('An error occurred.')

	def options(self, *args, **kwargs):
		self.response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
		self.response.headers['Access-Control-Allow-Origin' ] = ORIGINS
		self.response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
		self.response.headers['Cache-Control'               ] = 'no-cache'

	def respond(self, data, content_type='application/json', cache_life=0):
		self.response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
		self.response.headers['Access-Control-Allow-Origin' ] = ORIGINS

		if cache_life:
			self.response.headers['Cache-Control'] = 'max-age=%s' % cache_life
		else:
			self.response.headers['Cache-Control'] = 'no-cache'

		if content_type == 'application/json':
			self.response.headers['Content-Type'] = 'application/json'
			self.response.out.write( to_json(data, separators=(',',':')) )
		else:
			self.response.headers['Content-Type'] = content_type
			self.response.out.write(data)
