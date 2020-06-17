FROM python:3.6-alpine3.12 AS deps

COPY ./ /app

ENV LIBGIT2_VERSION=1.0.1

RUN apk --update add build-base make cmake libressl-dev gcc libffi-dev bash && \
        wget https://github.com/libgit2/libgit2/archive/v${LIBGIT2_VERSION}.tar.gz && \
        tar xzf v${LIBGIT2_VERSION}.tar.gz && \
        cd libgit2-${LIBGIT2_VERSION}/ && \
        mkdir build && cd build && \
        cmake .. && \
        cmake --build . --target install && \
        cd /app && \
        pip install --no-cache-dir -r requirements.txt && \
        python setup.py install && \
        rm -r /app

FROM deps AS catapult

ENTRYPOINT ["catapult"]

FROM deps AS release-resource

RUN apk --update add jq

COPY ./resource /opt/resource
