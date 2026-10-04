# syntax=docker/dockerfile:1
ARG UBUNTU_IMAGE=ubuntu:22.04@sha256:b1066385161d28ddf6bc7e7b28a9170eec11484c821d1a5150d176cbde41d7f7
FROM ${UBUNTU_IMAGE} AS builder
ARG OP25_COMMIT=71abcd0ead32f86f51615ea6cc8a6a4dba4c949a
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake build-essential pkg-config gnuradio-dev gr-osmosdr \
    libcppunit-dev librtlsdr-dev libuhd-dev libhackrf-dev libairspy-dev \
    liborc-0.4-dev libsndfile1-dev libspdlog-dev libboost-all-dev \
    python3-dev python3-pybind11 python3-numpy python3-setuptools
COPY build/op25-audio-origin.patch /tmp/op25-audio-origin.patch
RUN git clone https://github.com/boatbod/op25.git /opt/op25 \
    && git -C /opt/op25 checkout --detach "${OP25_COMMIT}" \
    && test "$(git -C /opt/op25 rev-parse HEAD)" = "${OP25_COMMIT}" \
    && git -C /opt/op25 apply --check /tmp/op25-audio-origin.patch \
    && git -C /opt/op25 apply /tmp/op25-audio-origin.patch \
    && cmake -S /opt/op25 -B /opt/op25/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/op25/build --parallel 4 \
    && cmake --install /opt/op25/build \
    && rm -rf /opt/op25/build /opt/op25/.git

FROM ${UBUNTU_IMAGE} AS rtl-builder
ARG RTL_BLOG_COMMIT=aed0ea19f3a273370a13c9009b96313c75d54c7b
COPY build/rtl-usb-retry.patch /tmp/rtl-usb-retry.patch
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake build-essential pkg-config libusb-1.0-0-dev
RUN git clone https://github.com/rtlsdrblog/rtl-sdr-blog.git /opt/rtl-sdr-blog \
    && git -C /opt/rtl-sdr-blog checkout --detach "${RTL_BLOG_COMMIT}" \
    && test "$(git -C /opt/rtl-sdr-blog rev-parse HEAD)" = "${RTL_BLOG_COMMIT}" \
    && git -C /opt/rtl-sdr-blog apply --check /tmp/rtl-usb-retry.patch \
    && git -C /opt/rtl-sdr-blog apply /tmp/rtl-usb-retry.patch \
    && cmake -S /opt/rtl-sdr-blog -B /opt/rtl-sdr-blog/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_LIBDIR=lib \
    && cmake --build /opt/rtl-sdr-blog/build --parallel 4 \
    && cmake --install /opt/rtl-sdr-blog/build \
    && rm -rf /opt/rtl-sdr-blog/build /opt/rtl-sdr-blog/.git

# Only the compiled helper is copied into the final image. Source builds with
# no build secret get an empty helper and can still use a local runtime mount.
FROM builder AS rr-key-builder
ARG REQUIRE_RR_EMBED=0
ARG RR_EMBED_REVISION=local
COPY build/build_rr_key_helper.py /tmp/build_rr_key_helper.py
RUN --mount=type=secret,id=rr_key \
    test -n "$RR_EMBED_REVISION" && \
    python3 /tmp/build_rr_key_helper.py --key-file /run/secrets/rr_key \
        --output /out/librrkey.so $(test "$REQUIRE_RR_EMBED" = 1 && printf '%s' --required)

FROM ${UBUNTU_IMAGE} AS runtime
ARG OP25_COMMIT=71abcd0ead32f86f51615ea6cc8a6a4dba4c949a
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="Brutal OP25 - built on boatbod/op25" \
      org.opencontainers.image.version="0.3.0-dev.4" \
      org.opencontainers.image.source="https://github.com/trappedinthesim/brutal-op25" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      io.op25.boatbod.revision="${OP25_COMMIT}"
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    OP25_DATA_DIR=/data OP25_BIND_ADDR=0.0.0.0 \
    OP25_APPS_DIR=/opt/op25/op25/gr-op25_repeater/apps \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/usr/local/lib/python3.10/dist-packages:/usr/lib/python3/dist-packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gnuradio gr-osmosdr python3-venv \
    python3-numpy python3-waitress python3-requests gnuplot-nox \
    libcppunit-1.15-0 liborc-0.4-0 libsndfile1 libspdlog1 libairspy0 \
    libhackrf0 librtlsdr0 libuhd4.1.0 libssl3 usbutils soapysdr-tools tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/ /usr/local/
COPY --from=builder /opt/op25/ /opt/op25/
COPY --from=rtl-builder /usr/local/ /usr/local/
COPY --from=rtl-builder /opt/rtl-sdr-blog/ /opt/rtl-sdr-blog/
COPY --from=rr-key-builder /out/librrkey.so /opt/manager/librrkey.so
RUN ldconfig && python3 -m venv --system-site-packages /opt/venv
WORKDIR /opt/manager
COPY LICENSE THIRD-PARTY-NOTICES.md ./
COPY build/requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip install --no-cache-dir setuptools==84.0.0 \
    && python -c "from gnuradio import gr; import gnuradio.op25, gnuradio.op25_repeater, osmosdr; import zeep"
# Explicit source allowlist: no raw credentials, key files, captures, or profiles.
COPY src/importer.py src/rr_key.py src/library.py src/profile_transfer.py src/test_connection.py src/container_receiver.py src/brutal_ui.py src/brutal_runtime.py src/brutal_supervisor.py src/brutal-ui.css src/brutal-systems.js src/brutal-tuning.js src/brutal-logo.png src/hardware_check.py src/receiver_readiness.py src/brutal_cli.py src/terminal_art.py src/terminal_menu.py src/rsp_receiver.py ./
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin op25 \
    && mkdir -p /data \
    && chown op25:op25 /data
USER op25
EXPOSE 8080 9000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "brutal_cli.py"]
# A terminal process has no HTTP health endpoint.
