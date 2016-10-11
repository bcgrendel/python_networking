import os
import sys
import traceback
import time
import datetime;
import random
import socket
import math
import json
# NOTE: This message manager requires that your receiving socket's buffer size is as large or larger than the sending socket's buffer size.

class Buffered_Message_Manager:
	
	def __init__(self, buffer_size=1024):
		self.buffer_size = buffer_size;

		self.received_messages = [];
		self.partial_map = {};
		self.message_info_map = {};

		# Garbage check interval in seconds
		self.garbage_check_interval = 300; # 5 minutes

		# prepare for generating unique id's
		self.proc_id = os.getpid();
		self.hostname = "";
		try:
			self.hostname = socket.gethostbyname(socket.gethostname());
		except:
			pass;
		if self.hostname == "":
			self.hostname = int(1000000L + (random.random() * 1000000L));
		
		self.recent_message_id_buffer_size = 100
		self.recent_message_ids = []
	
	def pop_message(self, decode_json=False):
		if(len(self.received_messages) < 1):
			return None;
		result = self.received_messages.pop(0);
		if(decode_json):
			result[2] = json.loads(result[2]);
		return result;

	# WARNING: this method might not be thread safe or reliable during concurrent calls.
	def pop_all_messages(self, decode_json=False):
		result = [];
		total_messages = len(self.received_messages);
		try:
			for i in range(0, total_messages):
				message = self.received_messages.pop(0);
				if(decode_json):
					message[2] = json.loads(message[2]);
				result.append(message);
		except:
			pass;

		return result;


	def generate_unique_id(self):
		return "%s-%s-%s-%s" % (self.proc_id, self.hostname, int(time.time()), int(1+random.random() * 10000));

	def handle_raw_message(self, message, addr="127.0.0.1", timestamp=time.time()):
		# Strip leading character
		lead = message[0:1];
		# Get the message body.
		body = message[1:];

		# partial message
		if(lead == "-"):
			self.handle_partial_packet(body, addr, timestamp);
		elif(lead == "x"):
			self.handle_info_packet(body, addr, timestamp);
		elif(lead == "_"):
			self.handle_solo_packet(body, addr, timestamp);
		else:
			# message is not prepared, append as is.
			self.received_messages.append([addr, timestamp, message]);

		# ignore anything else that comes through as it doesn't match the expected format.

	def reconstruct_message(self, message_id, addr):
		# Reconstruct message.
		total_pieces = self.message_info_map[message_id][2];
		timestamp = self.message_info_map[message_id][1];
		message = [];
		for i in range(0, total_pieces):
			message.append(self.partial_map[message_id][addr][i][1]);

		# Add message to received messages list.
		self.received_messages.append([addr, timestamp, "".join(message)]);

		self.recent_message_ids.append(message_id)
		if len(self.recent_message_ids) > self.recent_message_id_buffer_size:
			self.recent_message_ids.pop(0)
		# Delete partial message data.
		del self.partial_map[message_id];
		del self.message_info_map[message_id];

	def check_partial_map(self, message_id, addr):
		# If message info packet hasn't been recieved yet, we can't validate the pieces. return.
		if message_id not in self.message_info_map:
			return;
		# Address must match info packet.
		if self.message_info_map[message_id][0] != addr:
			return;
		# If no pieces recieved yet, return.
		if message_id not in self.partial_map:
			return;
		# Address must be in the partial_map under this message_id.
		if addr not in self.partial_map[message_id]:
			return;

		# If still missing some pieces, return.
		total_pieces = self.message_info_map[message_id][2];
		if(total_pieces > len(self.partial_map[message_id][addr])):
			return;

		# All pieces have been collected. Reconstruct the message.
		self.reconstruct_message(message_id, addr);

	def handle_info_packet(self, message, addr, timestamp):
		# Strip out message_id and total number of pieces
		parts = message.split("_");
		if(len(parts) != 2):
			return; # wrong format.
		message_id = parts[0];
		# is this an old message? Ignore it.
		if message_id in self.recent_message_ids:
			return
		total_pieces = int(parts[1]);

		# If this message_id is already in use, ignore this packet.
		if(message_id in self.message_info_map):
			return;

		# Store info
		self.message_info_map[message_id] = (addr, timestamp, total_pieces);

		# Check message pieces for completion
		self.check_partial_map(message_id, addr);

	def handle_solo_packet(self, message, addr, timestamp):
		parts = message.split("_",2);
		if(len(parts) != 3):
			return;
		message_id = parts[0]
		# is this an old message? Ignore it.
		if message_id in self.recent_message_ids:
			return
		
		self.recent_message_ids.append(message_id)
		if len(self.recent_message_ids) > self.recent_message_id_buffer_size:
			self.recent_message_ids.pop(0)
		
		self.received_messages.append([addr, timestamp, parts[2]]);

	def handle_partial_packet(self, message, addr, timestamp):
		parts = message.split("_", 2) 
		if(len(parts) != 3):
			return;
		message_id = parts[0];
		# is this an old message? Ignore it.
		if message_id in self.recent_message_ids:
			return
		piece_number = int(parts[1]);
		message_piece = (
			timestamp,
			parts[2],
		);

		if message_id not in self.partial_map:
			self.partial_map[message_id] = {};
			self.partial_map[message_id][addr] = {};

		if addr not in self.partial_map[message_id]:
			self.partial_map[message_id][addr] = {};

		self.partial_map[message_id][addr][piece_number] = message_piece;
		
		self.check_partial_map(message_id, addr);

	def prepare_message(self, message):
		result = [];
		unique_id = self.generate_unique_id();
		total_pieces = 1;
		
		message_length = len(message);

		# approximate total pieces
		remaining_buffer_size = self.buffer_size - (len(unique_id) + 3); # account for the lead char and underscore separators (hence +3).
		approximate_pieces = int( math.ceil(message_length / float(remaining_buffer_size)) )
		
		# reapproximate, this time with number of digits in first approximation + 4 (to be extra safe, though '4' is really a magic number. Sorry.) stripped from the remaining_buffer_size
		remaining_buffer_size -= (4 + len("%s" % approximate_pieces));

		total_pieces = int( math.ceil(message_length / float(remaining_buffer_size)) );
		if(total_pieces < 1):
			total_pieces = 1;
		
		if(total_pieces == 1):
			message_piece = "_%s_%s_%s" % (unique_id, 0, message)
			result.append(message_piece);
		else:
			# Generate info packet
			info_packet = "x%s_%s" % (unique_id, total_pieces)
			result.append(info_packet);

			# Generate message piece packets.
			offset = 0;
			endpoint = remaining_buffer_size;
			finalpoint = message_length;
			for i in range(0, total_pieces):
				message_piece = "-%s_%s_%s" % (unique_id, i, message[offset : endpoint]);
				result.append(message_piece);

				endpoint += remaining_buffer_size
				offset += remaining_buffer_size
				if(endpoint > finalpoint):
					endpoint = finalpoint
				if(offset == finalpoint):
					break;

		return result;

