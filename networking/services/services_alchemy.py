import time
import json

import sys
import os

orig_path = os.getcwd();
os.chdir("../");
sys.path.insert(0, os.getcwd());
os.chdir(orig_path);

try:
	from alchemy import connection_string
except:
	from ..alchemy import connection_string

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

db_config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "database_conf.json")

debug=False;

if __name__ == "__main__":
	if len(sys.argv) > 1:
		debug = True;
		if(sys.argv[1] == "conn"):
			print connection_string.generate_connection_string(db_config_file);
			exit();

Base = declarative_base()
class Endpoint(Base):
	__tablename__ = 'endpoint'
	__table_args__ = {'sqlite_autoincrement': True}
	
	id = Column(Integer, primary_key=True, autoincrement=True)
	ip = Column(String(256))
	port = Column(Integer)
	process_id = Column(Integer)
	service_list = Column(String(2048))
	last_active = Column(TIMESTAMP, default=datetime.datetime.utcnow())
	start_time = Column(TIMESTAMP, default=datetime.datetime.utcnow())
	
	def __repr__(self):
		return "<Endpoint(\n\tid='%s',\n\tip=%s,\n\tport=%s,\n\tprocess_id=%s,\n\tapplication_name=%s,\n\tapplication_id=%s,\n\tstart_time=%s,\n\tlast_active=%s)>" % (self.id, self.ip, self.port, self.process_id, self.application_name, self.application_id, self.start_time, self.last_active)

connection_string = connection_string.generate_connection_string(db_config_file)
engine = sqlalchemy.create_engine(connection_string, echo=debug)

Session = sessionmaker(bind=engine)

if __name__ == "__main__":
	Base.metadata.create_all(engine);
	
