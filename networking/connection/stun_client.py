import socket
import sys
import traceback
import struct
import threading;
from threading import Thread;
import time;
import datetime;
import json
#import buffered_message;
import hashlib
from Crypto.PublicKey import RSA
from connection_state import ConnectionState
# publickey = RSA.importKey(key_string)

import tcp;
import udp;

# *************
# EXAMPLE USAGE
# *************
'''
import socket
import tcp
import udp
import stun_client
import time

start_listening = True
local_ip = socket.gethostbyname(socket.gethostname())
local_port = 30779
server_ip = socket.gethostbyname(socket.gethostname())
server_port = 30788
socket_timeout = 3.0
peer_block_manager = None

client = stun_client.STUN_Client(start_listening, local_ip, local_port, server_ip, server_port, socket_timeout, peer_block_manager)

# Set your available listening port ranges
client.available_ports = [[35000, 35100], [36500, 36700],]

# Register a user acccount with the stun server.

class RegisterCallback:
	
	def __init__(self):
		self.error_message = ""
		self.success = None
	
	def handle_timeout(self, params=None):
		self.success = False
		self.error_message = "Registration request to server has timed-out."
	
	def complete_registration(self, success, error_message=""):
		self.success = success
		self.error_message = error_message


username = "test_user"
password = "test_pass123"
profile_map = {}
callback_object = RegisterCallback()
registration_type = "permanent"

client.register(username, password, profile_map, callback_object, registration_type)

response_check_interval = 0.5;
while callback_object.success == None:
	time.sleep(response_check_interval)

if not callback_object.success:
	print "Error: %s" % callback_object.error_message
	exit()

# Login with username and password.

class AuthCallback:
	
	def __init__(self):
		self.error_message = ""
		self.success = None
	
	def handle_timeout(self, params=None):
		self.success = False
		self.error_message = "Authentication request to server has timed-out."
	
	def complete_authentication(self, success, error_message=""):
		self.success = success
		self.error_message = error_message

callback_object = AuthCallback()

login = True # this authentication is to login. It'd be False if we wanted to log out.
client.authenticate(username, password, callback_object, login)

while callback_object.success == None:
	time.sleep(response_check_interval)

if not callback_object.success:
	print "Error: %s" % callback_object.error_message
	exit()

# Now we can access the list of peers connected to the server. 
# Alternatively, assign a function reference to client.peer_map_callback (argument will be a reference to client.peer_map) to be notified of peer list updates as they are received.
#
# sample peer_map:
# 	["test_user":["test_user", None], "another_user":["another_user", None],]

# Get a peer from the list.
peer_username = None;
for _username, data in client.peer_map.iteritems():
	if username != _username:
		peer_username = _username
		break

# Connect to that peer (hole-punch)

class ConnectionCallback:
	
	def __init__(self):
		self.error_message = ""
		self.success = None
		self.client_key = None
	
	def handle_timeout(self, params=None):
		self.success = False
		self.error_message = "Connection request to server has timed-out."
	
	def complete_connection(self, peer_username, success, error_message=""):
		self.success = success
		if success:
			self.client_key = error_message
		else:
			self.error_message = error_message


buffer_size = 128
callback_object = ConnectionCallback()

client.connect_to_peer(peer_username, buffer_size, callback_object)

while callback_object.success == None:
	time.sleep(response_check_interval)

if not callback_object.success:
	print "Error: %s" % callback_object.error_message
	exit()

client_key = callback_object.client_key
udp_client = client.client_map[client_key]

# Now you can communicate with that peer.
udp_client.send_message("Greetings!")
udp_client.pop_all_messages()

'''

class STUN_Client:
	
	def __init__(self, 
			start_listen_thread=False,
			local_ip=socket.gethostbyname(socket.gethostname()),
			local_port=30779,
			server_ip=socket.gethostbyname(socket.gethostname()),
			server_port=30788,
			socket_timeout=3.0,
			peer_block_manager=None):
		
		self.local_ip = local_ip;
		self.local_port = local_port;
		self.socket_timeout = socket_timeout;
		self.peer_block_manager = peer_block_manager;
		self.thread_sleep_duration = 0.1;
		self.error_log = [];
		
		self.username = None;
		self.password = None;
		self.profile_map = {};
		self.authenticated = False;
		self.auth_callback = None;
		self.auth_keys = None;
		self.auth_timeout = 15; # 15 seconds is the limit for authentication requests. It's just a magic number like many of these timeout values.
		self.last_auth = None;
		self.login_expiration = 20; # login will expire after this many seconds passes without successful keep-alive authentication
		self.auth_keep_alive_interval = 5;
		self.auth_keep_alive_multiplier = 1; # Avoid hammering the server if it's down. Will increment every time re-auth fails, returns to 1 upon successful authentication.
		self.re_auth_ready = None;
		
		self.master_log = []; # all messages recieved
		self.message_log_map = {}; # log per message type.
		
		# this will handle callbacks for keeping track of whether the user's authentication expires (namely from losing connection to the server.)
		self.authentication_monitor_object = None; 
		
		self.hole_punch_timeout = 20;
		self.hole_punch_max_attempts = 20;
		
		self.server_response_timeout = 20;
		
		# Server response flags. Set to None when sending a request; they are flipped to True upon receiving a response. Used for determining response time-out.
		self._auth_status = None;
		self._registration_status = None; # Private. Internal use only.
		self._holepunch_status = {};
		
		self.available_ports = [[34000, 34100],] # list of ranges, e.g. ports 34000 - 34100
		self.used_ports = [];
		
		self.registration_key = None;
		
		self.udp_client_keep_alive_timeout = 30;
		
		# dictionary of active udp connections (hole-punched)
		self.client_map = {};
		self.callback_map = {};
		
		self.send_queue = [];
		
		self.connection_state = ConnectionState(False);
		
		# Initialize TCP client.
		self.init_tcp_client(server_ip, server_port);
		
		self.peer_map = {};
		
		# Start listening to the stun server.
		self.init_stun_listener();
		
		self.keep_alive_monitor = KeepAliveMonitor(self);

		self.peer_map_callback = None;
	
	def shutdown(self, stun_only=True):
		self.authenticated = False;
		self.connection_state.active = False; # kills main thread, making the logout auth sequence impossible in its current implementation (get salt/key, then perform request) which needs the main loop.
		self.stun_client.disconnect();
		if not stun_only:
			# disconnect all udp clients...
			for key, client in self.client_map.iteritems():
				client.disconnect();
			self.client_map.clear();
			self.peer_map.clear();
			del self.used_ports[:]
	
	def restart(self, stun_only=True):
		self.shutdown(stun_only);
		self.init_tcp_client(self.server_ip, self.server_port);
		self.init_stun_listener();
	
	def log_error(self, error_message, extra=None):
		err_msg = "[STUN_Server] Line #%s: %s\n\n%s" % (str(traceback.tb_lineno(sys.exc_traceback)), traceback.format_exc(), sys.exc_info());
		timestamp = time.time();
		date_string = datetime.datetime.fromtimestamp(timestamp).strftime('(%Y-%m-%d) %H:%M:%S')
		self.error_log.append((timestamp, date_string, err_msg, extra));
	
	def monitor_response(self, target_object, target_key=None, timeout=20, callback=None, callback_params=None, timeout_callback=None, timeout_callback_params=None):
		"""Waits until target is no longer null or timeout occurs. Timeout is in seconds. target_object and target_key should be strings.
		If target key is not null, then target_object will be treated as a dictionary (using target_key for the index).
		
		This function is best utilized on its own separate thread."""
		# Wait until salt and key have been retrieved or timeout occurs.
		time_elapsed = 0;
		start_time = time.time();
		target_attribute = getattr(self, target_object);
		target = None;
		
		connection_state = self.connection_state
		
		#print "Monitoring for %s" % target_object;
		
		# Behold, python lambda expressions in the wild!
		if target_key == None:
			target = lambda parent: getattr(parent, target_object);
		else:
			target = lambda parent: getattr(parent, target_object)[target_key];
		
		while time_elapsed < timeout:
			time_elapsed = time.time() - start_time;
			# check for shutdown.
			if not connection_state.active:
				return;
			
			# check for target condition
			if target(self) != None:
				break;
			time.sleep(self.thread_sleep_duration);
		
		# Check for timeout.
		if target(self) == None:
			#print "Timeout on %s" % target_object;
			has_timeout_callback = timeout_callback != None;
			if has_timeout_callback:
				if timeout_callback_params != None:
					timeout_callback(timeout_callback_params);
				else:
					timeout_callback();
			return;
		#else:
		#	print "No timeout on %s" % target_object;
		
		# Success, run the callback if one was provided (maybe not if one is only concerned with the timeout event).
		if callback != None:
			if callback_params != None:
				callback(target_object, target_key, callback_params);
			else:
				callback(target_object, target_key);
	
	def authenticate_thread(self, username, password, callback_object=None, login=True):
		# callback_object should have a complete_authentication(success, error_message) method.
		self.username = username;
		self.password = password;
		self.auth_callback = callback_object;
		
		timeout_handler = None;
		has_timeout_handler = ((callback_object != None) and (hasattr(callback_object, "handle_timeout")))
		if has_timeout_handler:
			timeout_handler = callback_object.handle_timeout
		
		# Send salt and dynamic key retrieval request.
		self.auth_keys = None;
		message = "auth_salt_request %s" % username;
		if not self.stun_send_message(message):
			#callback_object.complete_authentication(False, "Failed to connect to the server.");
			if timeout_handler != None:
				timeout_handler("Failed to connect to the server.");
			return;
		
		# Wait until salt and key have been retrieved or timeout occurs.
		self.monitor_response("auth_keys", None, self.server_response_timeout, self.authenticate_send_credentials, [login, callback_object], timeout_handler, "Server failed to respond.");
		
	
	def authenticate_send_credentials(self, target_object=None, target_key=None, params=None):
		callback_object = None;
		if params != None:
			callback_object = params[1];
		login = params[0]
		# hash the password
		salt, dynamic_key = self.auth_keys;

		if not salt:
			if callback_object != None:
				callback_object.complete_authentication(False, "Failed to connect to the server.");
				return;
		
		salted_password = "%s%s" % (salt, self.password)
		hashed_salted_password = hashlib.sha384(salted_password).hexdigest();
		#print "hash1: %s\n" % hashed_salted_password;
		key_and_hash = "%s%s" % (dynamic_key, hashed_salted_password)
		hashed_password = hashlib.sha384(key_and_hash).hexdigest();
		#print "hash2: %s" % hashed_password;
		
		self._auth_status = None;
		# Send authentication request.
		message = "authenticate %s" % json.dumps([self.username, hashed_password, login, json.dumps(self.available_ports), json.dumps(self.used_ports)]);
		if not self.stun_send_message(message):
			if callback_object != None:
				callback_object.complete_authentication(False, "Failed to connect to the server.");
				return;
		
		timeout_handler = None;
		has_timeout_handler = ((callback_object != None) and (hasattr(callback_object, "handle_timeout")))
		if has_timeout_handler:
			timeout_handler = callback_object.handle_timeout
		
		self.monitor_response("_auth_status", None, self.server_response_timeout, None, None, timeout_handler);
	
	def registration_completion_handler(self, target_object, target_key, params):
		callback_object = params;
		registration_handler = None;
		has_registration_handler = ((callback_object != None) and (hasattr(callback_object, "complete_registration")))
		if has_registration_handler:
			callback_object.complete_registration(True, "");

	def send_encrypted_registration_request(self, target_object=None, target_key=None, params=None):
		username, password, profile_map, callback_object, registration_type = params;
		
		self._registration_status = None;
		
		# Construct the message.
		message = "%s" % json.dumps([username, password, profile_map, registration_type]);
		
		# Encrypt the message.
		public_key = RSA.importKey(self.registration_key)
		message = public_key.encrypt(message, 32);
		
		# Tack on the username in plain text and json_encode again. The STUN Server needs to username to determine which private key to use to decrypt the message.
		message = "register %s %s" % (username, message[0]);
		
		if not self.stun_send_message(message):
			callback_object.complete_registration(False, "Failed to connect to the server.");
			return;
		
		timeout_handler = None;
		has_timeout_handler = ((callback_object != None) and (hasattr(callback_object, "handle_timeout")))
		if has_timeout_handler:
			timeout_handler = callback_object.handle_timeout

		# Wait until salt and key have been retrieved or timeout occurs.
		self.monitor_response("_registration_status", None, self.server_response_timeout, self.registration_completion_handler, callback_object, timeout_handler);
	
	def register_thread(self, username, password, profile_map, callback_object=None, registration_type="permanent"):
		# callback_object should have a complete_registration(success, error_message) method.
		self.username = username;
		self.password = password;
		self.profile_map = profile_map;
		self.register_callback = callback_object;
		
		self.registration_key = None;
		message = "register_key %s" % username;
		if not self.stun_send_message(message):
			callback_object.complete_registration(False, "Failed to connect to the server.");
			return;
		
		timeout_handler = None;
		has_timeout_handler = ((callback_object != None) and (hasattr(callback_object, "handle_timeout")))
		if has_timeout_handler:
			timeout_handler = callback_object.handle_timeout
		
		params = [username, password, profile_map, callback_object, registration_type];
		self.monitor_response("registration_key", None, self.server_response_timeout, self.send_encrypted_registration_request, params, timeout_handler);

	def authenticate(self, username, password, callback_object=None, login=True):
		"""Non-blocking. Sends a user authentication request."""
		# Spawn a separate thread to perform authentication. This is to keep from blocking the caller, since a callback is expected to handle results.
		Thread(target=self.authenticate_thread, args=(username, password, callback_object, login)).start();
	
	def maintain_authentication(self, callback_object=None):
		#self.authentication_monitor_object
		username = self.username
		password = self.password
		last_auth = self.last_auth
		self.re_auth_ready = True;
		while self.authenticated:
			last_reauth = self.keep_alive_monitor.last_reauth_attempt;
			now = time.time();
			ready_time = last_reauth + (self.auth_keep_alive_multiplier * self.auth_keep_alive_interval);
			time_for_another_reauth_attempt = now >= ready_time;
			
			# By re_auth_ready, I'm saying a re-authentication attempt isn't currently in progress. Yes, it's a poorly named variable. 
			# I'll need to rename it something better. Maybe later (trademark).
			if self.re_auth_ready and time_for_another_reauth_attempt:
				self.re_auth_ready = False;
				self.authenticate(self.username, self.password, self.keep_alive_monitor);
				
			time.sleep(self.thread_sleep_duration);
	
	def logout(self):
		self.authenticated = False;
		self.authenticate(self.username, self.password, self.keep_alive_monitor, False);

	def register(self, username, password, profile_map, callback_object=None, registration_type="permanent"):
		"""Non-blocking. Sends a user registration request. 
		Only type of registration available for now is 'permanent'. Temporary to come later, maybe (for guests/'unregistered' users).
		Note that profile_map should be a json-encoded string (you can store arbitrary data here)."""
		# Spawn a separate thread to perform registration. This is to keep from blocking the caller, since a callback is expected to handle results.
		Thread(target=self.register_thread, args=(username, password, profile_map, callback_object, registration_type)).start();

	def init_tcp_client(self, server_ip, server_port, buffer_size=1024):
		self.server_ip = server_ip;
		self.server_port = server_port;
		self.stun_client = tcp.TCP_Client(server_ip, server_port, buffer_size);
	
	def init_stun_listener(self):
		self.connection_state = ConnectionState(True);
		Thread(target=self.stun_listen_loop).start();

	def stun_send_message(self, message, json_encode=False, prepare=True):
		try:
			self.stun_client.send_message(message, json_encode, prepare);
			return True;
		except:
			return False;

	def stun_listen_loop(self):
		connection_state = self.connection_state
		message_object = None
		while self.connection_state.active:
			try:
				message_object = self.stun_client.pop_message();
				is_valid_message = ((message_object != None) and (len(message_object) > 2));
				self.master_log.append(message_object);
				if is_valid_message:
					message = message_object[2];
					message_type, message_body = message.split(" ",1);
					if message_type not in self.message_log_map:
						self.message_log_map[message_type] = [];
					self.message_log_map[message_type].append(message_object);
					#print "MESSAGE: %s\n" % message_object;
					
					if(message_type == "peer_map"):
						# peer data should be [[peer_username, public_profile_map], ...]
						message_data = json.loads(message_body);
						self.update_peer_map(message_data);
						if self.peer_map_callback != None:
							self.peer_map_callback(self.peer_map);
					
					elif(message_type == "hole_punch"):
						peer_allowed = True;
						# message body should be [listen_ip, listen_port, peer_ip, peer_port, peer_username, buffer_size]
						message_data = json.loads(message_body);
						listen_ip, listen_port, peer_ip, peer_port, peer_username, buffer_size = message_data
						port_in_use = False;
						
						# Ensure port isn't already in use.
						if listen_port in self.used_ports:
							port_in_use = True;
							self.stun_send_message("hole_punch_reject %s" % json.dumps([listen_ip, listen_port, self.username, peer_ip, peer_port, peer_username, buffer_size, port_in_use]));
							continue;
						message_body = json.dumps([listen_ip, listen_port, self.username, peer_ip, peer_port, peer_username, buffer_size, port_in_use]);
						
						if(self.peer_block_manager != None):
							peer_allowed = self.peer_block_manager.is_peer_allowed(message_data);
						if(peer_allowed):
							self.stun_send_message("hole_punch_ack %s" % message_body);
						else:
							self.stun_send_message("hole_punch_reject %s" % message_body);
						
					elif(message_type == "hole_punch_request_rejected"):
						# Deals with requests that fail due to lack of authentication (this client or the target client) or target client doesn't exist.
						# message_body should be [listen_ip, listen_port, self.username, target_ip, target_port, username, buffer_size]
						fail_type, target_username, error_message = json.loads(message_body);
						if target_username in self.callback_map:
							callback_object = self.callback_map[target_username];
							callback_object.complete_connection(target_username, False, error_message);
							del self.callback_map[target_username];
						
					elif(message_type == "hole_punch_rejected"):
						# message_body should be [listen_ip, listen_port, self.username, target_ip, target_port, username, buffer_size]
						message_data = json.loads(message_body);
						listen_ip, listen_port, self.username, target_ip, target_port, username, buffer_size = message_data
						
						client_key = "%s-%s-%s" % (target_ip, target_port, username);
						
						callback_object = None;
						if client_key in self.callback_map:
							callback_object = self.callback_map[client_key]
						
						if callback_object  != None:
							callback_object.complete_connection(client_key, False, "Peer rejected the connection request.");
							del self.callback_map[client_key];
						
					elif(message_type == "init_hole_punch"):
						try:
							listen_ip, listen_port, peer_ip, peer_port, peer_username, buffer_size = json.loads(message_body);
							if listen_port not in self.used_ports:
								self.used_ports.append(listen_port);
							# No else. We're just going to hope there's no way for that if to not run, and that we're just being half-assed at feeling paranoid.
							# My mind is feeling like it's been twisted into a few knots at this point, to be honest.
							Thread(target=self.connect_to_remote_peer, args=(listen_ip, listen_port, peer_ip, peer_port, buffer_size, peer_username)).start();
							client_key = "%s_%s_%s" % (peer_ip, peer_port, peer_username)
							if peer_username in self._holepunch_status:
								self._holepunch_status[peer_username] = True;
							if peer_username in self.callback_map:
								self.callback_map[client_key] = self.callback_map[peer_username];
								del self.callback_map[peer_username]
						except Exception as e:
							self.log_error(e);
					
					elif(message_type == "auth_keys"):
						# message body should be [salt, dynamic_key]
						self.auth_keys = json.loads(message_body);
					
					elif(message_type == "auth_response"):
						# message body should be [success, username, profile_map, login, error_message]
						success, username, profile_map, login, error_message = json.loads(message_body);
						self._auth_status = True;
						new_auth = not self.authenticated;
						if success:
							if login:
								self.authenticated = True;
								self.auth_keep_alive_multiplier = 1;
								self.last_auth = time.time();
								self.username = username;
								self.profile_map = profile_map;
								if new_auth:
									Thread(target=self.maintain_authentication).start();
							else:
								self.authenticated = False;
								self.auth_keep_alive_multiplier = 1;
								self.last_auth = time.time();
								self.username = username;
								self.profile_map = profile_map;
						if self.auth_callback != None:
							self.auth_callback.complete_authentication(success, error_message);
					
					elif(message_type == "registration_key"):
						# message body should be "public_key"
						self.registration_key = message_body;
					
					elif(message_type == "registration_response"):
						# message body should be [success, username, profile_map, error_message]
						success, username, profile_map, error_message = json.loads(message_body);
						if success:
							self.username = username;
							self.profile_map = profile_map;
							self._registration_status = True;
						if self.registration_callback != None:
							self.register_callback.complete_registration(success, error_message);
					
			except Exception as exc:
				self.log_error(exc, message_object);
			
			time.sleep(self.thread_sleep_duration);

	def update_peer_map(self, packet):
		username_list = [];
		current_username_list = self.peer_map.keys();
		for user_block in packet:
			peer_username, profile_map = user_block;
			valid_username = ((peer_username != None) and (peer_username.replace(" ","").replace("\t","").replace("\n","").replace("\r","") != ""));
			if valid_username:
				username_list.append(peer_username);
				self.peer_map[peer_username] = user_block;
		remove_username_list = [];
		for username in current_username_list:
			if username not in username_list:
				remove_username_list.append(username);

		for username in remove_username_list:
			del self.peer_map[username];
	
	def auto_select_local_endpoint(self):
		listen_ip = self.local_ip;
		range_count = len(self.available_ports);
		for i in range(0, range_count):
			x = range_count - (1 + i)
			port_range = self.available_ports[x]
			port_count = port_range[1] - port_range[0]
			for j in range(0, port_count):
				port = port_range[1] - j;
				if port not in self.used_ports:
					return (listen_ip, port);
		return None;

	def connect_to_peer(self, target_username, buffer_size, callback_object=None, listen_ip = None, listen_port = None):
		""" callback_object should have a complete_connection(target, success, error_message) method where success is True or False.
		Extract info with: 
		 	ip, port, username = target.split("-",2)
		Returns False if it fails to send request message (e.g. peer is blocked or connection to server failed.). 
		"""
		local_endpoint_not_specified = ((listen_ip == None) or (listen_port == None))
		if local_endpoint_not_specified:
			try:
				listen_ip, listen_port = self.auto_select_local_endpoint();
			except:
				callback_object.complete_connection(client_key, False, "All available allowed local ports are already in use. Cannot initiate connection to peer.");
				return False;
		
		# Disallow connecting to yourself. What are you trying to pull?
		if self.username == target_username:
			callback_object.complete_connection(client_key, False, "You cannot connect to yourself.");
			return False;
		
		# disallow connecting to blocked peers.
		if(self.peer_block_manager != None):
			peer_allowed = self.peer_block_manager.is_peer_allowed([target_username, buffer_size]);
			if not peer_allowed:
				callback_object.complete_connection(client_key, False, "This peer has been blocked.");
				return False;
		client_key = target_username;
		self.callback_map[client_key] = callback_object;
		
		self._holepunch_status[client_key] = None;
		
		# Start hole_punch process.
		message = "request_hole_punch %s" % json.dumps([listen_ip, listen_port, self.username, target_username, buffer_size])
		if not self.stun_send_message(message):
			callback_object.complete_connection(client_key, False, "Failed to connect to the server.");
			del self.callback_map[client_key];
			return False;
		
		timeout_handler = None;
		has_timeout_handler = ((callback_object != None) and (hasattr(callback_object, "handle_timeout")))
		if has_timeout_handler:
			timeout_handler = callback_object.handle_timeout
		# Wait until salt and key have been retrieved or timeout occurs.
		Thread(target=self.monitor_response, args=("_holepunch_status", client_key, self.server_response_timeout, None, None, timeout_handler)).start();
		
		return True;

	def connect_to_remote_peer(self, local_ip, local_port, target_ip, target_port, buffer_size, username):
		"""Warning: Internal use only!"""
		print "Connecting to remote peer."
		udp_client = udp.UDP_Client(True, local_ip, local_port, target_ip, target_port, buffer_size, True);
		client_key = "%s_%s_%s" % (target_ip, target_port, username)
		
		callback_object = None;
		if client_key in self.callback_map:
			callback_object = self.callback_map[client_key]
		
		if self.hole_punch(udp_client, self.hole_punch_max_attempts, self.hole_punch_timeout):
			print "Hole-punch succeeded."
			if callback_object != None:
				callback_object.complete_connection(username, True, client_key);
			self.client_map[client_key] = udp_client; # success, add it to the map.
		else:
			print "Hole-punch failed."
			# remove that port from the used ports list.
			port_count = len(self.used_ports);
			for i in range(0, port_count):
				if self.used_ports[i] == local_port:
					del self.used_ports[i]
					break;
			
			# run the callback, if there is one.
			if callback_object != None:
				callback_object.complete_connection(client_key, False, "Failed to connect to peer.");

	def hole_punch_send_loop(self, udp_client, maximum_retries=20, delay=0.5):
		
		for i in range(0, maximum_retries):
			udp_client.send_message("syn", False, False);
			time.sleep(delay);

	# Create and return a udp socket that has established connection with the target peer, or None if it fails.
	def hole_punch(self, udp_client, maximum_retries=20, timeout=20):
		print "Performing hole-punch."
		delay = 0.5
		result = False;
		connection_state = self.connection_state
		Thread(target=self.hole_punch_send_loop, args=(udp_client, maximum_retries, delay)).start();
		start_time = time.time();
		for i in range(0, maximum_retries):
			time.sleep(delay)
			if not connection_state.active:
				# give up and close it out.
				udp_client.disconnect();
				print "Fail 1";
				return False;
			packet = "";
			try:
				packet = udp_client.pop_message();
			except:
				pass;
			
			if packet != None:
				print "hole_punch_response: " + str(packet);
				
				if len(packet) >= 3:
					# check the packet.
					if(packet[2] == "syn"):
						udp_client.send_message("ack", False, False); # send acknowledge
					elif(packet[2] == "ack"):
						udp_client.send_message("ack2", False, False); # send ack ack and return socket.
						result = True;
						print "Success 1";
						break;
					elif(packet[2] == "ack2"):
						result = True; # ack ack received, return socket.
						print "Success 2";
						break;
			
			# check for timeout
			time_elapsed = time.time() - start_time;
			if(time_elapsed >= timeout):
				print "Fail 2";
				break;
		
		return result;


class KeepAliveMonitor:
	
	def __init__(self, parent):
		self.parent = parent;
		self.last_reauth_attempt = time.time();
	
	def complete_authentication(self, success, error_message=""):
		self.parent.re_auth_ready = True;
		self.last_reauth_attempt = time.time();
		if not success:
			self.parent.auth_keep_alive_multiplier += 1;
		
	
	def handle_timeout(self, params=None):
		self.last_reauth_attempt = time.time();
		self.parent.re_auth_ready = True;
		self.parent.auth_keep_alive_multiplier += 1;
