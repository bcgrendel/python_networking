import socket
import sys
import os
import traceback
import struct
import threading
from threading import Thread
import time
from datetime import date, timedelta
import datetime
import json
import buffered_message
import psycopg2

from connection_state import ConnectionState
import tcp

import sqlalchemy
from sqlalchemy import func
import stun_alchemy
from stun_alchemy import Stun_User

from Crypto.PublicKey import RSA
from Crypto import Random

import re

orig_path = os.getcwd()
os.chdir("../")
sys.path.insert(0, os.getcwd())
os.chdir(orig_path)

from auth import auth
import hashlib

# *************
# EXAMPLE USAGE
# *************
"""
import os
import socket
import tcp
import udp
import stun_server

import yaml

def x(data):
	print yaml.dump({"data":data}, default_flow_style=False)

start_listening = True
buffer_size = 1024
local_ip = socket.gethostbyname(socket.gethostname())
local_port = 30788
database_config_file = "%s/database_conf.json" % os.path.dirname(os.path.realpath("database_conf.json")) # "%s/database_conf.json" % os.path.dirname(os.path.realpath(__file__))

server = stun_server.STUN_Server(start_listening, buffer_size, local_ip, local_port, database_config_file)

if __name__ == "__main__":
	
	# Keep this process running until Enter is pressed
	print "Press Enter to quit..."
	try:
		sys.stdin.readline()
	except:
		pass
	server.shutdown()
"""

# pk.exportkey("OpenSSH")

# comm = udp.UDP_Communications(True)
# comm.send_message([5,6,7], True)
# comm.pop_message(True)

class STUN_Server:
	
	def __init__(self, 
			start_listen_thread=False,
			buffer_size=1024,
			local_ip=socket.gethostbyname(socket.gethostname()),
			local_port=30788,
			database_config_file=None):
		self.local_ip = local_ip
		self.local_port = local_port
		self.buffer_size = buffer_size
		self.database_config_file = database_config_file
		self.thread_sleep_duration = 0.1
		self.metainfo_update_thread_sleep_duration = 0.5
		self.peer_timeout = 20 # measured in seconds
		self.peer_map = {}
		self.error_log = []
		
		self.master_log = [] # all messages recieved
		self.message_log_map = {} # log per message type.
		
		self.key_map = {} # RSA key map for peers attempting registration.
		
		self.connection_state = ConnectionState(False)
		if start_listen_thread:
			self.activate()
	
	def log_error(self, error_message, extra=None):
		err_msg = "[STUN_Server] Line #%s: %s\n\n%s" % (str(traceback.tb_lineno(sys.exc_traceback)), traceback.format_exc(), sys.exc_info())
		timestamp = time.time()
		date_string = datetime.datetime.fromtimestamp(timestamp).strftime('(%Y-%m-%d) %H:%M:%S')
		self.error_log.append((timestamp, date_string, err_msg, extra))
	
	def shutdown(self):
		self.connection_state.active = False
		self.tcp_server.disconnect()
	
	def restart(self):
		self.shutdown()
		self.activate()

	def activate(self, local_ip=None, local_port=None, buffer_size=None):
		self.local_ip = local_ip if local_ip != None else self.local_ip
		self.local_port = local_port if local_port != None else self.local_port
		self.buffer_size = buffer_size if buffer_size != None else self.buffer_size
		
		self.connection_state.active = False
		self.connection_state = ConnectionState(True)
		if(self.database_config_file == None):
			# attempt to get the current directory path (networking module) and assume a database_conf.json is there.
			self.database_config_file = "%s/database_conf.json" % os.path.dirname(os.path.realpath(__file__))
		self.load_database_settings()
		#self.init_database() # legacy direct sql connection init method. Replaced with SqlAlchemy ORM.
		
		self.init_tcp_server(self.local_ip, self.local_port, self.buffer_size)
		
		Thread(target=self.meta_watch).start()
		Thread(target=self.main_listen_loop).start()
			
	def load_database_settings(self):
		contents = ""
		f = open(self.database_config_file, "r+")
		contents = f.read()
		f.close()
		db_config_map = json.loads(contents)
		self.hostname = db_config_map["hostname"]
		self.db_username = db_config_map["username"]
		self.db_password = db_config_map["password"]
		self.db_name = db_config_map["database"]
		
	def init_database(self):
		try:
			if(self.hasattr("db_connection")):
				self.db_connection.close()
		except:
			pass;
		#connection_string = "dbname=%s user=%s password=%s host=%s" % (self.db_name, self.db_username, self.db_password, self.hostname);
		#self.db_connection = psycopg2.connect(connection_string); # cursors are not thread-safe, so create them separately for each thread.
	
	def init_tcp_server(self, local_ip=socket.gethostbyname(socket.gethostname()), local_port=30788, buffer_size=1024):
		self.local_ip = local_ip;
		self.local_port = local_port;
		self.buffer_size = buffer_size;
		self.tcp_server = tcp.TCP_Server(self.local_ip, self.local_port, self.buffer_size);
	
	def get_active_peer_map(self):
		session = stun_alchemy.Session();
		
		active_time = datetime.datetime.utcnow() - timedelta(seconds=self.peer_timeout); # <peer_timeout> seconds into the past.
		
		results = [];
		try:
			resultset = session.query(Stun_User).\
					filter(Stun_User.last_active >= active_time).\
					filter(Stun_User.logged_in == True).\
					order_by(Stun_User.username).\
					all();
			for user in resultset:
				results.append([user.username, user.profile_map]);
		except:
			results = [];
		
		session.close();
		
		return results;
	
	def generate_rsa_keys(self):
		random_generator = Random.new().read
		key = RSA.generate(1024, random_generator)
		return key;
	
	def generate_registration_key(self, ip_address, port, username):
		key = self.generate_rsa_keys();
		client_key = "%s_%s_%s" % (ip_address, port, username);
		self.key_map[client_key] = key;
		
		public_key = key.publickey();
		public_key_string = public_key.exportKey("OpenSSH");
		
		response = "registration_key %s" % public_key_string;
		recipients = [(ip_address, port),];
		self.tcp_server.send_message(response, recipients);

	def get_salt_and_key(self, username, ip_address, port):
		result = None;
		session = stun_alchemy.Session();
		resultset = session.query(Stun_User).filter(Stun_User.username == username).all();

		self.resultset = [resultset, username, ip_address, port]
		if len(resultset) < 1:
			session.close();
			return auth.create_fake_salt_and_key(username, "sda8901234lfk");
		user = resultset[0];
		
		dynamic_key = auth.get_dynamic_key(stun_alchemy.Session, Stun_User, user, True); # force new key
		salt = auth.extract_salt_from_key(user.salt_key);
		result = [salt, dynamic_key];
		
		user.auth_ip_address = ip_address;
		user.auth_port = port;
		session.commit();
		session.close();
		return result;

	def authenticate_user(self, username, password, ip_address, port, login=True, available_ports=None, used_ports=None):
		result = (False, None, "Invalid username/password.");
		session = stun_alchemy.Session();
		
		results = session.query(Stun_User).\
			filter(Stun_User.username == username).\
			filter(Stun_User.auth_ip_address == ip_address).\
			filter(Stun_User.auth_port == port).\
			all();
		
		if len(results) < 1:
			session.close();
			return (False, None, "Invalid username/password.");
		user = results[0];
		result = auth.auth_password(stun_alchemy.Session, Stun_User, user, password, ip_address);
		if result:
			user.last_active = datetime.datetime.utcnow();
			user.ip_address = ip_address;
			user.port = port;
			user.logged_in = login;
			if available_ports != None:
				user.available_ports = available_ports
			if used_ports != None:
				user.used_ports = used_ports
			session.commit();
			result = (True, user.profile_map, None);
		session.close();
		return result;
	
	def is_authenticated(self, username, ip_address, port):
		result = False;
		time_out = datetime.datetime.utcnow() - timedelta(seconds = self.peer_timeout);
		session = stun_alchemy.Session();
		results = session.query(Stun_User).\
			filter(Stun_User.username == username).\
			filter(Stun_User.auth_ip_address == ip_address).\
			filter(Stun_User.auth_port == port).\
			filter(Stun_User.last_active >= time_out).\
			filter(Stun_User.logged_in == True).\
			all();
		
		if len(results) < 1:
			result = False;
		else:
			result = True;
		
		session.close();
		return result;
	
	def user_is_active(self, username):
		result = None;
		time_out = datetime.datetime.utcnow() - timedelta(seconds = self.peer_timeout);
		session = stun_alchemy.Session();
		results = session.query(Stun_User).\
			filter(Stun_User.username == username).\
			filter(Stun_User.last_active >= time_out).\
			filter(Stun_User.logged_in == True).\
			all();
		
		if len(results) < 1:
			result = None;
		else:
			result = results[0];
		
		session.close();
		return result;
	
	def check_login_status_of_all_users(self):
		session = stun_alchemy.Session();
		try:
			resultset = session.query(Stun_User).\
					filter(Stun_User.logged_in == True).\
					order_by(Stun_User.username).\
					all();
			for user in resultset:
				if not self.user_is_active(user.username):
					user.logged_in = False;
			session.commit();
		except:
			pass;
		
		session.close();
	
	def is_acceptable_password(self, password):
		"""Returns True only if password length >= 8 and contains both letters and numbers 
		Note: special characters are allowed, but they are merely optional.  They do not count towards the alphanumeric requirement."""
		has_alphas_and_numbers = re.match(r"^(?=.+[\w])(?=.+[\d])",password) != None;
		return (has_alphas_and_numbers and (len(password) >= 8))

	def register_user(self, username, password, profile_map, ip_address, port, registration_type="permanent"):
		result = (False, username, profile_map, "Error: Registration failed.");
		session = stun_alchemy.Session();
		
		if not self.is_acceptable_password(password):
			session.close();
			return (False, "Invalid password. Password must be at least 8 characters long and contain both letters and numbers (special characters are optional).");
		
		results = session.query(Stun_User).filter(func.lower(Stun_User.username) == func.lower(username)).all();
		if len(results) >= 1:
			session.close();
			return (False, username, profile_map, "Username is already in use.");
		
		result = [True, username, profile_map, None];
		salt_key = auth.create_saltkey(username);
		salt = auth.extract_salt_from_key(salt_key)
		salt_and_pass = "%s%s" % (salt, password)
		hashed_password = hashlib.sha384(salt_and_pass).hexdigest();

		user = Stun_User(username=username, password=hashed_password, ip_address=ip_address, port=port, salt_key=salt_key, profile_map=json.dumps(profile_map), logged_in=False);
		session.add(user);
		session.commit();
		
		session.close();
		return result;
	
	def get_unused_port(self, user):
		result = None;
		if user.available_ports == None:
			return None;
		
		available_ports = json.loads(user.available_ports);
		used_ports = json.loads(user.used_ports);

		print "available_ports: %s" % available_ports;
		
		for port_range in available_ports:
			for i in range(port_range[0], port_range[1]):
				if i not in used_ports:
					return i;
		
		return result;
	
	def update_user_used_ports(self, user, port):
		session = stun_alchemy.Session();
		
		used_ports = json.loads(user.used_ports);
		used_ports.append(port);
		
		user.used_ports = json.dumps(used_ports);
		session.commit();
		session.close();
	
	def meta_watch(self):
		# in charge of maintaining up-to-date information on users online, their meta data (username, ip, port, and whatever else), and anything else that needs to be reported to clients.
		connection_state = self.connection_state
		server = self.tcp_server
		while connection_state.active:
			# Check all logged-in users to see if still logged in.
			self.check_login_status_of_all_users();
			
			# Grab peer data from db.
			self.peer_map = self.get_active_peer_map();
			
			# Notify all clients of the list of peers.
			response = "peer_map %s" % json.dumps(self.peer_map);
			self.tcp_server.send_message(response);
			
			time.sleep(self.metainfo_update_thread_sleep_duration);
	
	def handle_hole_punch_request(self, message_body, ip_address, port):
		# message_body should be [ip, port, requestee_username, target_ip, target_port, target_username, buffer_size]
		message_data = json.loads(message_body);
		requestee_ip, requestee_port, username, target_username, buffer_size = message_data
		# confirm the requestee is authenticated before proceeding.
		if not self.is_authenticated(username, ip_address, port):
			recipients = [(ip_address, port),];
			response = "hole_punch_request_rejected %s" % json.dumps([0, target_username, "You're not logged in."]);
			self.tcp_server.send_message(response, recipients);
			return False;
		
		# confirm the target user exists and is active.
		peer = self.user_is_active(target_username);
		if not peer:
			recipients = [(ip_address, port),];
			response = "hole_punch_request_rejected %s" % json.dumps([1, target_username, "Peer isn't available (not logged in / doesn't exist)."]);
			self.tcp_server.send_message(response, recipients);
			return False;
		
		# send request to target_user
		selected_port = self.get_unused_port(peer);
		
		# mark it as used (might be overwritten again by a re-auth request, but at any rate, 
		# it's a small window for screwing up and will correct itself naturally anyway - client will reject if it's already attempting to hole punch on a port). 
		self.update_user_used_ports(peer, selected_port);
		
		response_data = [peer.auth_ip_address, selected_port, requestee_ip, requestee_port, username, buffer_size];
		#  [listen_ip, listen_port, peer_ip, peer_port, peer_username, buffer_size]
		
		recipients = [(peer.auth_ip_address, peer.auth_port),];
		response = "hole_punch %s" % json.dumps(response_data);
		self.tcp_server.send_message(response, recipients);
		
		return True;
	
	def main_listen_loop(self):
		connection_state = self.connection_state;
		server = self.tcp_server;
		message_object = None
		while connection_state.active:
			try:
				message_object = self.tcp_server.pop_message();
				self.master_log.append(message_object);
				is_valid_message = ((message_object != None) and (len(message_object) > 2));
				if is_valid_message:
					message = message_object[2];
					message_type, message_body = message.split(" ",1);
					if message_type not in self.message_log_map:
						self.message_log_map[message_type] = [];
					self.message_log_map[message_type].append(message_object);
					#print "MESSAGE: %s\n" % message_object;
					ip_address, port = message_object[0];
					if(message_type == "auth_salt_request"):
						# message_body should be [username, ]
						message_data = message_body;
						username = message_data;
						# get the salt and key
						salt_and_key = self.get_salt_and_key(username, ip_address, port);
						
						response = "auth_keys %s" % json.dumps(salt_and_key);
						recipients = [(ip_address, port),];
						self.tcp_server.send_message(response, recipients);
						
					elif(message_type == "authenticate"):
						# message_body should be [username, hashed_password, login, available_ports, used_ports]
						username, hashed_password, login, available_ports, used_ports = json.loads(message_body);
						recipients = [(ip_address, port),];
						
						success, profile_map, error_message = self.authenticate_user(username, hashed_password, ip_address, port, login, available_ports, used_ports);
						
						response_data = [success, username, profile_map, login, error_message]
						response = "auth_response %s" % json.dumps(response_data);
						
						self.tcp_server.send_message(response, recipients);
						
					elif(message_type == "register_key"):
						# message_body should be "username"
						username = message_body;
						Thread(target=self.generate_registration_key, args=(ip_address, port, username)).start();
						
					elif(message_type == "register"):
						# contents username encrypted_string **ENCRYPTED_STRING**: [username, password, profile_map, registration_type]
						username, encrypted_string = message_body.split(" ", 1);
						client_key = "%s_%s_%s" % (ip_address, port, username);
						key = self.key_map[client_key];
						json_string = key.decrypt(encrypted_string);
						username, password, profile_map, registration_type = json.loads(json_string);
						
						response_data = self.register_user(username, password, profile_map, ip_address, port, registration_type);
						response = "registration_response %s" % json.dumps(response_data);
						
						recipients = [(ip_address, port),];
						self.tcp_server.send_message(response, recipients);
						
					elif(message_type == "request_hole_punch"):
						self.handle_hole_punch_request(message_body, ip_address, port);
						
					elif(message_type == "hole_punch_ack"):
						# message_body should be [username, ]
						message_data = json.loads(message_body);
						target_ip, target_port, target_username, requestee_ip, requestee_port, requestee_username, buffer_size, port_in_use = message_data
						
						# message to send: listen_ip, listen_port, peer_ip, peer_port, peer_username, buffer_size
						requestee = self.user_is_active(requestee_username);
						if requestee != None:
							message_body = json.dumps([requestee_ip, requestee_port, target_ip, target_port, target_username, buffer_size]);
							# Send init signal to requestee
							response = "init_hole_punch %s" % message_body;
									
							recipients = [(requestee.auth_ip_address, requestee.auth_port),];
							self.tcp_server.send_message(response, recipients);
							
							message_body = json.dumps([target_ip, target_port, requestee_ip, requestee_port, requestee_username, buffer_size]);
							# Send init signal to target.
							response = "init_hole_punch %s" % message_body;
							
							recipients = [(ip_address, port),];
							self.tcp_server.send_message(response, recipients);
						
						
					elif(message_type == "hole_punch_reject"):
						# message_body should be [target_ip, target_port, target_username, requestee_ip, requestee_port, requestee_username, buffer_size, port_in_use]
						message_data = json.loads(message_body);
						target_ip, target_port, target_username, requestee_ip, requestee_port, requestee_username, buffer_size, port_in_use = message_data
						
						message_body = json.dumps([requestee_ip, requestee_port, requestee_username, target_username, buffer_size])
						requestee = self.user_is_active(requestee_username);
						if port_in_use:
							# Assuming the requestee still exists and is logged in and active, get another port and make another hole_punch request to the target user.
							if requestee != None:
								self.handle_hole_punch_request(message_body, requestee.auth_ip_address, requestee.auth_port);
						else:
							# Inform the requestee that the request was rejected.
							if requestee != None:
								response = "hole_punch_request_rejected %s" % message_body;
								
								recipients = [(requestee.auth_ip_address, requestee.auth_port),];
								self.tcp_server.send_message(response, recipients);
						
			except Exception as exc:
				self.log_error(exc, message_object);
			time.sleep(self.thread_sleep_duration);
	

