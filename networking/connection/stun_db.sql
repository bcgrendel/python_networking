
-- User table.
create table stun_user(
	id bigserial,
	username character varying(256),
	password character varying(256),
	last_active timestamp without time zone default statement_timestamp(),
	create_date timestamp without time zone default statement_timestamp(),
	ip_address character varying(56),
	port integer,
	buffer_size integer
);