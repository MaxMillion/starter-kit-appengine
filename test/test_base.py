#!/usr/bin/env python

import logging
from datetime import datetime
from json     import dumps as json_stringify
from os.path  import dirname
from time     import mktime
from unittest import TestCase

from google.appengine.api           import apiproxy_stub, apiproxy_stub_map
from google.appengine.api.blobstore import blobstore_stub, file_blob_storage
from google.appengine.api.files     import file_service_stub
from google.appengine.api.images    import images_stub
from google.appengine.datastore     import datastore_stub_util
from google.appengine.ext           import ndb, testbed
from webtest                        import TestApp

from app import app



class URLFetchServiceMock(apiproxy_stub.APIProxyStub):
	def __init__(self, service_name='urlfetch'):
		super(URLFetchServiceMock, self).__init__(service_name)
		self._status  = None
		self._headers = None
		self._content = None

	def set_response(self, status, headers, content):
		self._status  = status
		self._headers = headers
		self._content = content

	def _Dynamic_Fetch(self, request, response):
		if self._status is None:
			raise Exception('urlfetch response not setup, call set_urlfetch_response')
		response.set_finalurl(request.url)
		response.set_contentwastruncated(False)
		response.set_statuscode(self._status)
		response.set_content(self._content)
		for header, value in self._headers.items():
			new_header = response.add_header()
			new_header.set_key(header)
			new_header.set_value(value)
		self.request  = request
		self.response = response

class TestBase(TestCase):
	CUSTOM_URLFETCH = True
	USERNAME        = 'kikteam'
	HOSTNAME        = 'myservice.appspot.com'

	def setUp(self):
		root         = dirname('..')
		self.policy  = datastore_stub_util.PseudoRandomHRConsistencyPolicy(probability=1.0)
		self.app     = app
		self.testapp = TestApp(self.app)
		self.testbed = testbed.Testbed()
		self.testbed.activate()
		self.testbed.init_taskqueue_stub(root_path=root)
		self.testbed.init_memcache_stub()
		self.testbed.init_datastore_v3_stub(root_path=root, consistency_policy=self.policy)
		self.testbed.init_user_stub()
		self.blob_storage = file_blob_storage.FileBlobStorage('/tmp/testbed.blobstore', testbed.DEFAULT_APP_ID)
		self.testbed._register_stub('blobstore', blobstore_stub.BlobstoreServiceStub(self.blob_storage))
		self.testbed._register_stub('file', file_service_stub.FileServiceStub(self.blob_storage))
		self.testbed._register_stub('images', images_stub.ImagesServiceStub())
		if self.CUSTOM_URLFETCH:
			self._url_fetch_mock = URLFetchServiceMock()
			apiproxy_stub_map.apiproxy.RegisterStub('urlfetch', self._url_fetch_mock)
		else:
			self._url_fetch_mock = None
			self.testbed.init_urlfetch_stub()
		self.taskqueue_stub = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)
		ndb.get_context().set_cache_policy(lambda key: False)

	def set_urlfetch_response(self, status=200, headers={}, content=''):
		if not self.CUSTOM_URLFETCH:
			raise Exception('url fetch not setup, set CUSTOM_URLFETCH=True')
		self._url_fetch_mock.set_response(status, headers, content)

	def tearDown(self):
		self.testbed.deactivate()

	def get_tasks(self, queue='default'):
		return self.taskqueue_stub.GetTasks(queue)

	def execute_tasks(self, queue='default'):
		tasks   = self.get_tasks(queue)
		retries = []
		self.taskqueue_stub.FlushQueue(queue)
		for task in tasks:
			params = task['body'].decode('base64')
			try:
				self.testapp.post(task['url'], params)
			except:
				retries.append(task)
		for task in retries:
			params = task['body'].decode('base64')
			self.testapp.post(task['url'], params)

	def api_call(self, method, resource, data=None, status=200, headers={}):
		method  = method.lower()
		is_json = False

		if data and (type(data) is dict) and (method in ['post', 'put', 'patch']):
			is_json = True

		#TODO: data as query param for other requests

		if is_json:
			func = getattr(self.testapp, method.lower()+'_json')
		else:
			func = getattr(self.testapp, method.lower())

		if data:
			return func(resource, params=data, status=status, headers=headers)
		else:
			return func(resource, status=status, headers=headers)

	def auth_api_call(self, method, resource, data=None, status=200, headers={}):
		method = method.lower()
		if method.lower() in ('put', 'post', 'patch'):
			if data and isinstance(data, dict):
				payload = json_stringify(data)
			else:
				payload = data
			data = None
			as_query = False
		else:
			payload = resource.split('?')[0]
			as_query = True
		now = int( mktime(datetime.utcnow().utctimetuple()) ) * 1000
		jws_headers = json_stringify({
			'alg'      : 'RS256'           ,
			'kikUsr'   : self.USERNAME     ,
			'exp'      : now + 1000*60*60*2,
			'x5u'      : self.HOSTNAME     ,
			'nbf'      : now - 1000*60*60  ,
			'kikCrdDm' : self.HOSTNAME     ,
			'kikDbg'   : True
		})
		jws = '.'.join(p.encode('base64').strip().replace('=','') for p in [
			jws_headers, payload, 'signature'
		])
		if as_query:
			data = data or {}
			data['jws'] = jws
		else:
			headers['Content-Type'] = 'text/plain'
			data = jws
		return self.api_call(method, resource, data=data, status=status, headers=headers);
