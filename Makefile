
ENVS=CDJBOT_TELEGRAM_TOKEN="${CDJBOT_TELEGRAM_TOKEN}"
HOST=ubuntu@54.152.53.180
SSH_KEYFILE=~/.ssh/omokey.pem

dbuild:
	docker build --rm -t morrita/cdjbot .
dbash: dbuild
	docker run --rm -t -i cdjbot /bin/bash
drun: dbuild
	docker run --rm -t -i -e ${ENVS} cdjbot
dpush: dbuild
	docker push morrita/cdjbot

push:
	scp -i ${SSH_KEYFILE} conf/cdjbot.conf ${HOST}:/tmp/cdjbot.conf
	ssh -i ${SSH_KEYFILE} ${HOST} docker pull morrita/cdjbot
	ssh -i ${SSH_KEYFILE} ${HOST} sudo cp /tmp/cdjbot.conf /etc/init/
	ssh -i ${SSH_KEYFILE} ${HOST} sudo service cdjbot restart
.PHONY: dbuild push
