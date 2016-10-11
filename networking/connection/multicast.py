import socket
import sys
import traceback
import struct
import threading;
from threading import Thread;
import time;
import datetime;
import json;
import buffered_message;
from connection_state import ConnectionState

# *************
# EXAMPLE USAGE
# *************
"""
import socket
import multicast

group = "224.5.5.6";
port = 28777
buffer_size = 128;

client1 = multicast.Multicast_Client(True, group, port, buffer_size);
client2 = multicast.Multicast_Client(True, group, port, buffer_size);

client1.send_message([5,6,7], True);
client1.pop_message(True);
client2.pop_message(True);

client2.send_message("Message from client2.");
client1.pop_message();
client2.pop_message();

client1.disconnect();
client2.disconnect();
"""

class Multicast_Client:
	
	def __init__(self, start_listen_thread=False, group="224.5.5.6", port=28777, buffer_size=1024):
		self.buffer_size = buffer_size;
		self.message_manager = buffered_message.Buffered_Message_Manager(self.buffer_size);
		self.timeout = 3.0;
		self.send_queue = [];
		self.thread_sleep_duration = 0.1;
		
		self.connect(group, port);
		
		self.connection_state = ConnectionState(False);
		if(start_listen_thread):
			self.start_listening();
	
	def connect(self, group="224.5.5.6", port=28777):
		try:
			# close open socket, if there are any.
			if(hasattr(self, "sock")):
				self.sock.shutdown(socket.SHUT_RDWR)
				self.sock.close();
		except:
			pass;
		self.multicast_group = group;
		self.multicast_port = port;

		self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP);
		self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1);
		self.sock.bind(('', self.multicast_port));
		mreq = struct.pack("4sl", socket.inet_aton(self.multicast_group), socket.INADDR_ANY);

		self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq);
		self.sock.settimeout(self.timeout);

	
	def send_message(self, message, json_encode=False, prepare=True):
		msg = message;
		if(json_encode):
			msg = json.dumps(msg);
		
		prepared_message_packets = [msg,];
		if prepare:
			prepared_message_packets = self.message_manager.prepare_message(msg);
		self.send_queue.append(prepared_message_packets);
	
	def send_message_loop(self):
		connection_state = self.connection_state
		while connection_state.active:
			message_count = len(self.send_queue);
			for i in range(0, message_count):
				prepared_message_packets = self.send_queue.pop(0);
				
				for packet in prepared_message_packets:
					try:
						self.sock.sendto(packet, (self.multicast_group, self.multicast_port));
					except:
						# todo: handle packet send timeout
						pass;
			time.sleep(self.thread_sleep_duration);
	
	def stop_listening(self):
		self.connection_state.active = False;
		try:
			self.sock.shutdown(socket.SHUT_RDWR)
			self.sock.close();
		except:
			pass;
	
	def start_listening(self):
		if(not self.connection_state.active):
			self.connection_state = ConnectionState(True);
			Thread(target=self.recv_message_loop).start();
			Thread(target=self.send_message_loop).start();
			return True;
		return False;
	
	def disconnect(self):
		self.stop_listening();
	
	def reconnect(self):
		self.disconnect();
		self.connect(self.multicast_group, self.multicast_port);
	
	def new_connection(self, group="224.5.5.6", port=28777):
		self.disconnect();
		self.connect(group, port);
	
	# Run this as its own thread.
	def recv_message_loop(self):
		connection_state = self.connection_state
		while connection_state.active:
			time.sleep(self.thread_sleep_duration);
			data = None;
			addr = None;
			try:
				data, addr = self.sock.recvfrom(self.buffer_size)
			except:
				continue;
			timestamp = time.time();
			self.message_manager.handle_raw_message(data, addr, timestamp);
	
	# Returns a list: [addr, timestamp, message]
	def pop_message(self, decode_json=False):
		return self.message_manager.pop_message(decode_json);

	# Returns a list of lists: [[addr, timestamp, message], ...]
	def pop_all_messages(self, decode_json=False):
		return self.message_manager.pop_all_messages(decode_json);
