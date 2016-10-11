import time
import threading
from threading import Thread
import datetime
import json
import traceback

import socket
#import networking
from ..connection import tcp
from ..connection import udp
import uuid

from ..connection.connection_state import ConnectionState

from peers import Service,\
			Peer_Service,\
			Local_Endpoint,\
			Peer_Endpoint,\
			Peer_Local_Endpoint


# Test if the provided remote function is actually published and runnable.
def peer_service_function_exists(interface, service_name, function_name):
	# does the function exist on this service?
	has_function = False
	for peer, service_map in interface.peer_map:
		if service_name in service_map.keys():
			if function_name in service_map["service_name"]:
				has_function = True
				break
	
	return has_function

def get_local_service_function(local_endpoint, service_name, function_name):
	function = None
	for service in local_endpoint.service_list:
		if service.name == service_name and function_name in service.function_map.keys():
			return service.function_map[function_name]
	
	return function

# api class
class Peer_Service_Interface(object):

	def __init__(self, **kwargs):
		keyword_arguments = {
			"local_endpoint": None,
			"peer_endpoint_list": [],
			"failed_to_connect_callback": None,
			"message_received_callback": None,
			"keep_alive_timeout_callback": None,
			"new_peer_connected_callback": None,
			"peer_interface_ready_callback": None, # fires when a peer is fully identified and ready to execute service functions.
			"peer_disconnected_callback": None,
		}
		self.apply_keyword_arguments(keyword_arguments, kwargs)
		
		if not isinstance(self.local_endpoint, Local_Endpoint):
			raise Exception("local_endpoint property of Peer_Service_Interface object must be a Local_Endpoint object.")
		
		for peer_endpoint in self.peer_endpoint_list:
			if not isinstance(peer_endpoint, Peer_Endpoint):
				raise Exception("peer_endpoint_list property of Peer_Service_Interface object must only contain Peer_Endpoint objects (or their derivatives, e.g. Peer_Local_Endpoint).")

		self.server_ip = self.local_endpoint.ip #socket.gethostbyname(socket.gethostname())
		self.server_port = self.local_endpoint.port
		
		self.buffer_size = 512
		self.server = None #udp.UDP_Client(True, server_ip, server_port, None, None, buffer_size, True, message_received_callback, keep_alive_timeout_callback, new_peer_connected_callback)
		self.server_type = "Client"
		self.communication_type = "udp"
		
		self.supported_communication_types = [
			"udp",
		]
		
		self.keep_alive = True

		self.peer_map = {
			# "<ip>_<port>": <service_map>
		}

		self.execution_callback_map = {
			# <message_id>: <callback_function>
		}
		self.execution_result_map = {
			# <message_id>: <results> # initially None
		}

		self.built_in_function_list = [
			"identify",
		]

		self.message_queue = []

		self.check_for_function_return_interval = 0.05
		self.remote_service_identification_interval = 0.3
		self.message_queue_processing_interval = 0.05

		self.connection_state = ConnectionState(False)
		self.internal_thread_init()
		self.init_server()
		
		# let's init connections to the provided peer endpoints.
		self.initiate_contact_with_peers()
	
	def apply_keyword_arguments(self, default_keyword_arguments, keyword_arguments):
		for argument, default_value in default_keyword_arguments.items():
			value = default_value
			if argument in keyword_arguments.keys():
				value = keyword_arguments[argument]
			setattr(self, argument, value)
	
	def initiate_contact_with_peers(self):
		# simply send the keep-alive message to each peer
		for peer_endpoint in self.peer_endpoint_list:
			peer_ip = peer_endpoint.ip
			peer_port = peer_endpoint.port
			self.server.connect_async(peer_ip, peer_port)
	
	def add_peer_endpoint(self, peer_endpoint):
		if not isinstance(peer_endpoint, Peer_Endpoint):
			raise Exception("peer_endpoint argument must be a Peer_Endpoint object.")
		
		if peer_endpoint in self.peer_endpoint_list:
			return False
		
		if self.get_peer_endpoint(peer_endpoint.ip, peer_endpoint.port) != None:
			return False
		
		# add the peer
		self.peer_endpoint_list.append(peer_endpoint)
		
		# connect to the peer
		self.server.connect_async(peer_endpoint.ip, peer_endpoint.port)
		
		
	def internal_thread_init(self):
		self.connection_state = ConnectionState(True)
		Thread(target=self.remote_service_identification).start()
		Thread(target=self.message_queue_processor).start()
	
	def identify(self):
		service_map = {}
		for service in self.local_endpoint.service_list:
			service_map[service.name] = service.function_map.keys()
		
		endpoint_name = "%s_%s" % (self.local_endpoint.ip, self.local_endpoint.port)
		return [endpoint_name, service_map]
	
	def handle_identified_peer_info(self, results):
		peer, service_map = results
		if type(peer) is not str and type(peer) is not unicode:
			ip, port = peer
			peer = "%s_%s" % (ip, port)
		
		ip, port = peer.split("_")
		port = int(port)
		self.peer_map[peer] = service_map
		# validate service_map
		# get the peer_endpoint that this peer maps to.
		identified_peer_endpoint = None
		for peer_endpoint in self.peer_endpoint_list:
			if peer_endpoint.ip == ip and peer_endpoint.port == port:
				identified_peer_endpoint = peer_endpoint
				break
		
		missing_services = []
		missing_functions = {}
		for service in identified_peer_endpoint.service_list:
			if service.name not in service_map.keys():
				missing_services.append(service.name)
				continue
			
			for function_name in service.expected_functions:
				if function_name not in service_map[service.name]:
					if service.name not in missing_functions.keys():
						missing_functions[service.name] = []
					missing_functions[service.name].append(function_name)
		
		if len(missing_services) > 0 or len(missing_functions) > 0:
			error_message = "ERROR: peer was missing required services/functions:"
			if len(missing_services) > 0:
				error_message += "\n\n\tMissing Services:\n\t\t%s" % str.join("\n\t\t", missing_services)
			if len(missing_functions) > 0:
				error_message += "\n\n\tMissing Functions:\n\t\t%s"
				for service_name, function_name in missing_functions.items():
					 error_message += "Service [%s]:\n\t\t\t%s" % (service_name, str.join("\n\t\t\t", missing_services))
			
			raise Exception(error_message)
		
		# fire callback to indicate peer interface is ready for use.
		if self.peer_interface_ready_callback != None:
			self.peer_interface_ready_callback(identified_peer_endpoint, service_map)
		
		# fire callback on the peer if it has been set to something other than None.
		if identified_peer_endpoint.peer_interface_ready_callback != None:
			identified_peer_endpoint._peer_interface_ready_callback()
	
	def remote_service_identification(self):
		current_connection_state = self.connection_state
		
		while self.connection_state.active:
			time.sleep(self.remote_service_identification_interval)
			# loop through the peer_map list
			for peer, service_list in self.peer_map.items():
				ip, port = peer.split("_")
				port = int(port)
				if service_list != None:
					continue
				
				# get that peer's list of services along with published functions on those services
				self.execute_peer_service_function([ip, port], None, "identify", [], self.handle_identified_peer_info, message_type="function_call")

	def message_queue_processor(self):
		current_connection_state = self.connection_state
		
		while self.connection_state.active:
			time.sleep(self.message_queue_processing_interval)
			while len(self.message_queue) > 0:
				message = self.message_queue.pop(0)

				peer = message[0]
				ip, port = peer
				timestamp = int(message[1])
				data = message[2]
				if len(data) < 2:
					continue
				
				message_type = data["message_type"]

				if message_type == "function_call":
					service_name = data["service_name"]
					if service_name != None:
						message_id = data["id"]
						function_name = data["function"]
						arguments = data["arguments"]

						# execute the function if it's published.
						self.execute_service_function(peer, message_id, service_name, function_name, arguments)
					else:
						message_id = data["id"]
						function_name = data["function"]
						arguments = data["arguments"]

						if function_name in self.built_in_function_list:
							#getattr(self, function_name)(peer, message_id, *arguments)
							self.execute_service_function(peer, message_id, None, function_name, arguments)
				elif message_type == "response":
					message_id = data["id"]
					results = data["results"]
					if message_id in self.execution_callback_map.keys():
						self.execution_callback_map[message_id](results)
						del self.execution_callback_map[message_id]
					else:
						self.execution_result_map[message_id] = results

	def execute_peer_service_function(self, peer_endpoint, service_name, function_name, arguments, callback_function=None, message_type="function_call"):
		# convert function name and args to a list object
		message_type = message_type.lower()
		if message_type not in ["function_call", "response"]:
			message_type = "function_call"
		
		ip, port = [None, None]
		if peer_endpoint != None:
			if type(peer_endpoint) is list:
				ip, port = peer_endpoint
			else:
				ip = peer_endpoint.ip
				port = peer_endpoint.port
		
		if ip == None or port == None:
			raise Exception("ERROR: A peer endpoint (in this format: [ip, port] ) or Peer_Service object must be provided in order to execute peer functions.")
		
		message_id = str(uuid.uuid4())
		message = {
			"message_type": message_type,
			"id": message_id,
			"service_name": service_name,
			"function": function_name,
			"arguments": arguments,
		}
		if callback_function != None:
			self.execution_callback_map[message_id] = callback_function
		
		self.server.send_message(message, True, True, ip, port)
		
		if callback_function == None:
			results = None
			# block until either the endpoint responds or disconnects
			while True:
				time.sleep(self.check_for_function_return_interval)
				if message_id in self.execution_result_map.keys():
					results = self.execution_result_map[message_id]
					del self.execution_result_map[message_id]
					break
			
			return results
		else:
			return message_id
	
	def _execute_service_function(self, peer_endpoint, message_id, service_name, function_name, arguments):
		target_ip, target_port = peer_endpoint
		function = None
		if service_name != None:
			function = get_local_service_function(self.local_endpoint, service_name, function_name)
		else:
			# internal function.
			is_valid_internal_function = hasattr(self, function_name) and function_name in self.built_in_function_list
			if is_valid_internal_function:
				function = getattr(self, function_name)
		
		if function != None:
			results = function(*arguments)
			response = {
				"message_type": "response",
				"id": message_id, 
				"results": results,
			}
			self.server.send_message(response, True, True, target_ip, target_port)
		else:
			# return a server response indicating the function either doesn't exist or isn't published.
			error_message = "The function [%s] is not a published function in the service '%s'" % (function_name, service_name)
			response = {
				"message_type": "error",
				"id": message_id,
				"service": service_name,
				"function": function_name,
				"error": error_message,
			}
			self.server.send_message(response, True, True, target_ip, target_port)

	def get_peer_endpoint(self, ip, port):
		for peer_endpoint in self.peer_endpoint_list:
			if peer_endpoint.ip == ip and peer_endpoint.port == port:
				return peer_endpoint
		return None
			
	def execute_service_function(self, peer_endpoint, message_id, service_name, function_name, arguments):
		Thread(target=self._execute_service_function, args=[peer_endpoint, message_id, service_name, function_name, arguments]).start();

	def _failed_to_connect_callback(self, ip, port):
		peer_endpoint = self.get_peer_endpoint(ip, port)
		if self.failed_to_connect_callback != None:
			self.failed_to_connect_callback(peer_endpoint)
		peer_endpoint._failed_to_connect_callback()
		
		
	def _handle_message_received(self, _ip, _port):
		messages = self.server.pop_all_messages(True) # True indicates that the data is to be json decoded.
		for message in messages:
			self.message_queue.append(message)

		if self.message_received_callback != None:
			self.message_received_callback(messages)
		
		for message in messages:
			peer = message[0]
			ip, port = peer
			peer_endpoint = self.get_peer_endpoint(ip, port)
			peer_endpoint._message_received_callback(message)
		

	def _keep_alive_timeout_callback(self, ip, port):
		if self.service == None:
			return
		function_to_call = "keep_alive_timeout"
		peer = "%s_%s" % (ip, port)
		#if service_function_exists(self, self.service, function_to_call):
		#	getattr(self.service, function_to_call)(peer) #(*arguments)

		# notify all pending remote function execution response listeners.
		handler_queue = self.execution_callback_map[peer]
		for handler_pair in handler_queue:
			response_handler, disconnect_handler = handler_pair
			disconnect_handler(peer)

		# remove this peer from the execution callback map
		del self.execution_callback_map[peer]
		
		if self.keep_alive_timeout_callback != None:
			self.keep_alive_timeout_callback(peer_endpoint)
		
		peer_endpoint = self.get_peer_endpoint(ip, port)
		if self.keep_alive_timeout_callback != None:
			self.keep_alive_timeout_callback(peer_endpoint)
		peer_endpoint._keep_alive_timeout_callback()
		
	def _peer_disconnected_callback(self, ip, port):
		peer_endpoint = self.get_peer_endpoint(ip, port)
		if self.peer_disconnected_callback != None:
			self.peer_disconnected_callback(peer_endpoint)
		peer_endpoint._peer_disconnected_callback()

	def _new_peer_connected_callback(self, ip, port):
		function_to_call = "handle_new_peer_connection"
		peer = "%s_%s" % (ip, port)
		#if service_function_exists(self, self.service, function_to_call):
		#	getattr(self.service, function_to_call)(peer) #(*arguments)

		# add this peer from the execution callback map
		self.execution_callback_map[peer] = []

		# add this peer to the peer_map.
		self.peer_map[peer] = None
		
		peer_endpoint = self.get_peer_endpoint(ip, port)
		if self.new_peer_connected_callback != None:
			self.new_peer_connected_callback(peer_endpoint)
		peer_endpoint._new_peer_connected_callback()

	def init_server(self):
		if self.communication_type in globals():
			communication_module = globals()[self.communication_type]
			communication_class_name = "%s_%s" % (self.communication_type.upper(), self.server_type)
			if hasattr(communication_module, communication_class_name):
				communication_class = getattr(communication_module, communication_class_name)
				self.server = communication_class(
					True, # start listening now
					self.server_ip, 
					self.server_port, 
					None, # initial target ip (initially None because we'll manage initializing connections ourselves)
					None, # initial target port
					self.buffer_size, 
					self.keep_alive, # send keep-alive packets
					self._failed_to_connect_callback,
					self._handle_message_received, 
					self._keep_alive_timeout_callback, 
					self._new_peer_connected_callback,
					self._peer_disconnected_callback,
					True, # require_ack (yeah, this is basically tcp on top of udp)
				)
				self.server.connection_attempt_timeout = 10.0 # seconds
	
	def shutdown(self):
		self.connection_state.active = False;
		self.server.disconnect()
	
	def restart(self):
		self.server.reconnect()
		self.internal_thread_init()
		self.initiate_contact_with_peers()
	
"""

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

"""