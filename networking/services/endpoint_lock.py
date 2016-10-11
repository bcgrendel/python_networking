
import socket
import os
import psutil
import socket
import json

import sqlalchemy
import time;
from datetime import date, timedelta
import datetime

from sqlalchemy import func

import services_alchemy
from services_alchemy import Endpoint,\
				     session_scope

import threading
from threading import Thread

from sqlalchemy.dialects import sqlite

endpoint_lock_map = {
	# <endpoint id>: <boolean> # the value indicates whether that endpoint is currently locked.
}
activity_update_interval = 1.0
activity_expiration = 4.0
active_session = None

def process_is_running(process_id):
		for process in psutil.process_iter():
			if process.pid == process_id:
				return True
		return False

def compile_endpoint_dict(ip, port, service_list, process_id=None):
	if process_id == None:
		process_id = os.getpid()
	
	return {
		"ip": ip,
		"port": port,
		"service_list": service_list,
		"process_id": process_id,
	}

def _lock_endpoint(endpoint, endpoint_id):
	global endpoint_lock_map
	global activity_update_interval
	global active_session
	session = services_alchemy.Session()
	
	while endpoint_lock_map[endpoint_id]:
		time.sleep(activity_update_interval)
		try:
			session.query(Endpoint).\
				filter(Endpoint.id == endpoint_id).\
				update({"last_active": datetime.datetime.utcnow()})
			session.commit()
		except:
			pass
	session.query(Endpoint).\
		filter(Endpoint.id == endpoint_id).\
		update({"last_active": None})
	session.commit()
	session.close()
	
def lock_endpoint(endpoint, endpoint_id):
	global endpoint_lock_map
	
	endpoint_lock_map[endpoint_id] = True
	Thread(target=_lock_endpoint, args=(endpoint, endpoint_id,)).start()

def unlock_endpoint(ip, port):
	global endpoint_lock_map
	
	session = services_alchemy.Session()
	if ip == None:
		ip = socket.gethostbyname(socket.gethostname())
	
	process_id = os.getpid()
	
	query = session.query(Endpoint).\
		filter(Endpoint.process_id == process_id).\
		filter(Endpoint.ip == ip).\
		filter(Endpoint.port == port).\
		filter(Endpoint.last_active != None)
	#print str(query.statement.compile(dialect=sqlite.dialect()))
	endpoint = query.first()
	
	# not in the db?
	if not endpoint:
		print "endpoint not found!"
		return False
	
	endpoint_id = endpoint.id
	# not on the current list of locks?
	if endpoint_id not in endpoint_lock_map.keys():
		return False
	
	# already unlocked?
	if not endpoint_lock_map[endpoint_id]:
		return False
	
	endpoint_lock_map[endpoint_id] = False
	endpoint.last_active = None
	session.commit()
	session.close()

def attempt_endpoint_registration(ip, port, service_list):
	global activity_expiration
	global endpoint_lock_map
	global activity_expiration
	
	service_string = json.dumps(service_list)
	endpoint_registered = False
	endpoint_dict = None
	endpoint_id = None
	endpoint = None
	with session_scope() as session:
		process_id = os.getpid()
		if ip == None:
			ip = socket.gethostbyname(socket.gethostname())
		
		endpoint_dict = compile_endpoint_dict(ip, port, service_string, process_id)
		
		start_time = None
		# try to query for the composite key [ip and port] and see if it exists. If not, create it.
		session = services_alchemy.Session()
		endpoint = session.query(Endpoint).\
			filter(Endpoint.ip == ip).\
			filter(Endpoint.port == port).\
			first()
		if not endpoint:
			endpoint = Endpoint(
				ip = ip,
				port = port,
				process_id = process_id,
				service_list = service_string,
				last_active = None
			)
			session.add(endpoint)
			session.commit()
			endpoint = session.query(Endpoint).\
				filter(Endpoint.ip == ip).\
				filter(Endpoint.port == port).\
				first()
		
		# make sure the ip and port aren't already in use.
		expiration_time = datetime.datetime.utcnow() - timedelta(seconds=activity_expiration)
		currently_active_endpoint = session.query(Endpoint).\
			filter(Endpoint.ip == ip).\
			filter(Endpoint.port == port).\
			filter(Endpoint.last_active >= expiration_time).\
			first()
		if currently_active_endpoint and currently_active_endpoint.process_id != process_id:
			# confirm that the process id of this endpoint is still active.
			if process_is_running(currently_active_endpoint.process_id):
				return False
			else:
				currently_active_endpoint.last_active = None
				session.commit()
		
		endpoint_id = endpoint.id
		# Give this endpoint a new start time.
		endpoint.start_time = datetime.datetime.utcnow()
		endpoint.process_id = process_id
		endpoint.ip = ip
		endpoint.port = port
		session.commit()
		endpoint_registered = True
	
	# ip and port are available, lock it and keep it updated. The entire service may be closed with 
	if endpoint_registered:
		lock_endpoint(endpoint_dict, endpoint_id)
		return True
	return False