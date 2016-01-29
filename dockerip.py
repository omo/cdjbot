#!/usr/bin/env python

import subprocess, re

def get_docker_host_ip():
    p = subprocess.Popen(["ifconfig", "docker0"], stdout=subprocess.PIPE)
    out, err = p.communicate()
    return re.search('inet addr:(.\S+)', str(out)).group(1)

def get_docker_host_mongo_url(dbname):
    return "mongodb://{}:27017/{}".format(get_docker_host_ip(), dbname)

if __name__ == "__main__":
    import optparse
    parser = optparse.OptionParser()
    parser.add_option("-u", "--url", dest="url", default=False,
                      help="Print in a URL form", action="store_true")
    parser.add_option("-d", "--database", dest="db", default="test",
                      help="Database name in the URL", metavar="DB")
    (options, args) = parser.parse_args()

    if options.url:
        print(get_docker_host_mongo_url(options.db))
    else:
        print(get_docker_host_ip())
