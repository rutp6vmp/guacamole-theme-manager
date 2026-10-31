#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# TEST ONLY. Runs before the unchanged official Guacamole 1.6.0 entrypoint.
set -eu
refuse() { printf '%s\n' 'PAM_PROBE_BOOTSTRAP_REFUSED' >&2; exit 78; }
[ "${PAM_SESSION_PROBE_ENABLED:-}" = fixture-only ] || refuse
[ "$#" -eq 1 ] || refuse
case "$1" in /opt/guacamole/bin/entrypoint.sh|--check-only) ;; *) refuse ;; esac
directory=${PAM_SESSION_PROBE_EXTENSIONS_DIR:-/etc/guacamole/extensions}
case "$directory" in /*) ;; *) refuse ;; esac
[ -d "$directory" ] && [ ! -L "$directory" ] || refuse
jar=$directory/guacamole-pam-session-probe.jar
expected=${PAM_SESSION_PROBE_REQUIRED_SHA256:-}
case "$expected" in ''|*[!a-f0-9]*) refuse ;; esac
[ "${#expected}" -eq 64 ] || refuse
[ -f "$jar" ] && [ ! -L "$jar" ] || refuse
actual=$(sha256sum "$jar" 2>/dev/null) || refuse
actual=${actual%% *}
[ "$actual" = "$expected" ] || refuse
printf '%s\n' 'PAM_PROBE_BOOTSTRAP_READY'
[ "$1" != --check-only ] || exit 0
exec "$@"
