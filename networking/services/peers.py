import time
import socket
import psutil
import os
import sys
import json
import threading
from threading import Thread
import subprocess

from ..connection.connection_state import ConnectionState

from endpoint_lock import attempt_endpoint_registration,\
				  unlock_endpoint

import argument_parser

DETACHED_PROCESS = 0x00000008

"""
remote_service_manager
--------------------------
	used to define what remote interfaces are expected and how they are connected to
		expected incoming connections
		expected outgoing connections
		initializer function for starting up the peer service's process (if not already running)
		is_running function for checking if the peer service is running

"""

class Service(object):

	def __init__(self, **kwargs):
		
		keyword_arguments = {
			"name": "app1",
			"id": "1",
			"function_map": {},
		}
		self.apply_keyword_arguments(keyword_arguments, kwargs)
		if not isinstance(self.function_map, dict):
			raise Exception("ERROR: (Service instantiation) function_map must be a dict.")
		
	def apply_keyword_arguments(self, default_keyword_arguments, keyword_arguments):
		for argument, default_value in default_keyword_arguments.items():
			value = default_value
			if argument in keyword_arguments.keys():
				value = keyword_arguments[argument]
			setattr(self, argument, value)

class Peer_Service(Service):

	def __init__(self, **kwargs):
		
		keyword_arguments = {
			"name": "app1",
			"id": "1",
			"expected_functions": None,
		}
		self.apply_keyword_arguments(keyword_arguments, kwargs)
	
	def validate_functions(self, function_list):
		has_expectations = self.expected_functions != None and len(self.expected_functions) > 0
		if has_expectations:
			missing_functions = []
			for expected_function in self.expected_functions:
				if expected_function not in function_list:
					missing_functions.append(expected_function)
			
			if len(missing_functions) > 0:
				raise Exception(
					"ERROR: [SERVICE name: %s, id: %s] is missing the following required function(s):\n\t%s" % (
						self.name,
						self.id,
						str.join("\n\t", missing_functions),
					)
				)
				return False
		return True

class Local_Endpoint(object):
	
	def __init__(self, **kwargs):
		keyword_arguments = {
			"ip": socket.gethostbyname(socket.gethostname()),
			"port": 59243,
			"master_process_id": None,
			"service_list": None,
			"local_cleanup_callback": None,
		}
		self.apply_keyword_arguments(keyword_arguments, kwargs)
		
		master_process_id = None
		if self.port == None:
			temp_ip, port, master_pid = argument_parser.get_endpoint()
			if temp_ip != None and ip == None:
				self.ip = temp_ip
			if master_pid != None and master_process_id == None:
				master_process_id = master_pid
			
		if self.ip == None:
			self.ip = socket.gethostbyname(socket.gethostname())
		
		if self.master_process_id == None:
			self.master_process_id = master_process_id
		
		if self.service_list == None:
			self.service_list = []
		for service in self.service_list:
			if type(service) is not Service:
				raise Exception("ERROR: (Local_Endpoint instantiation) service_list must only contain Service objects.")
		self.is_open = False
		
		self.establish_endpoint_lock()
	
	def apply_keyword_arguments(self, default_keyword_arguments, keyword_arguments):
		for argument, default_value in default_keyword_arguments.items():
			value = default_value
			if argument in keyword_arguments.keys():
				value = keyword_arguments[argument]
			setattr(self, argument, value)
	
	def establish_endpoint_lock(self):
		service_list = []
		for service in self.service_list:
			service_list.append([service.name, service.id])
		if not attempt_endpoint_registration(self.ip, self.port, service_list):
			print "Failed to acquire lock! An active lock already exists on this endpoint."
			os._exit(0)
		else:
			self.is_open = True
	
	def open(self):
		if not self.is_open:
			self.establish_endpoint_lock()
	
	def close(self):
		unlock_endpoint(self.ip, self.port)
		self.is_open = False
	
	def self_terminate(self):
		self.close()
		if self.local_cleanup_callback != None:
			self.local_cleanup_callback()
		os._exit(0)


class Peer_Endpoint(object):
	def __init__(self, **kwargs):
		pass
	
	def apply_keyword_arguments(self, default_keyword_arguments, keyword_arguments):
		for argument, default_value in default_keyword_arguments.items():
			value = default_value
			if argument in keyword_arguments.keys():
				value = keyword_arguments[argument]
			setattr(self, argument, value)
	
	def start_service(self):
		pass

	def stop_service(self):
		pass

	def is_running(self):
		return True

# api endpoints provided by a process running on this machine which we (might) have permissions to start/stop.
class Peer_Local_Endpoint(Peer_Endpoint):

	def __init__(self, **kwargs):
		keyword_arguments = {
			"local_endpoint": None, # local_endpoint object
			"ip": socket.gethostbyname(socket.gethostname()),
			"port": 59243,
			"service_list": [],
			"relationship": "peer", # If this service is a slave to this process, then we manage whether it starts or stops. Possible values are "peer", "slave", and "master". Any other value just translates to "peer".
			"process_run_command": "",
			"process_stop_command": None, # if None, normal task kill, otherwise, the command in the string will be run.
								# If '<pid>' is in the string, it will be replaced with the actual process id.
			"failed_to_connect_callback": None,
			"message_received_callback": None,
			"keep_alive_timeout_callback": None,
			"new_peer_connected_callback": None,
			"peer_disconnected_callback": None,
			"local_cleanup_callback": None, # If this service is a slave, it will run this if the master DCs/terminates.
			"peer_interface_ready_callback": None,
		}
		self.apply_keyword_arguments(keyword_arguments, kwargs)
		if self.ip == None:
			self.ip = socket.gethostbyname(socket.gethostname())
		if not isinstance(self.local_endpoint, Local_Endpoint):
			raise Exception("local_endpoint property of Peer_Local_Service object must be a Local_Endpoint object.")
		
		self.process_id = None
		if self.local_endpoint.master_process_id != None:
			if self.relationship.lower() == "master":
				self.process_id = self.local_endpoint.master_process_id
		
		self.state = ConnectionState(False)
		self.master_health_check_interval = 4.0
		self.slave_health_check_interval = 4.0
		self.peer_interface = None # to be set by the interface object itself.
		
		# initialize
		self.check_stop_command()
		self.initialize()
	
	def _failed_to_connect_callback(self):
		if self.failed_to_connect_callback != None:
			self.failed_to_connect_callback(self)
	
	def _message_received_callback(self, message):
		if self.message_received_callback != None:
			self.message_received_callback(self, message)
	
	def _keep_alive_timeout_callback(self):
		if self.keep_alive_timeout_callback != None:
			self.keep_alive_timeout_callback(self)
	
	def _new_peer_connected_callback(self):
		if self.new_peer_connected_callback != None:
			self.new_peer_connected_callback(self)
	
	def _peer_disconnected_callback(self):
		if self.peer_disconnected_callback != None:
			self.peer_disconnected_callback(self)
	
	def _peer_interface_ready_callback(self):
		if self.peer_interface_ready_callback != None:
			self.peer_interface_ready_callback(self)
	
	def simple_process_kill(self):
		if self.process_id != None:
			for process in psutil.process_iter():
				if process.pid == self.process_id:
					process.kill()
					return True
		return False
		
	def check_stop_command(self):
		if self.process_stop_command == None:
			pass
		
	def initialize(self):
		relationship = self.relationship.lower()
		if relationship == "slave":
			# start the service and get the process_id.
			self.start_service()
			
			# monitor the slave process and restart it if it unexpectedly dies.
			Thread(target=self.slave_monitor).start()
			
		elif relationship == "master":
			# monitor the master process and self-terminate if it unexpectedly dies.
			Thread(target=self.master_monitor).start()
		else:
			# We don't really need to manage independent peer processes. So no starting and monitoring.
			pass
	
	def peer_process_is_running(self, process_id = None):
		if process_id == None:
			process_id = self.process_id
		
		if process_id != None:
			for process in psutil.process_iter():
				if process.pid == process_id:
					return True
		return False
	
	def slave_health_check(self):
		return self.peer_process_is_running()
					
	
	def slave_monitor(self):
		state = self.state
		while state.active:
			time.sleep(self.slave_health_check_interval)
			if not self.slave_health_check():
				# we need to restart the peer process and reconnect.
				self.start_service()
				break
		
		
	def terminate_self(self):
		# If this is a slave service, use this method to end the entire service.
		if self.local_cleanup_callback != None:
			self.local_cleanup_callback() # this better not have any async. os._exit is an immediate termination.
		self.local_endpoint.terminate_self()
	
	def master_health_check(self):
		return self.peer_process_is_running()
	
	def master_monitor(self):
		state = self.state
		while state.active:
			time.sleep(self.master_health_check_interval)
			if not self.master_health_check():
				self.terminate_self()
		
		
	def execute_stop_command(self, pid):
		if self.process_stop_command == None:
			for process in psutil.process_iter():
				if process.pid == pid:
					process.kill()
					return True
		else:
			command_string = self.process_stop_command.replace("<pid>", str(pid))
			os.system(command_string)
			return True
		return False
		

	def start_service(self):
		self.state.active = False
		self.state = ConnectionState(True)
		
		# launch service as completely independent process.
		self.process_id = subprocess.Popen(self.process_run_command, creationflags=DETACHED_PROCESS, close_fds=True).pid
		

	def stop_service(self):
		self.state.active = False
		if self.process_id == None:
			return None
		self.execute_stop_command(self.process_id)

	def is_running(self):
		if self.state.active:
			return self.peer_process_is_running()
		return False

class Peer_Remote_Endpoint(Peer_Endpoint):

	def __init__(self, **kwargs):
		"""
			The accepted keyword arguments and their default values are:
				"local_endpoint": None, # local_endpoint object
				"peer_ip": socket.gethostbyname(socket.gethostname()),
				"peer_port": 59243,
				"service_list": [],
				"is_host": True, # Is the service we're connecting to the host? If True, we initiate connection to the peer. If False, the peer initiates connection to us.
				"failed_to_connect_callback": None,
				"message_received_callback": None,
				"keep_alive_timeout_callback": None,
				"new_peer_connected_callback": None,
				"peer_disconnected_callback": None,
		"""
		keyword_arguments = {
			"local_endpoint": None, # local_endpoint object
			"ip": socket.gethostbyname(socket.gethostname()),
			"port": 59243,
			"service_list": [],
			"is_host": True, # Is the service we're connecting to the host? If True, we initiate connection to the peer. If False, the peer initiates connection to us.
			"failed_to_connect_callback": None,
			"message_received_callback": None,
			"keep_alive_timeout_callback": None,
			"new_peer_connected_callback": None,
			"peer_disconnected_callback": None,
		}
		self.apply_keyword_arguments(keyword_arguments, kwargs)
		if not isinstance(self.local_endpoint, Local_Endpoint):
			raise Exception("local_endpoint property of Peer_Local_Service object must be a Local_Endpoint object.")


	def start_service(self, service_interface = None):
		pass

	def stop_service(self):
		pass

	def is_running(self):
		return True