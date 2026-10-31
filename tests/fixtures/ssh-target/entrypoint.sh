#!/bin/sh
# Test-only credentials are injected at runtime, never placed in an image layer.
set -eu
mkdir -p /run/sshd
ssh-keygen -A >/dev/null 2>&1
IFS= read -r probe_password < /run/secrets/ssh-password
printf 'probe:%s\n' "$probe_password" | chpasswd
unset probe_password
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config_test
