import network_layer
import sys
import time
import socket

ip = socket.gethostbyname(socket.gethostname())
port = 47890

if len(sys.argv) >= 2:
	port = int(sys.argv[1])

