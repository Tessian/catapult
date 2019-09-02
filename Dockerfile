FROM python:3.6-alpine3.7 AS deps

COPY ./ /app

ENV LIBGIT2_VERSION=0.28.3
ENV LIBGIT2_SHA256=ac84343b7826ece64185817782a920069c0e419f78ed5d3e4d661e630e32bc26

RUN apk --update add build-base make cmake libressl-dev gcc libffi-dev && \
        wget https://github.com/libgit2/libgit2/archive/v${LIBGIT2_VERSION}.tar.gz && \
        tar xzf v${LIBGIT2_VERSION}.tar.gz && \
        cd libgit2-${LIBGIT2_VERSION}/ && \
        cmake . && \
        make && \
        make install && \
        cd /app && \
        pip install --no-cache-dir -r requirements.txt && \
        python setup.py install && \
        rm -r /app

FROM deps AS catapult

ENTRYPOINT ["catapult"]

FROM deps AS release-resource

RUN apk --update add jq

COPY ./resource /opt/resource
