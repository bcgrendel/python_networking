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
import uuid

# *************
# EXAMPLE USAGE
# *************
"""
import socket
import udp

def connect1(ip, port):
    print "%s [%s]: new connection received at client 1" % (ip, port)

def connect2(ip, port):
    print "%s [%s]: new connection received at client 2" % (ip, port)

def message1(ip, port):
    print "%s [%s]: message received at client 1" % (ip, port)

def message2(ip, port):
    print "%s [%s]: message received at client 2" % (ip, port)

def timeout1(ip, port):
    print "%s [%s]: timeout at client 1" % (ip, port)

def timeout2(ip, port):
    print "%s [%s]: timeout at client 2" % (ip, port)

def disconnect1(ip, port):
    print "%s [%s]: peer disconnection at client 1" % (ip, port)

def disconnect2(ip, port):
    print "%s [%s]: peer disconnection at client 2" % (ip, port)

def failed_connect1(ip, port):
    print "%s [%s]: connection to this peer FAILED at client 1" % (ip, port)

def failed_connect2(ip, port):
    print "%s [%s]: connection to this peer FAILED at client 2" % (ip, port)


client1_ip = socket.gethostbyname(socket.gethostname())
client1_port = 29779
client2_ip = socket.gethostbyname(socket.gethostname())
client2_port = 29778
buffer_size = 128

client1 = udp.UDP_Client(True, client1_ip, client1_port, client2_ip, client2_port, buffer_size, True, failed_connect1, message1, timeout1, connect1, disconnect1, True)
client2 = udp.UDP_Client(True, client2_ip, client2_port, client1_ip, client1_port, buffer_size, True, failed_connect2, message2, timeout2, connect2, disconnect2, True)

client1.send_message([5,6,7], True)
client2.pop_message(True)

client2.send_message("Message from client2.")
client1.pop_message()

client1.disconnect()
client2.disconnect()
"""

class UDP_Client:
	
	def __init__(
			self, 
			start_listen_thread=False,
			local_ip=socket.gethostbyname(socket.gethostname()),
			local_port=29779,
			target_ip=socket.gethostbyname(socket.gethostname()),
			target_port=29778,
			buffer_size=1024,
			keep_alive=False,
			failed_to_connect_callback=None,
			message_received_callback=None,
			keep_alive_timeout_callback=None,
			new_peer_connected_callback=None,
			peer_disconnected_callback=None,
			require_ack=False,
		):
		
		self.target_ip = target_ip
		self.target_port = target_port
		self.keep_alive = keep_alive
		self.failed_to_connect_callback = failed_to_connect_callback
		self.message_received_callback = message_received_callback
		self.keep_alive_timeout_callback = keep_alive_timeout_callback
		self.new_peer_connected_callback = new_peer_connected_callback
		self.peer_disconnected_callback = peer_disconnected_callback
		self.require_ack = require_ack

		self.connected_peers = {
			# "<ip>_<port>" : [connected_timestamp, last_message_received_timestamp, keep-alive_check_count]
		}
		
		self.buffer_size = buffer_size
		self.message_manager = buffered_message.Buffered_Message_Manager(self.buffer_size)
		self.timeout = 3.0
		self.send_queue = []
		self.thread_sleep_duration = 0.1

		self.keep_alive_timeout = 30; # 30 seconds
		#self.keep_alive_timestamp = time.time()
		self.keep_alive_interval = 3
		self.keep_alive_send_timestamp = time.time()

		self.peer_username = ""; # username belonging to remote peer
		self.error_log = []
		
		self.resend_interval = 3 # used when require_ack = True
		
		# track previous deliberate disconnections to make sure keep-alive functionality doesn't resurrect those connections.
		self.disconnected_peers = {
			#"<ip>_<port>": <disconnection timestamp>
		}
		self.disconnect_lockout_duration = self.keep_alive_interval * 2
		
		self.bind_socket(local_ip, local_port)
		
		self.connection_state = ConnectionState(False)
		if(start_listen_thread):
			self.start_listening()
		
		self.connection_attempt_timeout = 5 # seconds
		self.received_acks = []
	
	def connect_async(self, target_ip, target_port):
		Thread(target=self.connect, args=(target_ip, target_port)).start()
	
	def connect(self, target_ip, target_port):
		peer = "%s_%s" % (target_ip, target_port)
		# send keep-alive packet
		self.send_message("1", False, False, target_ip, int(target_port))
		start_time = time.time()
		time_elapsed = 0
		while peer not in self.connected_peers:
			time.sleep(0.5)
			time_elapsed = time.time() - start_time
			if time_elapsed > self.connection_attempt_timeout:
				if self.failed_to_connect_callback != None:
					self.failed_to_connect_callback(target_ip, int(target_port))
				return False
		return True
	
	def init_socket(self):
		try:
			# close open socket, if there are any.
			if(hasattr(self, "sock")):
				self.sock.shutdown(socket.SHUT_RDWR)
				self.sock.close()
		except:
			pass
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	
	def handle_peer_disconnect(self, peer):
		self.disconnected_peers[peer] = time.time()
		addr = peer.split("_")
		del self.connected_peers[peer]
		if self.peer_disconnected_callback != None:
			self.peer_disconnected_callback(addr[0], int(addr[1]))
		

	def bind_socket(self, local_ip=socket.gethostbyname(socket.gethostname()), local_port=29779):
		self.local_port = local_port
		self.local_ip = local_ip

		# (Re)initialize socket before binding.
		self.init_socket()
		self.sock.settimeout(self.timeout)

		self.sock.bind((local_ip, local_port))
	
	def prepend_unique_id(self, message):
		return "%s__%s" % (str(uuid.uuid4()), message)
	
	def send_message(self, message, json_encode=False, prepare=True, _target_ip=None, _target_port=None):
		target_ip   = _target_ip   if _target_ip   != None else self.target_ip
		target_port = _target_port if _target_port != None else self.target_port

		# !!! WARNING !!!
		# If you pass prepare as False, you MUST ensure message doesn't exceed buffer-size yourself.
		
		msg = message
		if(json_encode):
			msg = json.dumps(msg)
		
		messages = [[self.prepend_unique_id(msg), 0],]
		prepared_message_packets = [messages, target_ip, target_port]
		if prepare:
			messages = [[self.prepend_unique_id(message), 0] for message in self.message_manager.prepare_message(msg)]
			prepared_message_packets = [messages, target_ip, target_port]
		self.send_queue.append(prepared_message_packets)
	
	def keep_alive_send_check(self):
		for peer, timestamps in self.connected_peers.items():
			addr = peer.split("_")
			ip, port = [addr[0], int(addr[1])]
			now = time.time()
			diff = now - timestamps[1] #self.keep_alive_send_timestamp
			next_check_time = self.keep_alive_interval * (timestamps[2] + 1)
			if diff > next_check_time:
				self.connected_peers[peer][2] += 1
				self.connected_peers[peer][1] = now
				self.send_message("1", False, False, ip, port)

	def send_message_loop(self):
		connection_state = self.connection_state
		prepared_message_packets, target_ip, target_port, last_sent = [None, None, None, None]
		while connection_state.active:
			if self.keep_alive:
				self.keep_alive_send_check()
			message_count = len(self.send_queue)
			index = -1
			for i in range(0, message_count):
				index += 1
				if not self.require_ack:
					prepared_message_packets, target_ip, target_port = self.send_queue.pop(0)
				else:
					prepared_message_packets, target_ip, target_port = self.send_queue[index]
				
				
				packet_index = -1
				for j in range(0, len(prepared_message_packets)):
					packet_index += 1
					packet, last_sent = prepared_message_packets[packet_index]
					
					if last_sent != 0 and self.require_ack:
						sent_timestamp = time.time()
						packet_id, packet = packet.split("__", 1)
						if packet_id in self.received_acks:
							del self.send_queue[index][0][packet_index]
							packet_index -= 1
							if len(self.send_queue[index][0]) < 1:
								del self.send_queue[index]
								index -= 1
							continue
						
						now = time.time()
						time_difference = now - last_sent
						if time_difference < self.resend_interval:
							continue
					
					# update the last sent timestamp for this packet
					if self.require_ack:
						self.send_queue[index][0][j][1] = time.time()
					try:
						self.sock.sendto(packet, (target_ip, target_port))
					except:
						# todo: handle packet send timeout
						pass
			time.sleep(self.thread_sleep_duration)
	
	def keep_alive_loop(self):
		connection_state = self.connection_state
		while connection_state.active:
			self.send_message("1", False, False)
	
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
			Thread(target=self.recv_message_loop).start()
			Thread(target=self.send_message_loop).start()
			return True
		return False
	
	def disconnect_from_peer(self, peer_ip, peer_port):
		peer = "%s_%s" % (peer_ip, peer_port)
		if peer not in self.connected_peers:
			return False
		
		self.disconnected_peers[peer] = time.time()
		peer_port = int(peer_port)
		self.send_message("2", False, False, peer_ip, peer_port)
		
		del self.connected_peers[peer]
		
		return True
	
	def disconnect(self):
		for peer, timestamps in self.connected_peers.items():
			addr = peer.split("_")
			ip, port = [addr[0], int(addr[1])]
			self.send_message("2", False, False, ip, port)
		time.sleep(0.5)
		self.connected_peers.clear()
		self.stop_listening()
	
	def reconnect(self):
		self.disconnect()
		time.sleep(self.disconnect_lockout_duration + 0.5)
		self.bind_socket(self.local_ip, self.local_port)
		self.start_listening()
	
	def new_connection(self, local_ip=socket.gethostbyname(socket.gethostname()), local_port=29779):
		self.disconnect()
		self.bind_socket(local_ip, local_port)
	
	def check_keep_alive(self):
		for peer, timestamps in self.connected_peers.items():

			addr = peer.split("_")
			now = time.time()
			timestamp = timestamps[0]
			diff = now - timestamp; #self.keep_alive_timestamp
			if(diff > self.keep_alive_timeout):
				del self.connected_peers[peer]
				if self.keep_alive_timeout_callback != None:
					self.keep_alive_timeout_callback(addr[0], int(addr[1]))
				elif self.peer_disconnected_callback != None:
					self.peer_disconnected_callback(addr[0], int(addr[1]))
				#self.disconnect()
				#err_msg = "[UDP_Client]: Client connection timed out. (peer: IP: %s   Port: %s  Username: %s)" % (self.target_ip, self.target_port, self.peer_username)
				#timestamp = time.time()
				#date_string = datetime.datetime.fromtimestamp(timestamp).strftime('(%Y-%m-%d) %H:%M:%S')
				#self.error_log.append((timestamp, date_string, err_msg))

	# Run this as its own thread.
	def recv_message_loop(self):
		connection_state = self.connection_state
		while connection_state.active:
			#time.sleep(0.001)
			if self.keep_alive:
				self.check_keep_alive()
			data_raw = None
			data = None
			addr = None
			try:
				data_raw, addr = self.sock.recvfrom(self.buffer_size)
			except:
				continue
			
			packet_id = None
			if "__" in data_raw:
				packet_id, data = data_raw.split("__", 1)
			else:
				data = data_raw
			
			peer = "%s_%s" % (addr[0], addr[1])
			ip, port = [addr[0], int(addr[1])]
			
			if peer in self.disconnected_peers:
				disconnect_limit = self.disconnected_peers[peer] + self.disconnect_lockout_duration
				now = time.time()
				
				# should we ignore this message?
				if now <= disconnect_limit:
					continue
			
			# check if peer is new or not and update keep-alive info
			if peer not in self.connected_peers:
				if self.new_peer_connected_callback != None:
					self.new_peer_connected_callback(addr[0], int(addr[1]))
				
				self.connected_peers[peer] = [int(time.time()), 0, 0]
			else:
				self.connected_peers[peer][0] = int(time.time())
				self.connected_peers[peer][2] = 0 # reset the keep-alive check counter on received messages.
			
			if self.keep_alive:
				if data == "1":
					#self.keep_alive_timestamp = time.time()
					continue
				self.send_message("1", False, False, ip, port)
			
			if data == "2":
				# peer is disconnecting.
				self.handle_peer_disconnect(peer)
				continue
			
			if (len(data) > 2) and (data[:3]).lower() == "ack":
				# clear associated message from the message queue.
				ack_token, ack_id = data.split(" ", 1)
				self.received_acks.append(ack_id)
				continue
			
			timestamp = time.time()
			self.message_manager.handle_raw_message(data, addr, timestamp)
			
			# send ack for this packet.
			self.send_message("ack %s" % packet_id, False, False, ip, port)
			
			#print "UDP duration: %s" % (time.time() - timestamp)
			if self.message_received_callback != None:
				self.message_received_callback(ip, port)
	
	# Returns a list: [addr, timestamp, message]
	def pop_message(self, decode_json=False):
		return self.message_manager.pop_message(decode_json)
	
	# Returns a list of lists: [[addr, timestamp, message], ...]
	def pop_all_messages(self, decode_json=False):
		return self.message_manager.pop_all_messages(decode_json)

