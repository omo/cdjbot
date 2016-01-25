
# XXX: This should be upgraded LTS once it's available
FROM ubuntu:vivid
RUN apt update -y && apt install -y python3 python3-dev python3-pip
RUN pip3 install virtualenv
ENV APP_HOME /opt/app
RUN mkdir -p $APP_HOME
WORKDIR $APP_HOME

ADD requirements.txt $APP_HOME
RUN /usr/local/bin/virtualenv -p python3 env
RUN . env/bin/activate && pip3 install -r requirements.txt
