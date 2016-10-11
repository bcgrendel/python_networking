import argparse

parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument(
			"-H",
			"--ip",
			metavar="ip",
			dest="ip",
			type=str,
                  help="IP of the endpoint. Will be localhost if omitted."
)
parser.add_argument(
			"-p",
			"--port",
			metavar="port",
			dest="port",
			type=int,
			required=True,
                  help="Port number of the endpoint. Required."
)
parser.add_argument(
			"-m",
			"--master_pid",
			metavar="master_pid",
			dest="master_pid",
			type=int,
                  help="Process ID of master process responsible for starting/managing this process."
)
args = None
# use this to get the parser and add more arguments before parsing.
def get_parser():
	global parser
	return parser

# parses the args if it hasn't already and returns it. That means if you add arguments after parsing the first time,
# you'll need to parse again manually with the parser object. This function will just return the initial results.
def parse_args():
	global parser
	global args
	if args == None:
		args = parser.parse_args()
	return args
	
def get_endpoint():
	global args
	if args == None:
		parse_args()
	return [
		args.ip,
		args.port,
		args.master_pid,
	]