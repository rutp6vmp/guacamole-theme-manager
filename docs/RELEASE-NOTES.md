GuacTheme Manager CLI 1.2.0 (themes remain 1.1.0)

2026-11-01: separate guacamole-jdbc-zh-tw-1.0.0.jar provides Traditional
Chinese for all 49 JDBC 1.6.0 translation keys. Covers connection concurrency,
load balancing, guacd settings, group/user restrictions and password policies.
The translation-only overlay works independently of the themes and preserves
the existing core language extension. See JDBC_TRANSLATION.zh-TW.txt.

2026-10-31: session probe 0.2.0 adds protected-file sharing controls, fail-closed
required-policy checks, monotonic in-memory generations and tracked parent/child
closure. 53 live checks cover genuinely valid previous share keys and existing
HTTP/WS tunnels; original session 57, gate 21+5 and TOTP 46 pass again. This is
still a single-node test prototype with no durable restart/HA or production grants.

Further P00 increment: separate session probe 0.1.0 and a disposable OpenSSH
target pass 57 live checks: per-login context binding, one-use/concurrent launch,
active/share guards, local deadline and actual tunnel closure. Original gate and
TOTP regression suites pass again. The probe is not a production grant/MFA engine
and is built independently with --probe session, never installed with a theme.

Development follow-up (2026-10-30): dated 152-item TXT acceptance ledger,
consistency checks and separate test-only G01 Java gate probe 0.1.0. The probe
passes 21 server and 5 browser checks against an isolated official installation;
admission/session binding and real active/shared joins remain pending.
Probe source is included; test binaries are built separately under dist/poc
and are never installed or imported as a static theme.

- Added protect-deployment: adopt an already-running complete Compose file list
  without resetting an active theme or recreating containers. The existing
  config.json and lock are the shared manifest for all managed operations.
- Reject missing live Compose overlays, disabled required official TOTP/recording
  modules, and modified/missing pinned security JARs before theme mutation.
- Preserve security requirements across theme reset, restore and recovery;
  verify official module load after recreation. Adoption preserves a private
  configuration backup; configure cannot remove protected requirements.
- Added isolated official JDBC/TOTP acceptance and native API permission probes.
  See PAM_PILOT_RUNBOOK.zh-TW.txt and PAM_IMPLEMENTATION_STATUS.zh-TW.txt.
- No production MFA rollout, admission gate, vendor isolation, real recording
  acceptance or vault integration is included in this initial PAM increment.

GuacTheme Manager 1.1.0

- Completed themed settings and native editors: users, user groups, connections,
  connection groups, sharing profiles, history, sessions, preferences and import/help.
- Shared personal palettes across dashboard and administration pages; native
  forms, permissions, save/delete behavior and confirmation dialogs retained.
- Explicit CLI upgrade and repository replacement with preserved backups.

- Installable LibreNMS Style and Dark themes for Apache Guacamole 1.6.0.
- Authorized connection inventory, search, categories, groups, favorites, and native remote-client routes.
- English / Traditional Chinese compatibility; browser-local palette preferences.
- Standard-library Python CLI with validated imports, explicit trust/restart confirmation, Compose scope verification, backups, rollback, restore and interrupted-transaction recovery.
- Prebuilt JARs and ZIPs; no compiler needed for installation.

Read docs/TEST-REPORT.md for executed validation and remaining operator checks.
An existing Docker deployment has been activated and verified; see
docs/DEPLOYMENT-VERIFICATION.md for subsequent validation. Real RDP/SSH/VNC
handshakes are not claimed complete. The frontend adapter supports 1.6.0 only.

Theme JavaScript/HTML runs with the current user's origin privileges. SHA-256
checks integrity, not publisher trust. Review third-party themes before activation.
