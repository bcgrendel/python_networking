
-- user table

create table stun_user(
	id bigserial,
	username character varying(256),
	password character varying(50),
	last_active timestamp without time zone default current_timestamp()
);


