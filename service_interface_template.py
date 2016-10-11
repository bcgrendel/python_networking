
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

communication_is_ready = {
	# "<service_name>_<service_id>": False/True,
}

def peer_failed_connection_callback(peer_endpoint):
	pass
	
def peer_connected_callback(peer_endpoint):
	pass

def peer_disconnected_callback(peer_endpoint):
	pass

def peer_timeout_callback(peer_endpoint):
	pass
	
def peer_message_received_callback(peer_endpoint, message):
	pass
	
def communication_is_ready_callback(peer_endpoint):
	global communication_is_ready
	pass

service_list = [
	#Service(
	#	name = "actions",
	#	id = "actions_1",
	#	function_map = {
	#		"action_one": action_one,
	#		"action_two": action_two,
	#		"peer_finished": peer_finished,
	#	}
	#),
]
peer_service_list = [
	#Peer_Service(
	#	name = "actions",
	#	id = "action_2",
	#	expected_functions = [
	#		"action_three",
	#		"action_four",
	#		"peer_finished"
	#	]
	#),
]
	
# create endpoint
local_endpoint = Local_Endpoint(
	ip = None, # None will be replaced by the localhost address.
	port = 49789,
	master_process_id = None,
	service_list = service_list,
	local_cleanup_callback = None
)
# create peer_endpoint object
peer_endpoint = Peer_Local_Endpoint(
	local_endpoint = local_endpoint, # local_endpoint object
	ip = None,
	port = 49790,
	service_list = peer_service_list,
	relationship = "peer", # If this service is a slave to this process, then we manage whether it starts or stops. Possible values are "peer", "slave", and "master". Any other value just translates to "peer".
	process_run_command = [sys.executable, "peer_script.py", "arg1", "arg2"],
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
result = peer_interface.execute_peer_service_function(
	peer_endpoint, 
	peer_service_list[0].name,
	peer_service_list[0].expected_functions[0], 
	args
)

peer_interface.execute_peer_service_function(
	peer_endpoint, 
	peer_service_list[0].name,
	"peer_finished",
	[]
)

# wait for communication to complete.
while active or peer_active:
	time.sleep(0.5)

# close the interface.
peer_interface.shutdown()

# kill the peer (if it's a slave)
peer_endpoint.stop_application()

# unlock our endpoint and exit
local_endpoint.self_terminate()