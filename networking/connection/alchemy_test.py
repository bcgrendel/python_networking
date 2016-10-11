
import sqlalchemy
import time;
from datetime import date, timedelta
import datetime

from sqlalchemy import func
import stun_alchemy
from stun_alchemy import Stun_User

session = stun_alchemy.Session();

active_time = datetime.datetime.utcnow() - timedelta(seconds=15); # <peer_timeout> seconds into the past.

resultset = [];
resultset = session.query(Stun_User).\
		filter(Stun_User.last_active >= active_time).\
		filter(Stun_User.logged_in == True).\
		order_by(Stun_User.username).\
		all();
for user in resultset:
	results.append(user.username, user.profile_map);

session.close();

session = stun_alchemy.Session();
