#!/bin/bash
virtualenv -p python3 env
. ./env/bin/activate
pip3 install -r requirements.txt
