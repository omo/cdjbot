#!/usr/bin/env python

import subprocess, re

p = subprocess.Popen(["ifconfig", "docker0"], stdout=subprocess.PIPE)
out, err = p.communicate()
addr = re.search('inet addr:(.\S+)', str(out)).group(1)
print(addr)
