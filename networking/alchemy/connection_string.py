import json
import os

#"%s://%s:%s@%s:%s/%s" % (db_config["dbms"], db_config["username"], db_config["password"], db_config["hostname"], db_config["port"], db_config["database"])

def generate_connection_string(filename="database_conf.json"):
	contents = None
	with open(filename,"r+") as f:
		contents = f.read()

	db_config = json.loads(contents)

	if db_config["database"] == "memory":
		return "%s:///:memory:" % db_config["dbms"];
	
	valid_username = ("username" in db_config) and (db_config["username"].strip(' \t\n\r') != "");
	valid_password = ("password" in db_config) and (db_config["password"].strip(' \t\n\r') != "");
	valid_hostname = ("hostname" in db_config) and (db_config["hostname"].strip(' \t\n\r') != "");
	valid_port = ("port" in db_config) and (db_config["port"].strip(' \t\n\r') != "");
	valid_database = ("database" in db_config) and (db_config["database"].strip(' \t\n\r') != "");
	
	if db_config["database"][0] == ".":
		directory = os.path.dirname(filename)
		db_config["database"] = os.path.join(directory, db_config["database"])

	username = db_config["username"] if valid_username else ""
	password = ":%s" % db_config["password"] if valid_password else ""
	hostname = "@%s" % db_config["hostname"] if valid_hostname else ""
	port = ":%s" % db_config["port"] if valid_port else ""
	database = "/%s" % db_config["database"] if valid_database else ""
	
	
	return "%s://%s%s%s%s%s" % (db_config["dbms"], username, password, hostname, port, database)
