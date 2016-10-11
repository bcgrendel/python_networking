
import time
import subprocess
import sys
import psutil

from networking.services.peers import Service,\
			Peer_Service,\
			Local_Endpoint,\
			Peer_Endpoint,\
			Peer_Local_Endpoint
			
from networking.services.interface import Peer_Service_Interface

DETACHED_PROCESS = 0x00000008

results = []
active = True
peer_active = True

# Define our functions.
def action_one(arg1, arg2):
	return "%s_%s" % (arg1, arg2,)
	
def action_two(arg1, arg2):
	return "%s___%s" % (arg1, arg2,)
	
def action_three(arg1, arg2):
	return "%s_***_%s" % (arg1, arg2,)
	
def action_four(arg1, arg2):
	return "%s_###_%s" % (arg1, arg2,)

def peer_finished():
	global peer_active
	peer_active = False
	
def peer_failed_connection_callback(peer_endpoint):
	print "[%s:%s] failed to connect." % (peer_endpoint.ip, peer_endpoint.port)
	
def peer_connected_callback(peer_endpoint):
	print "[%s:%s] connected." % (peer_endpoint.ip, peer_endpoint.port)

def peer_disconnected_callback(peer_endpoint):
	print "[%s:%s] disconnected." % (peer_endpoint.ip, peer_endpoint.port)

def peer_timeout_callback(peer_endpoint):
	print "[%s:%s] timed out." % (peer_endpoint.ip, peer_endpoint.port)
	
def peer_message_received_callback(peer_endpoint, message):
	print "[%s:%s] sent us a message. Message is:\n\t%s" % (peer_endpoint.ip, peer_endpoint.port, message)

# Define our services
services_one = [
	Service(
		name = "actions",
		id = "actions_1",
		function_map = {
			"action_one": action_one,
			"action_two": action_two,
			"peer_finished": peer_finished,
		}
	),
]
services_two = [
	Service(
		name = "actions",
		id = "actions_2",
		function_map = {
			"action_three": action_three,
			"action_four": action_four,
			"peer_finished": peer_finished,
		}
	),
]

peer_services_one = [
	Peer_Service(
		name = "actions",
		id = "action_2",
		expected_functions = [
			"action_three",
			"action_four",
			"peer_finished"
		]
	),
]

peer_services_two = [
	Peer_Service(
		name = "actions",
		id = "action_1",
		expected_functions = [
			"action_one",
			"action_two",
			"peer_finished"
		]
	),
]

port_one = 44321
port_two = 44322

communication_is_ready = {
	# "<service_name>_<service_id>": False/True,
}

def communication_is_ready_callback(peer_endpoint):
	global communication_is_ready
	for service in peer_endpoint.service_list:
		service_key = "%s_%s" % (service.name, service.id)
		communication_is_ready[service_key] = True
	
	print "[%s:%s] is identified." % (peer_endpoint.ip, peer_endpoint.port)

def process_one(args):
	global services_one
	global peer_services_one
	global results
	global active
	global port_one
	global port_two
	global communication_is_ready
	
	# create endpoint
	local_endpoint = Local_Endpoint(
		ip = None, # None will be replaced by the localhost address.
		port = port_one,
		master_process_id = None,
		service_list = services_one,
		local_cleanup_callback = None
	)
	# create peer_endpoint object
	peer_endpoint = Peer_Local_Endpoint(
		local_endpoint = local_endpoint, # local_endpoint object
		ip = None,
		port = port_two,
		service_list = peer_services_one,
		relationship = "peer", # If this service is a slave to this process, then we manage whether it starts or stops. Possible values are "peer", "slave", and "master". Any other value just translates to "peer".
		process_run_command = "",
		process_stop_command = None, # if None, normal task kill, otherwise, the command in the string will be run.
							# If '<pid>' is in the string, it will be replaced with the actual process id.
		failed_to_connect_callback = peer_failed_connection_callback,
		message_received_callback = peer_message_received_callback,
		keep_alive_timeout_callback = peer_timeout_callback,
		new_peer_connected_callback = peer_connected_callback,
		peer_disconnected_callback = peer_disconnected_callback,
		local_cleanup_callback = None,
		peer_interface_ready_callback = communication_is_ready_callback
	)
	
	# initialize interface
	peer_interface = Peer_Service_Interface(
		local_endpoint = local_endpoint,
		peer_endpoint_list = [peer_endpoint, ],
		failed_to_connect_callback = None,
		message_received_callback = None,
		keep_alive_timeout_callback = None,
		new_peer_connected_callback = None,
		peer_interface_ready_callback = None, # fires when a peer is fully identified and ready to execute service functions.
		peer_disconnected_callback = None
	)
	services_ready = False
	while not services_ready:
		services_ready = True
		for service in peer_endpoint.service_list:
			service_key = "%s_%s" % (service.name, service.id)
			if service_key not in communication_is_ready or not communication_is_ready[service_key]:
				services_ready = False
				break
	
	# run communications.
	results = [
		peer_interface.execute_peer_service_function(
			peer_endpoint, 
			peer_services_one[0].name,
			peer_services_one[0].expected_functions[0], 
			args
		),
		peer_interface.execute_peer_service_function(
			peer_endpoint, 
			peer_services_one[0].name,
			peer_services_one[0].expected_functions[1], 
			args
		),
	]
	
	peer_interface.execute_peer_service_function(
		peer_endpoint, 
		peer_services_one[0].name,
		"peer_finished",
		[]
	)
	
	print str(results)
	active = False
	
	# wait for communication to complete.
	while active or peer_active:
		time.sleep(0.5)
	
	# write the results to a log file.
	with open("./log_process_one.txt", "w+") as writer:
		writer.write(str.join("\n", results))
		writer.flush()
	
	# close the interface.
	peer_interface.shutdown()
	local_endpoint.self_terminate()
	
def process_two(args):
	global services_two
	global peer_services_two
	global results
	global active
	global port_one
	global port_two
	global communication_is_ready
	
	# create endpoint
	local_endpoint = Local_Endpoint(
		ip = None, # None will be replaced by the localhost address.
		port = port_two,
		master_process_id = None,
		service_list = services_two,
		local_cleanup_callback = None
	)
	# create peer_endpoint object
	peer_endpoint = Peer_Local_Endpoint(
		local_endpoint = local_endpoint, # local_endpoint object
		ip = None,
		port = port_one,
		service_list = peer_services_two,
		relationship = "peer", # If this service is a slave to this process, then we manage whether it starts or stops. Possible values are "peer", "slave", and "master". Any other value just translates to "peer".
		process_run_command = "",
		process_stop_command = None, # if None, normal task kill, otherwise, the command in the string will be run.
							# If '<pid>' is in the string, it will be replaced with the actual process id.
		failed_to_connect_callback = peer_failed_connection_callback,
		message_received_callback = peer_message_received_callback,
		keep_alive_timeout_callback = peer_timeout_callback,
		new_peer_connected_callback = peer_connected_callback,
		peer_disconnected_callback = peer_disconnected_callback,
		local_cleanup_callback = None,
		peer_interface_ready_callback = communication_is_ready_callback
	)
	
	# initialize interface
	peer_interface = Peer_Service_Interface(
		local_endpoint = local_endpoint,
		peer_endpoint_list = [peer_endpoint, ],
		failed_to_connect_callback = None,
		message_received_callback = None,
		keep_alive_timeout_callback = None,
		new_peer_connected_callback = None,
		peer_interface_ready_callback = None, # fires when a peer is fully identified and ready to execute service functions.
		peer_disconnected_callback = None
	)
	services_ready = False
	while not services_ready:
		services_ready = True
		for service in peer_endpoint.service_list:
			service_key = "%s_%s" % (service.name, service.id)
			if service_key not in communication_is_ready or not communication_is_ready[service_key]:
				services_ready = False
				break
	
	# run communications.
	results = [
		peer_interface.execute_peer_service_function(
			peer_endpoint, 
			peer_services_two[0].name,
			peer_services_two[0].expected_functions[0], 
			args
		),
		peer_interface.execute_peer_service_function(
			peer_endpoint, 
			peer_services_two[0].name,
			peer_services_two[0].expected_functions[1], 
			args
		),
	]
	
	peer_interface.execute_peer_service_function(
		peer_endpoint, 
		peer_services_two[0].name,
		"peer_finished",
		[]
	)
	
	print str(results)
	active = False
	
	# wait for communication to complete.
	while active or peer_active:
		time.sleep(0.5)
	
	# write the results to a log file.
	with open("./log_process_two.txt", "w+") as writer:
		writer.write(str.join("\n", results))
		writer.flush()
	
	# close the interface.
	peer_interface.shutdown()
	local_endpoint.self_terminate()

def process_three(args):
	global services_one
	global peer_services_one
	global results
	global active
	global port_one
	global port_two
	global communication_is_ready
	
	# create endpoint
	local_endpoint = Local_Endpoint(
		ip = None, # None will be replaced by the localhost address.
		port = port_one,
		master_process_id = None,
		service_list = services_one,
		local_cleanup_callback = None
	)
	# create peer_endpoint object
	peer_endpoint = Peer_Local_Endpoint(
		local_endpoint = local_endpoint, # local_endpoint object
		ip = None,
		port = port_two,
		service_list = peer_services_one,
		relationship = "slave", # If this service is a slave to this process, then we manage whether it starts or stops. Possible values are "peer", "slave", and "master". Any other value just translates to "peer".
		process_run_command = [sys.executable, sys.argv[0], "p4"],
		process_stop_command = None, # if None, normal task kill, otherwise, the command in the string will be run.
							# If '<pid>' is in the string, it will be replaced with the actual process id.
		failed_to_connect_callback = peer_failed_connection_callback,
		message_received_callback = peer_message_received_callback,
		keep_alive_timeout_callback = peer_timeout_callback,
		new_peer_connected_callback = peer_connected_callback,
		peer_disconnected_callback = peer_disconnected_callback,
		local_cleanup_callback = None,
		peer_interface_ready_callback = communication_is_ready_callback
	)
	
	# initialize interface
	peer_interface = Peer_Service_Interface(
		local_endpoint = local_endpoint,
		peer_endpoint_list = [peer_endpoint, ],
		failed_to_connect_callback = None,
		message_received_callback = None,
		keep_alive_timeout_callback = None,
		new_peer_connected_callback = None,
		peer_interface_ready_callback = None, # fires when a peer is fully identified and ready to execute service functions.
		peer_disconnected_callback = None
	)
	services_ready = False
	while not services_ready:
		services_ready = True
		for service in peer_endpoint.service_list:
			service_key = "%s_%s" % (service.name, service.id)
			if service_key not in communication_is_ready or not communication_is_ready[service_key]:
				services_ready = False
				break
	
	# run communications.
	results = [
		peer_interface.execute_peer_service_function(
			peer_endpoint, 
			peer_services_one[0].name,
			peer_services_one[0].expected_functions[0], 
			args
		),
		peer_interface.execute_peer_service_function(
			peer_endpoint, 
			peer_services_one[0].name,
			peer_services_one[0].expected_functions[1], 
			args
		),
	]
	
	peer_interface.execute_peer_service_function(
		peer_endpoint, 
		peer_services_one[0].name,
		"peer_finished",
		[]
	)
	
	print str(results)
	active = False
	
	# wait for communication to complete.
	while active or peer_active:
		time.sleep(0.5)
	
	# write the results to a log file.
	with open("./log_process_three.txt", "w+") as writer:
		writer.write(str.join("\n", results))
		writer.flush()
	
	# close the interface.
	peer_interface.shutdown()
	local_endpoint.self_terminate()
	
def process_four(args):
	global services_two
	global peer_services_two
	global results
	global active
	global port_one
	global port_two
	global communication_is_ready
	
	# create endpoint
	local_endpoint = Local_Endpoint(
		ip = None, # None will be replaced by the localhost address.
		port = port_two,
		master_process_id = None,
		service_list = services_two,
		local_cleanup_callback = None
	)
	# create peer_endpoint object
	peer_endpoint = Peer_Local_Endpoint(
		local_endpoint = local_endpoint, # local_endpoint object
		ip = None,
		port = port_one,
		service_list = peer_services_two,
		relationship = "master", # If this service is a slave to this process, then we manage whether it starts or stops. Possible values are "peer", "slave", and "master". Any other value just translates to "peer".
		process_run_command = None,
		process_stop_command = None, # if None, normal task kill, otherwise, the command in the string will be run.
							# If '<pid>' is in the string, it will be replaced with the actual process id.
		failed_to_connect_callback = peer_failed_connection_callback,
		message_received_callback = peer_message_received_callback,
		keep_alive_timeout_callback = peer_timeout_callback,
		new_peer_connected_callback = peer_connected_callback,
		peer_disconnected_callback = peer_disconnected_callback,
		local_cleanup_callback = None,
		peer_interface_ready_callback = communication_is_ready_callback
	)
	
	# initialize interface
	peer_interface = Peer_Service_Interface(
		local_endpoint = local_endpoint,
		peer_endpoint_list = [peer_endpoint, ],
		failed_to_connect_callback = None,
		message_received_callback = None,
		keep_alive_timeout_callback = None,
		new_peer_connected_callback = None,
		peer_interface_ready_callback = None, # fires when a peer is fully identified and ready to execute service functions.
		peer_disconnected_callback = None
	)
	services_ready = False
	while not services_ready:
		services_ready = True
		for service in peer_endpoint.service_list:
			service_key = "%s_%s" % (service.name, service.id)
			if service_key not in communication_is_ready or not communication_is_ready[service_key]:
				services_ready = False
				break
	
	# run communications.
	results = [
		peer_interface.execute_peer_service_function(
			peer_endpoint, 
			peer_services_two[0].name,
			peer_services_two[0].expected_functions[0], 
			args
		),
		peer_interface.execute_peer_service_function(
			peer_endpoint, 
			peer_services_two[0].name,
			peer_services_two[0].expected_functions[1], 
			args
		),
	]
	
	peer_interface.execute_peer_service_function(
		peer_endpoint, 
		peer_services_two[0].name,
		"peer_finished",
		[]
	)
	
	print str(results)
	active = False
	
	# wait for communication to complete.
	while active or peer_active:
		time.sleep(0.5)
	
	# write the results to a log file.
	with open("./log_process_four.txt", "w+") as writer:
		writer.write(str.join("\n", results))
		writer.flush()
	
	# close the interface.
	peer_interface.shutdown()
	local_endpoint.self_terminate()
	
def process_is_running(process_id = None):
		if process_id == None:
			process_id = self.process_id
		
		if process_id != None:
			for process in psutil.process_iter():
				if process.pid == process_id:
					return True
		return False

if __name__ == '__main__':
	if len(sys.argv) < 2:
		# run the two processes and get them communicating with each other.
		command = [sys.executable, sys.argv[0], "p1"]
		process_id_one = subprocess.Popen(command, creationflags=DETACHED_PROCESS, close_fds=True).pid
		command = [sys.executable, sys.argv[0], "p2"]
		process_id_two = subprocess.Popen(command, creationflags=DETACHED_PROCESS, close_fds=True).pid
		command = [sys.executable, sys.argv[0], "p3"]
		process_id_three = subprocess.Popen(command, creationflags=DETACHED_PROCESS, close_fds=True).pid
		
		print "Processes one [%s], two [%s], and three [%s] are now running." % (process_id_one, process_id_two, process_id_three)
		while process_is_running(process_id_one) and process_is_running(process_id_two):
			time.sleep(0.5)
			
		print "[END] Processes one [%s], two [%s], and three [%s] are now finished." % (process_id_one, process_id_two, process_id_three)
		
		expected_results = {
			"./log_process_one.txt": "test1_***_test2\ntest1_###_test2",
			"./log_process_two.txt": "test3_test4\ntest3___test4",
			"./log_process_three.txt": "test5_***_test6\ntest5_###_test6",
			"./log_process_four.txt": "test7_test8\ntest7___test8",
		}
		for filename, expected_result in expected_results.items():
			contents = None
			with open(filename, "r+") as reader:
				contents = reader.read()
			if contents == expected_result:
				print "Results successfully passed for log file: %s" % filename
			else:
				print "Results didn't match for log file: %s" % filename
				print "\t Comparison:\n\t\t%s\n-------\n\t\t" % (
					str.join("\n\t\t", contents.split("\n")),
					str.join("\n\t\t", expected_result.split("\n"))
				)
	else:
		if sys.argv[1].lower() == "p1":
			args = ["test1", "test2"]
			process_one(args)
		elif sys.argv[1].lower() == "p2":
			args = ["test3", "test4"]
			process_two(args)
		elif sys.argv[1].lower() == "p3":
			args = ["test5", "test6"]
			process_three(args)
		elif sys.argv[1].lower() == "p4":
			args = ["test7", "test8"]
			process_four(args)