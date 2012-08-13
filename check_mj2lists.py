#!/usr/bin/env python
#
# Nagios plugin to monitor the membership on majordomo2 lists.
#
# The idea is to make sure that lists that are supposed to have
# only a fixed set of members remain as such - even if they by
# operator error or software bug end up being public.
#
# The plugin will take the name of a settings file on the
# commandline, and this file should have the following
# format:
#
# [DEFAULT]
# host=lists.domain.org
# password=supersecret
#
# [list1]
# members=a@foo.com,b@bar.com,c@baz.com
#
# [list2]
# members=a@foo.com,c@baz.com
# host=lists.otherdomain.org
# password=evenmoresecret
#
#
# If there are any members on the list that are not in the file,
# CRITICAL will be returned and they will be listed.
# iF there are any members in the file that are not on the list,
# WARNING will be returned and they will be listed.
#
#
# Copyright (C) 2010, Magnus Hagander
# Copyright (C) 2010, PostgreSQL Global Development Group
# Released under The PostgreSQL Licence


from optparse import OptionParser
from ConfigParser import ConfigParser
from urllib import urlopen, urlencode, unquote
from email.Utils import parseaddr
import sys
import os.path
import re

class MajordomoInterface:
	"""
	Simple interface wrapping some majordomo commands through scraping
	the mj_wwwadm interface.
	"""

	def __init__(self, mjhost, listname, listpwd):
		self.mjhost = mjhost
		self.listname = listname
		self.listpwd = listpwd

	def fetch_current_subscribers(self):
		"""
		Fetch the current list of subscribers by calling out to the majordomo
		server and scrape the result of the 'who-short' command.
		"""

		f = urlopen("https://%s/mj/mj_wwwadm?passw=%s&list=%s&func=who-short" %
			(self.mjhost, self.listpwd, self.listname))
		s = f.read()
		f.close()

		# Ugly screen-scraping regexp hack
		resub = re.compile('list administration<br>\s+</p>\s+<pre>([^<]+)</pre>')
		m = resub.findall(s)
		if len(m) != 1:
			if s.find("<!-- Majordomo who_none format file -->") > 0:
				# Nobody on the list yet
				return set()
			raise Exception("Could not find list of subscribers")

		# Deal with those HTML entities that are set by the majordomo server.
		s = m[0].replace('&lt;','<').replace('&gt;','>').replace('&quot;','"')

		# Parse all email addresses to make sure we can deal with both the
		# "user@domain.com" and "Joe User <user@domain.com>" formats. Return
		# the address part only, as a unique set.
		return set([parseaddr(a)[1] for a in re.split('[\r\n]+',s) if a])

	def RemoveSubscribers(self, remove_subscribers):
		"""
		Remove the specified subscribers from the list.
		"""

		victims = "\r\n".join(remove_subscribers)
		self.__PostMajordomoForm({
			'func': 'unsubscribe-farewell',
			'victims': victims
		})

	def AddSubscribers(self, add_subscribers):
		"""
		Add the specified subscribers to the list.
		"""

		victims = "\r\n".join(add_subscribers)
		self.__PostMajordomoForm({
			'func': 'subscribe-set-welcome',
			'victims': victims
		})
	
	def __PostMajordomoForm(self, varset):
		"""
		Post a fake form to the majordomo mj_wwwadm interface with whatever
		variables are specified. Add the listname and password on top of what's
		already in the set of variables.
		"""

		var = varset
		var.update({
			'list': self.listname,
			'passw': self.listpwd
		})
		body = urlencode(var)
		
		h = httplib.HTTPS(self.mjhost)
		h.putrequest('POST', '/mj/mj_wwwadm')
		h.putheader('host', self.mjhost)
		h.putheader('content-type','application/x-www-form-urlencoded')
		h.putheader('content-length', str(len(body)))
		h.endheaders()
		h.send(body)
		errcode, errmsg, headers = h.getreply()
		if errcode != 200:
			print "ERROR: Form returned code %i, message %s" % (errcode, errmsg)
			print h.file.read()
			raise Exception("Aborting")


class MajordomoList(object):
	"""
	This class represents a single majordomo list.
	"""
	def __init__(self, cfg, listname):
		self.name = listname
		self.members = set([r.strip() for r in
							cfg.get(self.name, 'members').split(',')])
		self.majordomo = MajordomoInterface(cfg.get(self.name, 'host'),
											self.name,
											cfg.get(self.name, 'password'))

	def check(self):
		"""
		Connect to majordomo and get a list of subscribers, then compare this
		list with the subscribers we should have. If there are differences,
		return the appropriate alert (depending on if there are too many or too
		few members	on the list) along with a descriptive message. Otherwise,
		return an OK status with simple statistics aobut the list.
		"""
		try:
			current = self.majordomo.fetch_current_subscribers()
			if current.difference(self.members):
				return NagiosResult(NagiosResult.CRITICAL,
									"List %s should not have member(s) %s." % (
						self.name,
						", ".join(current.difference(self.members)),
						))
			if self.members.difference(current):
				return NagiosResult(NagiosResult.WARNING,
									"List %s is missing member(s) %s." % (
						self.name,
						", ".join(self.members.difference(current)),
						))
			return NagiosResult(NagiosResult.OK, "List %s, %s members" % (
					self.name, len(self.members),
					))
		except Exception, e:
			return NagiosResult(NagiosResult.CRITICAL,
								"Exception trying to check list %s: %s" % (
					self.name, e,
					))


class NagiosResult(object):
	"""
	Represents a single nagios status (OK, WARNING, CRITICAL), along with
	an (optional) associated message.
	"""
	OK=0
	WARNING=1
	CRITICAL=2

	def __init__(self, status, message=''):
		if status<0 or status>2:
			raise ValueError('Invalid status')
		self.status = status
		self.message = message

	def status_string(self):
		if self.status == NagiosResult.OK: return "OK"
		if self.status == NagiosResult.WARNING: return "WARNING"
		if self.status == NagiosResult.CRITICAL: return "CRITICAL"
		raise NotImplementedError


class NagiosResultCollector(object):
	"""
	Class that collects a set of NagiosResult:s. Keeps track of which is
	the most severe, and adjust the return code based on that. Keeps track
	of *all* messages generated.
	"""
	def __init__(self):
		self.worst_status = NagiosResult.OK
		self.messages = []

	def append(self, results):
		"""
		Append results to the accumulated list, and set the maximum status level.
		"""
		for r in results:
			if r.status > self.worst_status:
				self.worst_status = r.status
			if r.message:
				self.messages.append(r.message)

	def exit(self):
		"""
		Print the status, and exit with whatever messages we have collected.
		"""
		print "%s: %s" % (
			NagiosResult(self.worst_status).status_string(),
			' :: '.join(self.messages),
			)
		sys.exit(self.worst_status)

		
if __name__=="__main__":
	opt = OptionParser()
	opt.add_option('-f', '--file', dest='filename',
				   help='Read configuration from FILE', metavar='file')
	(options, args) = opt.parse_args()

	if not options.filename:
		opt.print_help()
		sys.exit(3)

	if not os.path.isfile(options.filename):
		print "File %s not found" % options.filename
		sys.exit(3)

	c = ConfigParser()
	c.read(options.filename)

	lists = [MajordomoList(c, listname) for listname in c.sections()]

	result = NagiosResultCollector()
	result.append([l.check() for l in lists])

	result.exit()
