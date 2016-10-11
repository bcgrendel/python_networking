
import time

from endpoint_lock import attempt_endpoint_registration,\
				  unlock_endpoint

import argument_parser

ip, port, master_pid = argument_parser.get_endpoint()

service_list = [
	{
		"service_name": "test_app",
		"service_id": "test_app_1",
	},
	{
		"service_name": "test_app",
		"service_id": "test_app_2",
	},
	{
		"service_name": "main_app",
		"service_id": "main_app_1",
	},
]

if not attempt_endpoint_registration(ip, port, service_list):
	print "Failed to acquire lock! An active lock already exists on this endpoint."
	exit()

# sleeping 20 seconds
for i in range(1, 5):
	time.sleep(5.0)
	print i*5
	
print "unlocking..."
unlock_endpoint(ip, port)
print "complete"