#!/usr/bin/env python
from migrate.versioning.shell import main

if __name__ == '__main__':
    main(url='postgresql+psycopg2://stun_server:sadf987#40274$%@localhost:5432/stun', debug='False', repository='stun')
