import time
import json

import sys
import os
import psycopg2

orig_path = os.getcwd();
os.chdir("../");
sys.path.insert(0, os.getcwd());
os.chdir(orig_path);

from alchemy import connection_string

from datetime import date, timedelta
import datetime

import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, \
	Integer, \
	String, \
	BigInteger, \
	TIMESTAMP, \
	Boolean, \
	Sequence, \
	ForeignKey

from sqlalchemy.orm import sessionmaker

from contextlib import contextmanager

@contextmanager
def session_scope():
	"""Provide a transactional scope around a series of operations."""
	session = Session()
	try:
		yield session
		session.commit()
	except:
		session.rollback()
		raise
	finally:
		session.close()

db_config_file = "database_conf.json";

debug=False;

if __name__ == "__main__":
	if len(sys.argv) > 1:
		debug = True;
		if(sys.argv[1] == "conn"):
			print connection_string.generate_connection_string(db_config_file);
			exit();

Base = declarative_base()
#s = Sequence("stun_user_id_seq", start=1, increment=1)
class Stun_User(Base):
	__tablename__ = 'stun_user'
	
	id = Column(BigInteger, primary_key=True)
	username = Column(String(256))
	password = Column(String(256))
	salt_key = Column(String(256))
	dynamic_key = Column(String(256)) 
	auth_token = Column(String(256))
	last_active = Column(TIMESTAMP, default=datetime.datetime.utcnow())
	create_date = Column(TIMESTAMP, default=datetime.datetime.utcnow())
	auth_ip_address = Column(String(56));
	auth_port = Column(Integer);
	ip_address = Column(String(56))
	port = Column(Integer)
	profile_map = Column(String(4096)) # json string with miscellaneous data
	logged_in = Column(Boolean, nullable=False, default=True)
	available_ports = Column(String(1024))
	used_ports = Column(String(1024))
	
	def __repr__(self):
		return "<Stun_User(username='%s', ip=%s, port=%s, create_date=%s last_active=%s)>" % (self.username, self.ip_address, self.port, self.create_date, self.last_active)

"""
class Stun_User_Endpoint(Base):
	__tablename__ = 'stun_user_endpoint'
	
	id = Column(BigInteger, primary_key=True)
	user_id = Column(BigInteger, ForeignKey("stun_user.id"), nullable=False)
	ip_address = Column(String(56))
	port = Column(Integer)
	buffer_size = Column(Integer)
	endpoint_label = Column(String(128))
	
	def __repr__(self):
		return "<Stun_User_Endpoint(ip=%s, port=%s, buffer_size=%s)>" % (self.ip_address, self.port, self.buffer_size)
"""
#Stun_User.__table__

connection_string = connection_string.generate_connection_string(db_config_file);
engine = sqlalchemy.create_engine(connection_string, echo=debug);

Session = sessionmaker(bind=engine)

if __name__ == "__main__":
	Base.metadata.create_all(engine);
	
