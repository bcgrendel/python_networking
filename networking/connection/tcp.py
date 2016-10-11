import socket
import sys
import traceback
import struct
import threading
from threading import Thread
import time
import datetime
import json
import buffered_message
from connection_state import ConnectionState

# *************
# EXAMPLE USAGE
# *************
"""
import socket
import tcp

import sys
import traceback

def handle_error(error_message=None, extra=None):
	err_msg = "[STUN_Server] Line #%s: %s\n\n%s" % (str(traceback.tb_lineno(sys.exc_traceback)), traceback.format_exc(), sys.exc_info())
	print err_msg

server_ip = socket.gethostbyname(socket.gethostname())
server_port = 29979
buffer_size = 128

server = tcp.TCP_Server(server_ip, server_port, buffer_size)
client = tcp.TCP_Client(server_ip, server_port, buffer_size)

server.exception_handler = handle_error
client.exception_handler = handle_error

for i in range(0,10):
	client.send_message("Message from client.")

server.pop_message()

for i in range(0,10):
	server.send_message("Response from server.")

client.pop_message()

server.disconnect()
client.disconnect()
"""

class TCP_Server:
	
	def __init__(self,
			local_ip=socket.gethostbyname(socket.gethostname()),
			local_port=29979,
			buffer_size=1024):
		
		self.connection_state = ConnectionState(False)
		self.buffer_size = buffer_size
		
		content_length_prefix_size = 1 + len(str(self.buffer_size))
		self.message_manager = buffered_message.Buffered_Message_Manager(self.buffer_size - content_length_prefix_size)
		self.conn_list = []
		self.send_queue = []
		self.timeout = 3.0
		self.thread_sleep_duration = 0.1
		
		self.exception_handler = None
		
		self.bind_socket(local_ip, local_port)
	
	def init_socket(self):
		try:
			# close open socket, if there are any.
			if(hasattr(self, "sock")):
				self.sock.shutdown(socket.SHUT_RDWR)
				self.sock.close()
		except:
			if self.exception_handler != None:
				self.exception_handler()
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

	# starts/restarts the server
	def bind_socket(self, local_ip=socket.gethostbyname(socket.gethostname()), local_port=29979):
		self.local_port = local_port
		self.local_ip = local_ip
		
		# Clear out the list of client connections.
		del self.conn_list[:]
		
		# (Re)initialize socket before binding.
		self.init_socket()
		self.sock.settimeout(self.timeout)
		
		self.sock.bind((local_ip, local_port))
		self.sock.listen(1)
		
		# Now we start listening for connections.
		self.connection_state.active = False
		self.start_listening()

	def send_message(self, message, target_clients=None, json_encode=False, prepare=True):
		"""
		Send a message to (optionally specified) client(s).
			'target' is either None or a tuple containing (ip, port, username).
			eg. target=[('127.0.0.1', 25500), ('127.0.0.1', 27987)]
			If no target is specified, message is broadcast to all clients.
		!!! WARNING !!!
		If you pass prepare as False, you MUST ensure message doesn't exceed buffer-size yourself.
		"""
		target_list = []
		if target_clients != None:
			for target in target_clients:
				target_list.append("%s_%s" % (target[0], target[1]))
		
		msg = message
		if(json_encode):
			msg = json.dumps(msg)
		
		prepared_message_packets = [msg,]
		if prepare:
			prepared_message_packets = self.message_manager.prepare_message(msg)

		prepared_message_packets = ["%s_%s" % (len(packet), packet) for packet in prepared_message_packets]
		self.send_queue.append((prepared_message_packets, target_list))
	
	def stop_listening(self):
		self.connection_state.active = False
		try:
			self.sock.shutdown(socket.SHUT_RDWR)
			self.sock.close()
		except:
			pass
	
	def start_listening(self):
		if(not self.connection_state.active):
			self.connection_state = ConnectionState(True)
			Thread(target=self.recv_connection_loop).start()
			Thread(target=self.send_message_loop).start()
			return True
		return False
	
	def disconnect(self):
		self.stop_listening()
	
	def reconnect(self):
		self.disconnect()
		self.bind_socket(self.target_ip, self.target_port)
	
	def new_connection(self, target_ip=socket.gethostbyname(socket.gethostname()), target_port=29979):
		self.disconnect()
		self.bind_socket(target_ip, target_port)
	
	def recv_connection_loop(self):
		connection_state = self.connection_state
		while connection_state.active:
			time.sleep(self.thread_sleep_duration)
			conn = None
			addr = None
			try:
				conn, addr = self.sock.accept()
			except:
				continue
			# Start a thread for communicating with this client.
			self.conn_list.append((conn, addr))
			Thread(target=self.recv_message_loop, args=(conn, addr)).start()

	# Run this as its own thread.
	def recv_message_loop(self, conn, addr):
		connection_state = self.connection_state
		data_is_ready = False
		content_length = None
		message_list = []
		message = None
		while connection_state.active:
			time.sleep(self.thread_sleep_duration)
			data = None
			try:
				data = conn.recv(self.buffer_size)
			except:
				pass
			try:
				if not data:
					continue
				
				while len(data) > 0:
					if content_length == None:
						content_length, data = data.split("_", 1)
						content_length = int(content_length)
						content = data[0:content_length]
						data = data[content_length:]
						if len(content) >= content_length:
							message_list.append(content)
							content_length = None
						else:
							message = content
					else:
						remainining_length = content_length - len(message)
						content = data[0:remainining_length]
						data = data[remainining_length:]
						message = "%s%s" % (message, content)
						if len(message) >= content_length:
							message_list.append(message)
							content_length = None
			except:
				if self.exception_handler != None:
					self.exception_handler()
			if len(message_list) > 0:
				for _message in message_list:
					timestamp = time.time()
					self.message_manager.handle_raw_message(_message, addr, timestamp)
				del message_list[:]
	
	def get_target_recipient_list(self, conn_list, target_clients):
		if len(target_clients) < 1:
			return conn_list
		result = []
		for conn_tuple in conn_list:
			conn_id = "%s_%s" % conn_tuple[1]
			if conn_id in target_clients:
				result.append(conn_tuple)
		return result

	def send_message_loop(self):
		connection_state = self.connection_state
		while connection_state.active:
			message_count = len(self.send_queue)
			for i in range(0, message_count):
				prepared_message_packets, target_clients = self.send_queue.pop(0)
				
				conn = None
				conn_list = self.get_target_recipient_list(self.conn_list, target_clients)
				for packet in prepared_message_packets:
					for conn_tuple in conn_list:
						conn = conn_tuple[0]
						try:
							conn.send(packet)
						except:
							# todo: handle packet send timeout
							if self.exception_handler != None:
								self.exception_handler()
			time.sleep(self.thread_sleep_duration)
	
	# Returns a list: [addr, timestamp, message]
	def pop_message(self, decode_json=False):
		return self.message_manager.pop_message(decode_json)
	
	# Returns a list of lists: [[addr, timestamp, message], ...]
	def pop_all_messages(self, decode_json=False):
		return self.message_manager.pop_all_messages(decode_json)









# ==========
# TCP CLIENT
# ==========

class TCP_Client:
	
	def __init__(
			self,
			target_ip=socket.gethostbyname(socket.gethostname()),
			target_port=29979,
			buffer_size=1024
		):
		
		self.connection_state = ConnectionState(False)
		self.buffer_size = buffer_size
		content_length_prefix_size = 1 + len(str(self.buffer_size))
		self.message_manager = buffered_message.Buffered_Message_Manager(self.buffer_size - content_length_prefix_size)
		self.timeout = 3.0
		self.send_queue = []
		self.thread_sleep_duration = 0.1
		
		self.exception_handler = None
		
		self.bind_socket(target_ip, target_port)
	
	def init_socket(self):
		try:
			# close open socket, if there are any.
			if(hasattr(self, "sock")):
				self.sock.shutdown(socket.SHUT_RDWR)
				self.sock.close()
		except:
			if self.exception_handler != None:
				self.exception_handler()
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

	def bind_socket(self, target_ip=socket.gethostbyname(socket.gethostname()), target_port=29979):
		self.target_ip = target_ip
		self.target_port = target_port
		
		# (Re)initialize socket before binding.
		self.init_socket()
		self.sock.settimeout(self.timeout)
		self.sock.connect((target_ip, target_port))
		
		self.start_listening()
	
	def send_message(self, message, json_encode=False, prepare=True):
		# !!! WARNING !!!
		# If you pass prepare as False, you MUST ensure message doesn't exceed buffer-size yourself.
		
		msg = message
		if(json_encode):
			msg = json.dumps(msg)
		
		prepared_message_packets = [msg,]
		if prepare:
			prepared_message_packets = self.message_manager.prepare_message(msg)
		
		prepared_message_packets = ["%s_%s" % (len(packet), packet) for packet in prepared_message_packets]
		self.send_queue.append(prepared_message_packets)
	
	def send_message_loop(self):
		connection_state = self.connection_state
		while connection_state.active:
			message_count = len(self.send_queue)
			for i in range(0, message_count):
				prepared_message_packets = self.send_queue.pop(0)
				
				for packet in prepared_message_packets:
					try:
						self.sock.send(packet)
					except:
						# todo: handle packet send timeout
						if self.exception_handler != None:
							self.exception_handler()
			time.sleep(self.thread_sleep_duration)
	
	def stop_listening(self):
		self.connection_state.active = False
		try:
			self.sock.shutdown(socket.SHUT_RDWR)
			self.sock.close()
		except:
			if self.exception_handler != None:
				self.exception_handler()
	
	def start_listening(self):
		if(not self.connection_state.active):
			self.connection_state = ConnectionState(True)
			Thread(target=self.recv_message_loop).start()
			Thread(target=self.send_message_loop).start()
			return True
		return False
	
	def disconnect(self):
		self.stop_listening()
	
	def reconnect(self):
		self.disconnect()
		self.bind_socket(self.target_ip, self.target_port)
	
	def new_connection(self, target_ip=socket.gethostbyname(socket.gethostname()), target_port=29979):
		self.disconnect()
		self.bind_socket(target_ip, target_port)
	
	# Run this as its own thread.
	def recv_message_loop(self):
		addr = (self.target_ip, self.target_port)
		connection_state = self.connection_state
		content_length = None
		message_list = []
		message = None
		while connection_state.active:
			time.sleep(self.thread_sleep_duration)
			data = None
			try:
				data = self.sock.recv(self.buffer_size)
			except:
				pass
			try:
				if not data:
					continue
				while len(data) > 0:
					if content_length == None:
						content_length, data = data.split("_", 1)
						content_length = int(content_length)
						content = data[0:content_length]
						data = data[content_length:]
						if len(content) >= content_length:
							message_list.append(content)
							content_length = None
						else:
							message = content
					else:
						remainining_length = content_length - len(message)
						content = data[0:remainining_length]
						data = data[remainining_length:]
						message = "%s%s" % (message, content)
						if len(message) >= content_length:
							message_list.append(message)
							content_length = None
			except:
				if self.exception_handler != None:
					self.exception_handler()
			if len(message_list) > 0:
				for _message in message_list:
					timestamp = time.time()
					self.message_manager.handle_raw_message(_message, addr, timestamp)
				del message_list[:]
	
	# Returns a list: [addr, timestamp, message]
	def pop_message(self, decode_json=False):
		return self.message_manager.pop_message(decode_json)
	
	# Returns a list of lists: [[addr, timestamp, message], ...]
	def pop_all_messages(self, decode_json=False):
		return self.message_manager.pop_all_messages(decode_json)
