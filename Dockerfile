FROM python:3.7-buster

ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y \
    redis-server \
    man vim htop procps wget git tini \
    build-essential

RUN mkdir /code

WORKDIR /code

COPY requirements.txt /code/
RUN pip install -r requirements.txt

COPY . /code/

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["./docker_cmd.bash"]
