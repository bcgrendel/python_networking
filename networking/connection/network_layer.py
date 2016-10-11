import time
import threading
from threading import Thread
import datetime
import json
import traceback

import socket
#import networking
import tcp
import udp
import uuid

from connection_state import ConnectionState

def is_published_function(application, function_name):
	# does the function exist on this application?
	has_function = hasattr(application, function_name)

	# is the function published on this application
	function_is_published = True
	has_published_function_list = hasattr(application, "published_functions")
	if has_published_function_list:
		function_is_published = function_name in application.published_functions
	
	return has_function and function_is_published


"""
remote_application_manager
--------------------------
	used to define what remote interfaces are expected and how they are connected to
		expected incoming connections
		expected outgoing connections
		initializer function for starting up the peer application's process (if not already running)
		is_running function for checking if the peer application is running

"""

class peer_application(object):

	def __init__(
		self,
		failed_to_connect_callback=None,
		message_received_callback=None,
		keep_alive_timeout_callback=None,
		new_peer_connected_callback=None,
		peer_disconnected_callback=None
		):
		pass

	def start_application(self):
		pass

	def stop_application(self):
		pass

	def is_running(self):
		pass

# api endpoints provided by a process running on this machine which we (might) have permissions to start/stop.
class peer_local_application(peer_application):

	def __init__(
		self,
		failed_to_connect_callback=None,
		message_received_callback=None,
		keep_alive_timeout_callback=None,
		new_peer_connected_callback=None,
		peer_disconnected_callback=None
		):
		pass

	def start_application(self):
		pass

	def stop_application(self):
		pass

	def is_running(self):
		pass

class peer_remote_application(peer_application):

	def __init__(self, **kwargs):
		"""
			The accepted keyword arguments and their default values are:
				"local_application": <object>,   The local_application object that will provide functions to the peer application(s).
				"application_name": "app1",      The expected peer application's name. Must match the name reported by the peer.
				"connected_application_min": 1,  Minimum number of connected instances of the application before application is considered to be running.
				"connected_application_max": 1,  Maximum number of instances of the application allowed to connect to us.
				"is_host": True,                 if True, we init connection to the peer. If False, the peer inits connection to us.
				"peer_endpoints": [],            Expects either None, an empty list, or a list of endpoints from which connections may be made.
				                                 'peer_endpoints' is required if is_host=True. If list is empty or None, any peer endpoints may connect.
				                                 If is_host, connections will be attempted until 'connected_application_min' is reached.
				                                 To specify that any port from a given IP may be used, set the port number to "*" instead of an integer.
				                                       [[<ip>, <port>], ...]
		"""
		keyword_arguments = {
			"local_application": None, # Will need a better default than null. An actual local_application object with no public functions.
			"application_name": "app1"
			"is_host": True, # Is the application we're connecting to the host? If True, we initiate connection to the peer. If False, the peer initiates connection to us.
		}

		# assign properties from the keyword arguments.
		self.apply_keyword_arguments(keyword_arguments, kwargs)

		"""
		any_peers_allowed = self.peer_endpoints != None and len(self.peer_endpoints) < 1
		if any_peers_allowed:
			self.peer_endpoints = None
		"""
	
	def apply_keyword_arguments(self, default_keyword_arguments, keyword_arguments):
		for argument, default_value in default_keyword_arguments.items():
			value = default_value
			if argument in keyword_arguments.keys():
				value = keyword_arguments[argument]
			setattr(self, argument, value)

	def start_application(self, application_interface = None):
		pass

	def stop_application(self):
		pass

	def is_running(self):
		return True

class peer_application_manager:

	def __init__(self, peer_application_list):
		self.peer_application_list = peer_application_list
		self.start_managing_applications()
	
	def start_managing_applications(self):
		pass

class tcp_client_group:

	def __init__(self):
		self.client_map = {
			# "<ip>_<port>": <TCP_Client object>
		}
	
	def send_message(self, message, json_encode=False, prepare=True):
		for peer, tcp_client in self.client_map.items():
			tcp_client.send_message(message, json_encode, prepare)
	
	# Returns a list of lists: [[addr, timestamp, message], ...]
	def pop_all_messages(self, decode_json=False):
		messages = []
		for peer, tcp_client in self.client_map.items():
			messages.extend(tcp_client.pop_all_messages(decode_json))
		return messages

class peer_application_interface:

	def __init__(self, local_port=59779, peer_endpoints=[]):
		self.application_map = {
			# <application_name>: application_object
		}

		self.server_ip = socket.gethostbyname(socket.gethostname())
		self.server_port = local_port
		
		self.target_ip = None
		self.target_port = None
		
		self.buffer_size = 512
		self.server = None #udp.UDP_Client(True, server_ip, server_port, None, None, buffer_size, True, message_received_callback, keep_alive_timeout_callback, new_peer_connected_callback)
		self.server_type = "Client"
		self.communication_type = "udp"
		self.keep_alive = True

		self.remote_application_map = {
			# "application_name": [[ip, port], [published function list]],
		}

		self.peer_map = {
			# "<ip>_<port>": "application_name"
		}

		self.unidentified_remote_applications = [
			# [<ip>, <port>],
		]

		self.execution_callback_map = {
			# 
		}

		self.built_in_function_list = [
			"get_function_list",
			"identify",
		]

		self.message_queue = []

		self.check_for_function_return_interval = 0.05
		self.remote_application_identification_interval = 0.3
		self.message_queue_processing_interval = 0.05

		self.connection_state = ConnectionState(False)
		self.internal_thread_init()
		self.init_server()
		
		# let's init connections to the provided peer endpoints.
		self.target_peer_endpoints = []
		for peer_endpoint in peer_endpoints:
			self.target_peer_endpoints.append(peer_endpoint)
		
		self.initiate_contact_with_peers()
		
	def initiate_contact_with_peers(self):
		# simply send the keep-alive message to each peer
		for peer_endpoint in self.target_peer_endpoints:
			peer_ip, peer_port = peer_endpoint
			self.server.send_message("1", False, False, peer_ip, peer_port)

	def internal_thread_init(self):
		self.connection_state = ConnectionState(True)
		Thread(target=self.remote_application_identification).start()
		Thread(target=self.message_queue_processor).start()
	
	def identify(self, message_id):
		pass
	
	def remote_application_identification(self):
		current_connection_state = self.connection_state
		
		while self.connection_state.active:
			time.sleep(self.remote_application_identification_interval)
			# loop through the peer_map list
			for peer, application_name in self.peer_map.items():
				target_ip, port = peer.split("_")
				port = int(port)
				if application_name != None:
					continue
				
				# get that peer's list of applications along with published functions on those applications
				results = self.execute_remote_function("identify", [], target_ip, target_port, None, message_type="internal_function_call")

	def message_queue_processor(self):
		current_connection_state = self.connection_state
		
		while self.connection_state.active:
			time.sleep(self.message_queue_processing_interval)
			while len(message_queue) > 0:
				message = message_queue.pop(0)

				peer = message[0]
				ip, port = peer
				timestamp = int(message[1])
				data = message[2]
				if len(data) < 2:
					continue
				
				message_type = data["type"]

				if message_type == "function_call":
					message_id = data["id"]
					function_name = data["function"]
					arguments = data["arguments"]

					# execute the function if it's published.
					self.execute_application_function(peer, message_id, function_name, arguments)
				elif message_type == "internal_function_call":
					message_id = data["id"]
					function_name = data["function"]
					arguments = data["arguments"]

					if function_name in self.built_in_function_list:
						getattr(self, function_name)(peer, message_id, *arguments)
				elif message_type == "response":
					message_id = data["id"]
					results = data["results"]

	def shutdown(self):
		self.connection_state.active = False;
		self.server.disconnect()

	def restart(self):
		self.server.reconnect()
		self.internal_thread_init()
	
	def get_function_list(self, message_id):
		response = ""

	def receive_function_list(self, message):
		pass

	def _handle_remote_function_return(self, message_id, message):
		pass

	def execute_remote_function(self, function_name, *arguments, target_ip, target_port, callback_function=None, message_type="function_call"):
		# convert function name and args to a list object
		_callback_function = callback_function
		if _callback_function == None:
			pass

		message_id = str(uuid.uuid4())
		message = {
			"message_type": message_type,
			"id": message_id,
			"function": function_name,
			"arguments": arguments,
		}
		self.server.send_message(message, True, True, target_ip, target_port)
		if callback_function == None:
			results = None
			# block until either the endpoint responds or disconnects
			while True:
				time.sleep(self.check_for_function_return_interval)
			
			return results
	
	def _execute_application_function(self, peer, message_id, function_name, application_name, arguments):
		target_ip, target_port = peer
		if is_published_function(self.application, function_name):
			results = getattr(self.application, function_name)(*arguments)
			response = {
				"message_type": "response",
				"id": message_id, 
				"results": results,
			}
			self.server.send_message(response, True, True, target_ip, target_port)
		else:
			# return a server response indicating the function either doesn't exist or isn't published.
			error_message = "The function [%s] is not a published function in the application '%s'" % (function_name, application_name)
			response = {
				"message_type": "error",
				"id": message_id,
				"function": function_name,
				"error": error_message,
			}
			self.server.send_message(response, True, True, target_ip, target_port)
			pass

	def execute_application_function(self, peer, message_id, function_name, application_name, arguments):
		Thread(target=self._execute_application_function, args=[peer, message_id, function_name, arguments]).start();

	def failed_to_connect_callback(self, target_ip, target_port):
		pass
		
	def handle_message_received(self):
		messages = self.server.pop_all_messages()
		for message in messages:
			if self.application == None:
				continue

			self.message_queue.append(message)

		

	def keep_alive_timeout_callback(self, ip, port):
		if self.application == None:
			return
		function_to_call = "keep_alive_timeout"
		peer = "%s_%s" % (ip, port)
		if is_published_function(self.application, function_to_call):
			getattr(self.application, function_to_call)(peer) #(*arguments)

		# notify all pending remote function execution response listeners.
		handler_queue = self.execution_callback_map[peer]
		for handler_pair in handler_queue:
			response_handler, disconnect_handler = handler_pair
			disconnect_handler(peer)

		# remove this peer from the execution callback map
		del self.execution_callback_map[peer]
		
	def peer_disconnected_callback(self, ip, port):
		pass

	def new_peer_connected_callback(self, ip, port):
		if self.application == None:
			return
		function_to_call = "handle_new_peer_connection"
		peer = "%s_%s" % (ip, port)
		if is_published_function(self.application, function_to_call):
			getattr(self.application, function_to_call)(peer) #(*arguments)

		# add this peer from the execution callback map
		self.execution_callback_map[peer] = []

		# add this peer to the peer_map.
		self.peer_map[peer] = None

	# this function expects an object (module or class instance)
	def set_application_object(_application):
		"""
		Note: You can pass the current module as an object to this function.
			
			import sys
			current_module = sys.modules[__name__]
		"""
		self.application = _application

	def set_network_configuration(self, config):
		"""
			Config must be a dictionary that looks like this:
			{
				 server_ip: <ip>, 
				 server_port: <port>, 
				 target_ip=None,
				 target_port=None, 
				 buffer_size=512,
				 communication_type="udp",
				 server_type="Client"
			}
			
		"""
		self.server_ip = _server_ip
		self.server_port = _server_port
		self.target_ip = _target_ip
		self.target_port = _target_port
		self.buffer_size = _buffer_size
		self.communication_type = _communication_type
		self.server_type = _server_type.lower().capitalize()

		# Keep alive shall be kept required for this remote application interface.
		self.keep_alive = True

	def set_callbacks(self, _message_received_callback, _keep_alive_timeout_callback, _new_peer_connected_callback):
		self.message_received_callback = _message_received_callback
		self.keep_alive_timeout_callback = _keep_alive_timeout_callback
		self.new_peer_connected_callback = _new_peer_connected_callback

	def init_server(self):
		if self.communication_type in globals():
			communication_module = globals()[self.communication_type]
			communication_class_name = "%s_%s" % (self.communication_type.upper(), server_type)
			if hasattr(communication_module, communication_class_name):
				communication_class = getattr(communication_module, communication_class_name)
				self.server = communication_class(
					True, # start listening now
					self.server_ip, 
					self.server_port, 
					self.target_ip, 
					self.target_port, 
					self.buffer_size, 
					self.keep_alive, # send keep-alive packets
					self.failed_to_connect_callback,
					self.message_received_callback, 
					self.keep_alive_timeout_callback, 
					self.new_peer_connected_callback,
					self.peer_disconnected_callback
				)
			
