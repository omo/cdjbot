
HOST=ubuntu@54.152.53.180
SSH_KEYFILE=~/.ssh/omokey.pem
MONGO_NAME=cdjbot-mongo

# https://github.com/docker-library/mongo/blob/358d9eb62895be2c9fd4290595573c93b79d47d4/3.2/Dockerfile
# 27017 is the default mongo port
MONGO_PORT=27017
DOCKER_HOST_ADDR=${shell python dockerip.py}
DOCKER_IMAGE_NAME=morrita/cdjbot
DOCKER_ENVS=-e CDJBOT_TELEGRAM_TOKEN="${CDJBOT_TELEGRAM_TOKEN}" -e CDJBOT_MONGO_URL="${CDJBOT_MONGO_URL}"

dclean-images:
	-docker rmi ${shell docker images | grep --color=never "^<none>" | awk '{print $$3}'}
dbuild: dclean-images
	docker build --rm -t ${DOCKER_IMAGE_NAME} .
dbash: dbuild
	docker run --rm -t -i ${DOCKER_IMAGE_NAME} /bin/bash
drun: dbuild
	docker run --rm -t -i ${DOCKER_ENVS} ${DOCKER_IMAGE_NAME}
dpush: dbuild
	docker push morrita/cdjbot

mongostart:
	docker run -p ${MONGO_PORT}:${MONGO_PORT} -d --name ${MONGO_NAME} mongo
mongostop:
	docker stop ${MONGO_NAME}
	docker rm ${MONGO_NAME}
mongocli:
	docker run -it --rm mongo sh -c 'exec mongo --shell --host ${DOCKER_HOST_ADDR}'

# XXX: Not sure this really work. Let's try on next push.
pushclean:
	ssh -i ${SSH_KEYFILE} ${HOST} 'docker images | grep --color=never "^<none>" | awk "{print \$$3}"'
push:
	scp -i ${SSH_KEYFILE} conf/cdjbot.conf ${HOST}:/tmp/cdjbot.conf
	ssh -i ${SSH_KEYFILE} ${HOST} docker pull ${DOCKER_IMAGE_NAME}
	ssh -i ${SSH_KEYFILE} ${HOST} sudo cp /tmp/cdjbot.conf /etc/init/
	ssh -i ${SSH_KEYFILE} ${HOST} sudo service cdjbot restart
.PHONY: dbuild push monogostart mongostop
