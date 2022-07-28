FROM python:3.7-alpine3.16 AS deps

COPY ./ /app

ENV LIBGIT2_VERSION=1.4.3

RUN apk --update add build-base gcc libffi-dev bash libgit2-dev && \
        cd /app && \
        pip install --no-cache-dir . && \
        rm -r /app

FROM deps AS catapult

ENTRYPOINT ["catapult"]

FROM deps AS release-resource

RUN apk --update add jq

COPY ./resource /opt/resource
