FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/ssh/ssh_host_* \
    && useradd --create-home --shell /bin/sh probe
COPY sshd_config /etc/ssh/sshd_config_test
COPY entrypoint.sh /target-entrypoint.sh
ENTRYPOINT ["/bin/sh", "/target-entrypoint.sh"]
