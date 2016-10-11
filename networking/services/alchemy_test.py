
import sqlalchemy
import time;
from datetime import date, timedelta
import datetime

from sqlalchemy import func
import services_alchemy
from services_alchemy import Endpoint

session = services_alchemy.Session()

active_time = datetime.datetime.utcnow() - timedelta(seconds=15) # <peer_timeout> seconds into the past.

resultset = []
resultset = session.query(Endpoint).\
		filter(Endpoint.last_active >= active_time).\
		all()

print "Results:\n--------\n"
for endpoint in resultset:
	print "[%s] %s" % [endpoint.process_id, endpoint.application_name]

session.close()

