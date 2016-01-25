
ENVS=CDJBOT_TELEGRAM_TOKEN="${CDJBOT_TELEGRAM_TOKEN}"

dbash: dbuild
	docker run --rm -t -i cdjbot /bin/bash
drun: dbuild
	docker run --rm -t -i -e ${ENVS} cdjbot
dbuild:
	docker build --rm -t cdjbot .

.PHONY: dbuild
