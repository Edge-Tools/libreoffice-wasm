FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc-12 \
    g++-12 \
    git \
    curl \
    wget \
    ca-certificates \
    python3 \
    python3-dev \
    autoconf \
    automake \
    libtool \
    pkg-config \
    flex \
    bison \
    gperf \
    nasm \
    zip \
    unzip \
    libssl-dev \
    libcap-dev \
    xsltproc \
    libxml2-utils \
    meson \
    ninja-build \
    xz-utils \
    && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 120 \
                            --slave   /usr/bin/g++ g++ /usr/bin/g++-12 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 https://github.com/emscripten-core/emsdk.git /emsdk \
    && /emsdk/emsdk install 3.1.71 \
    && /emsdk/emsdk activate 3.1.71 \
    && chmod -R a+rX /emsdk
ENV PATH="/emsdk/upstream/emscripten:/emsdk/upstream/bin:${PATH}"
ENV EMSDK=/emsdk
ENV EM_CONFIG=/emsdk/.emscripten

RUN useradd -m -u 1000 lo \
    && mkdir -p /src /dist \
    && chown lo:lo /src /dist

ARG VERSION=26.2.2.2
ENV VERSION=${VERSION}
ENV SOURCE_SHA256=e5af29abc1f1c8961787700ff50bc62a3d69b7293e20a968c4a352fd32155fd7

USER lo
WORKDIR /src

RUN SRC_DIR="${VERSION%.*}" \
    && curl -fsSL -o /tmp/lo.tar.xz \
        "https://download.documentfoundation.org/libreoffice/src/${SRC_DIR}/libreoffice-${VERSION}.tar.xz" \
    && echo "${SOURCE_SHA256}  /tmp/lo.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/lo.tar.xz --strip-components=1 -C /src \
    && rm /tmp/lo.tar.xz \
    && echo "lo_sources_ver=${VERSION}" > /src/sources.ver

COPY --chown=lo:lo patches/emscripten-modular.py /tmp/emscripten-modular.py
RUN python3 /tmp/emscripten-modular.py \
    solenv/gbuild/platform/EMSCRIPTEN_INTEL_GCC.mk

RUN ./autogen.sh \
    --disable-debug \
    --enable-sal-log \
    --disable-crashdump \
    --host=wasm32-local-emscripten \
    --disable-gui \
    --with-wasm-module="writer calc impress" \
    --without-java

RUN make -j$(nproc)

RUN cp /src/instdir/program/soffice.wasm             /dist/soffice.wasm \
    && cp /src/instdir/program/soffice.data             /dist/soffice.data \
    && cp /src/instdir/program/soffice.data.js.metadata  /dist/soffice.data.js.metadata \
    && cp /src/instdir/program/soffice.js               /dist/soffice.mjs \
    && cp /src/instdir/program/soffice.js               /dist/soffice.js \
    && [ "$(head -c4 /dist/soffice.wasm | od -An -tx1 | tr -d ' \n')" = "0061736d" ] \
    && [ "$(stat -c%s /dist/soffice.wasm)" -gt 10485760 ] \
    && [ "$(stat -c%s /dist/soffice.data)" -gt 10485760 ]

COPY --chown=lo:lo patches/node-compat.py /tmp/node-compat.py
RUN python3 /tmp/node-compat.py /dist/soffice.mjs \
    && cp /dist/soffice.mjs /dist/soffice.js

FROM scratch AS exportor
COPY --from=builder /dist /dist
