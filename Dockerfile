FROM python:3.6-alpine3.12 AS deps

COPY ./ /app

ENV LIBGIT2_VERSION=1.0.1

RUN apk --update add build-base gcc libffi-dev bash libgit2-dev && \
        cd /app && \
        pip install --no-cache-dir -r requirements.txt && \
        python setup.py install && \
        rm -r /app

FROM deps AS catapult

ENTRYPOINT ["catapult"]

FROM deps AS release-resource

RUN apk --update add jq

COPY ./resource /opt/resource
