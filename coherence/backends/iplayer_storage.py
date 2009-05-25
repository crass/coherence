# -*- coding: utf-8 -*-

# Licensed under the MIT license
# http://opensource.org/licenses/mit-license.php

# Copyright 2008, Benjamin Kampmann <ben.kampmann@googlemail.com>


########## The imports
# The entry point for each kind of Backend is a 'BackendStore'. The BackendStore
# is the instance that does everything Usually. In this Example it can be
# understood as the 'Server', the object retrieving and serving the data.
from coherence.backend import BackendStore

# The data itself is stored in BackendItems. They are also the first things we
# are going to create.
from coherence.backend import BackendItem

# To make the data 'renderable' we need to define the DIDLite-Class of the Media
# we are providing. For that we have a bunch of helpers that we also want to
# import
from coherence.upnp.core import DIDLLite

# And we also import the reactor, that allows us to specify an action to happen
# later
from twisted.internet import reactor

from twisted.internet.threads import deferToThread

from coherence.upnp.core import utils
from twisted.web import server
from twisted.web.resource import Resource

from urllib import urlretrieve
from os.path import dirname,expanduser, exists
from os import makedirs, chmod, system, popen
from popen2 import Popen3

class ProxyStream(Resource):

	def __init__(self, uri, video):
		self.video = video
		self.uri = uri
		Resource.__init__(self)

	def requestFinished(self, result):
		""" self.connection is set in utils.ReverseProxyResource.render """
		print "ProxyStream requestFinished"

	def get_pid(self, request):
		pid = request.uri.split("/")[-1]
		cmd = "%s --force --stdout -n --pid %s"%(self.video.store.script_path,pid)
		print "render",pid, cmd
		run = Popen3(cmd, True)
		f = open(pid,"w+b")
		while run.poll()==-1:
			data = run.fromchild.read(8192)
			request.write(data)
			f.write(data)
		f.close()
		print run.childerr.read()
		print "render return",run.wait()

	def render(self, request):
		dfr = deferToThread(self.get_pid, request)
		return server.NOT_DONE_YET

	########## The models
# After the download and parsing of the data is done, we want to save it. In
# this case, we want to fetch the videos and store their URL and the title of
# the image. That is the IplayerVideo class:

class IplayerVideo(BackendItem):
	# We inherit from BackendItem as it already contains a lot of helper methods
	# and implementations. For this simple example, we only have to fill the
	# item with data.

	def __init__(self, parent, id, title, pid):
		self.parentid = parent.id	   # used to be able to 'go back'
		self.parent = parent

		top_parent = parent
		while not isinstance(top_parent, BackendStore):
			top_parent = top_parent.parent
		
		self.store = top_parent
		self.update_id = 0

		self.id = id					# each item has its own and unique id

		self.url = self.store.urlbase + pid
		self.location = ProxyStream(self.url, self) # the url of the picture

		self.name = unicode(title,"utf8","ignore")   # the title of the picture. Inside
										# coherence this is called 'name'


		# Item.item is a special thing. This is used to explain the client what
		# kind of data this is. For e.g. A VideoItem or a MusicTrack.
		self.item = DIDLLite.VideoItem(id, parent.id, self.name)

		# each Item.item has to have one or more Resource objects
		# these hold detailed information about the media data
		# and can represent variants of it (different sizes, transcoded formats)
		res = DIDLLite.Resource(self.url, 'http-get:*:video/quicktime:*')
		res.size = None #FIXME: we should have a size here
						#	   and a resolution entry would be nice too
		self.item.res.append(res)

	def get_path(self):
		return self.url

class IplayerContainer(BackendItem):
	# The IplayerContainer will hold the reference to all our IplayerImages. This
	# kind of BackenedItem is a bit different from the normal BackendItem,
	# because it has 'children' (the Iplayerimages). Because of that we have
	# some more stuff to do in here.

	def __init__(self, parent, id, name):
		# the ids as above
		self.parent = parent
		if self.parent != None:
			self.parent_id = parent.id
		else:
			self.parent_id = None
		self.id = id
		self.name = unicode(name,"utf8","ignore")   # the title of the picture. Inside

		# but we need to set it to a certain mimetype to explain it, that we
		# contain 'children'.
		self.mimetype = 'directory'

		# As we are updating our data periodically, we increase this value so
		# that our clients can check easier if something has changed since their
		# last request.
		self.update_id = 0

		# that is where we hold the children
		self.children = []

		# and we need to give a DIDLLite again. This time we want to be
		# understood as 'Container'.
		self.item = DIDLLite.Container(id, self.parent_id, self.name)

		self.item.childCount = None # will be set as soon as we have images

	def get_children(self, start=0, end=0):
		# This is the only important implementation thing: we have to return our
		# list of children
		if end != 0:
			return self.children[start:end]
		return self.children[start:]

	# there is nothing special in here
	# FIXME: move it to a base BackendContainer class
	def get_child_count(self):
		return len(self.children)

	def get_item(self):
		return self.item

	def get_name(self):
		return self.name

	def get_id(self):
		return self.id

########## The server
# As already said before the implementation of the server is done in an
# inheritance of a BackendStore. This is where the real code happens (usually).
# In our case this would be: downloading the page, parsing the content, saving
# it in the models and returning them on request.

class IplayerStore(BackendStore):

	# this *must* be set. Because the (most used) MediaServer Coherence also
	# allows other kind of Backends (like remote lights).
	implements = ['MediaServer']

	script_url = "http://linuxcentre.net/get_iplayer/get_iplayer"
	script_path = expanduser("~/.local/share/coherence/get_iplayer")

	# as we are going to build a (very small) tree with the items, we need to
	# define the first (the root) item:
	ROOT_ID = 0
	id = ROOT_ID

	def __init__(self, server, *args, **kwargs):
		# first we inizialize our heritage
		BackendStore.__init__(self,server,**kwargs)

		# When a Backend is initialized, the configuration is given as keyword
		# arguments to the initialization. We receive it here as a dicitonary
		# and allow some values to be set:

		# the name of the MediaServer as it appears in the network
		self.name = kwargs.get('name', 'iPlayer')

		# timeout between updates in hours:
		self.refresh = int(kwargs.get('refresh', 1)) * (60 *60)

		# internally used to have a new id for each item
		self.next_id = 1000

		# the UPnP device that's hosting that backend, that's already done
		# in the BackendStore.__init__, just left here the sake of completeness
		self.server = server

		# initialize our Iplayer container (no parent, this is the root)
		self.container = IplayerContainer(None, self.ROOT_ID, "iPlayer")

		# but as we also have to return them on 'get_by_id', we have our local
		# store of videos per id:
		self.everything = {}

		# we tell that if an XBox sends a request for videos we'll
		# map the WMC id of that request to our local one
		self.wmc_mapping = {'15': 0}

		# and trigger an update of the data
		dfr = self.update_data()

		# So, even though the initialize is kind of done, Coherence does not yet
		# announce our Media Server.
		# Coherence does wait for signal send by us that we are ready now.
		# And we don't want that to happen as long as we don't have succeeded
		# in fetching some first data, so we delay this signaling after the update is done:
		dfr.addCallback(self.init_completed)
		dfr.addCallback(self.queue_update)

	def get_by_id(self, id):
		print "asked for", id, type(id)
		# what ever we are asked for, we want to return the container only
		if isinstance(id, basestring):
			id = id.split('@',1)[0]
		try:
			id = int(id)
		except ValueError:
			pass
		if id == self.ROOT_ID:
			return self.container
		val = self.everything.get(id,None)
		print id,val,val.name
		return val

	def upnp_init(self):
		# after the signal was triggered, this method is called by coherence and

		# from now on self.server is existing and we can do
		# the necessary setup here

		# that allows us to specify our server options in more detail.

		# here we define what kind of media content we do provide
		# mostly needed to make some naughty DLNA devices behave
		# will probably move into Coherence internals one day
		self.server.connection_manager_server.set_variable( \
			0, 'SourceProtocolInfo', ['internal:*:video/quicktime:*',
				'http-get:*:video/quicktime:*'], default=True)

		# and as it was done after we fetched the data the first time
		# we want to take care about the server wide updates as well
		self._update_container()

	def _update_container(self, result=None):
		# we need to inform Coherence about these changes
		# again this is something that will probably move
		# into Coherence internals one day
		if self.server:
			self.server.content_directory_server.set_variable(0,
					'SystemUpdateID', self.update_id)
			value = (self.ROOT_ID,self.container.update_id)
			self.server.content_directory_server.set_variable(0,
					'ContainerUpdateIDs', value)
		return result

	def update_loop(self):
		# in the loop we want to call update_data
		dfr = self.update_data()
		# aftert it was done we want to take care about updating
		# the container
		dfr.addCallback(self._update_container)
		# in ANY case queue an update of the data
		dfr.addBoth(self.queue_update)

	def get_schedule(self):
		if not exists(dirname(self.script_path)):
			makedirs(dirname(self.script_path))
		if not exists(self.script_path):
			urlretrieve(self.script_url, self.script_path)
			chmod(self.script_path, 0755)
			ret = system("%s --plugins-update"%self.script_path)
			assert ret == 0
		data = popen("%s --listformat '<name>;<pid>;<episode>;<channel>'"%self.script_path).readlines()
		return data

	def update_data(self):
		# trigger an update of the data

		# fetch the rss
		dfr = deferToThread(self.get_schedule)

		# then parse the data into our models
		dfr.addCallback(self.parse_data)

		return dfr

	def parse_data(self, data):
		# reset the childrens list of the container and the local storage
		self.container.children = []
		self.videos = {}
		self.channels = {}
		self.series = {}
		open("dump","w").write(" ".join(data))

		post_match = False
		for line in data:
			if not post_match:
				if line == "Matches:\n":
					post_match = True
				continue
			if len(line.strip()) == 0: # blank after list
				break
			(series,pid,episode,channel) = line.strip().split(";")

			if channel not in self.channels:
				self.channels[channel] = IplayerContainer(self, self.next_id, channel)
				self.everything[self.next_id] = self.channels[channel]
				self.container.children.append(self.channels[channel])
				self.next_id += 1

			if series not in self.series:
				self.series[series] = IplayerContainer(self.channels[channel], self.next_id, series)
				self.everything[self.next_id] = self.series[series]
				self.channels[channel].children.append(self.series[series])
				self.channels[channel].update_id +=1
				self.next_id +=1

			video = IplayerVideo(self.series[series], self.next_id, "%s - %s"%(series,episode), pid)
			self.series[series].children.append(video)
			self.series[series].update_id +=1
			self.everything[self.next_id] = video
			self.everything[pid] = video

			self.next_id += 1

		# and increase the container update id and the system update id
		# so that the clients can refresh with the new data
		self.container.update_id += 1
		self.update_id += 1

	def queue_update(self, error_or_failure):
		# We use the reactor to queue another updating of our data
		print "error or failure",error_or_failure
		reactor.callLater(self.refresh, self.update_loop)

if __name__ == '__main__':

	from twisted.internet import reactor

	f = IplayerStore(None)
	
	reactor.run()
