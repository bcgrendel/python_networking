import socket
import tcp
import udp
import stun_client
import time

import yaml

def x(data):
	print yaml.dump({"data":data}, default_flow_style=False)

def y(data):
	print data[2]

start_listening = True
local_ip = socket.gethostbyname(socket.gethostname())
local_port = 30779
server_ip = socket.gethostbyname(socket.gethostname())
server_port = 30788
socket_timeout = 3.0
peer_block_manager = None

response_check_interval = 0.1

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
	
	def complete_registration(self, success, error_message=""):
		self.success = success
		self.error_message = error_message


username = "test_user"
password = "test_pass123"
profile_map = {}

class AuthCallback:
	
	def __init__(self):
		self.error_message = ""
		self.success = None
	
	def handle_timeout(self, params=None):
		self.success = False
		self.error_message = "Authentication request to server has timed-out."
		print self.error_message
	
	def complete_authentication(self, success, error_message=""):
		self.success = success
		self.error_message = error_message

callback_object = AuthCallback()

login = True # this authentication is to login. It'd be False if we wanted to log out.
client.authenticate(username, password, callback_object, login)


while callback_object.success == None:
	time.sleep(response_check_interval)

if not callback_object.success:
	print "Error [%s]: %s" % (callback_object.success, callback_object.error_message)
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
