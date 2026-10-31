# GuacTheme Manager

Installable dashboard themes and a safe CLI for **Apache Guacamole 1.6.0**. Uses official CSS, JavaScript and HTML-patch JAR extensions without modifying the WAR, authentication or production database.

[繁體中文](README.md) · [Installation / recovery](docs/INSTALL.md) · [Theme format](docs/THEMES.md) · [Architecture / upstream references](docs/ARCHITECTURE.md) · [Tests](docs/TESTING.md) · [Release process](docs/RELEASING.md)

## Start here

Read the [standalone Guacamole installation sequence (Traditional Chinese)](docs/GUACAMOLE_INSTALL.zh-TW.md) for the core service setup, first login, remote connection checks and optional theme installation.

For a fresh Ubuntu VM, follow the [step-by-step Docker Compose guide (Traditional Chinese)](docs/NEW_VM_INSTALL.zh-TW.txt): install Docker, initialize a new Guacamole 1.6.0/PostgreSQL deployment, build the themes and enable the CLI. The existing `install.sh` installs only the theme manager.

For an existing Guacamole 1.6.0 deployment:

```bash
git clone https://github.com/rutp6vmp/guacamole-theme-manager.git
cd guacamole-theme-manager
python3 scripts/build.py
(cd dist && sha256sum -c SHA256SUMS)
sudo sh scripts/install.sh
```

Then follow [installation and recovery](docs/INSTALL.md). Git source downloads do not contain prebuilt `dist` artifacts or your deployment credentials/data. The full core Traditional Chinese extension, recording and MFA require separate setup.

## Development and validation

[1.1.0 settings coverage and validation](docs/SETTINGS-1.1.md)

[PAM system plan (Traditional Chinese TXT)](docs/PAM_SYSTEM_PLAN.zh-TW.txt) · [Deployment protection and pilot runbook (Traditional Chinese TXT)](docs/PAM_PILOT_RUNBOOK.zh-TW.txt)

[Dated PAM acceptance ledger (152 requirements, Traditional Chinese TXT)](docs/PAM_ACCEPTANCE.zh-TW.txt)

[G01 test-only Java gate probe](docs/PAM_G01_PROBE.zh-TW.txt) passes 21 server and 5 browser checks in a disposable JDBC fixture. Production admission, stable login-session binding and live-session control remain pending.

The separate [live SSH/context-bound intent and local revocation probe](docs/PAM_SESSION_PROBE.zh-TW.txt) passes 57 checks. Contexts, intents and leases remain in memory; production grants, MFA policy and multi-node behavior are pending.

The 2026-10-31 [session 0.2.0 sharing/policy-failure follow-up](docs/PAM_SHARING_PROBE.zh-TW.txt) passes 53 additional checks with genuinely valid old share keys and live HTTP/WS tunnels. It remains an isolated prototype.

The [session 0.3.0 policy checkpoint/restart follow-up](docs/PAM_RESTART_PROBE.zh-TW.txt) passes 51 additional checks: Web recreation/SIGKILL preserves the policy high-water mark, old handles remain invalid, and storage failures deny new launches. This is a single-node isolated prototype.

The [native dependency outage follow-up](docs/PAM_OUTAGE_PROBE.zh-TW.txt) adds 32 passing checks using the unchanged 0.3.0 probe: PostgreSQL stalls deny launches while local deadlines still close SSH; guacd death, failed-intent consumption and recovery are exercised. The full failure matrix and HA remain pending.

Current session probe source is **0.4.0**, adding [independent startup checks and a protected entry](docs/PAM_INGRESS_PROBE.zh-TW.txt). Missing/altered modules stop startup; the entry checks provider/policy availability before forwarding requests. This remains a single-node localhost prototype; production vendor access is disabled.

CLI **1.2.0** adds `protect-deployment` and an isolated official TOTP acceptance suite. Themes remain **1.1.0**. This is initial PAM groundwork; approval, time-limited admission, vendor isolation and production MFA rollout are still pending.

## Install prebuilt artifacts

Obtain `guacamole-theme-manager-1.2.0.zip` and `SHA256SUMS` from a trusted source. Local builds do not imply a published GitHub release. Verify the archive against the external checksum, extract, then:

```bash
(cd dist && sha256sum -c SHA256SUMS)
sudo sh scripts/install.sh
sudo guac-theme configure \
  --extensions-dir /opt/guacamole/custom/extensions \
  --compose-file /opt/guacamole/compose.yaml \
  --service guacamole \
  --web-url http://127.0.0.1:8080/guacamole/
sudo guac-theme doctor
sudo guac-theme import dist/guac-theme-librenms-1.1.0.zip
sudo guac-theme import dist/guac-theme-dark-1.1.0.zip
sudo guac-theme switch librenms
```

Adjust all paths and the **Compose service name**, which differs from a container name. Requirements: Linux, Python 3.10+, Docker Compose v2 and an existing official `guacamole/guacamole:1.6.0` Web service. No build tools or additional Python packages are needed to install.

Switching prompts for code trust and confirmation of a Web container recreation, which can interrupt remote sessions. Automation must explicitly pass `--trust-theme --yes`. Only the selected Web service is recreated, using `--no-deps --pull never --no-build`. The manager verifies both Compose configuration and runtime mounts before changing the dedicated `guac-theme-managed.jar`. Existing translation and authentication JARs are preserved.

## Commands

```bash
guac-theme list
guac-theme current
guac-theme import theme.zip
guac-theme install librenms
guac-theme switch dark
guac-theme backup
guac-theme restore BACKUP_ID
guac-theme reset
guac-theme remove librenms
guac-theme recover
guac-theme doctor
```

`install` activates an imported theme. Running `bin/guac-theme` from the full release can also import its bundled ZIP automatically; an installed standalone CLI requires explicit ZIP import first. `remove` only removes inactive themes. `reset` removes the manager's active JAR and verifies the native application. An unfinished transaction blocks further mutations until `recover`. Backups contain the managed theme only, not database contents or deployment secrets.

## Dashboard

LibreNMS-inspired original design: dark sidebar, toolbar, authorized inventory, search, category and recursive group filters, pagination, favorites, native connection links, and responsive layout. Supports English and Traditional Chinese alongside `guacamole-zh-tw.jar`, adding only `GTM` translation keys.

A separate translation-only `guacamole-jdbc-zh-tw-1.0.0.jar` supplements all
49 JDBC 1.6.0 keys, including connection concurrency, load balancing, guacd,
account restrictions and password policies. It works independently of the
themes and is included in the full source/prebuilt release. See
[installation and validation (Traditional Chinese TXT)](docs/JDBC_TRANSLATION.zh-TW.txt).

Browser-local appearance choices: LibreNMS, Dark, Light, Default. Favorites store IDs only and are scoped to the user and authentication source. These preferences do not authenticate or authorize anyone. Personal Default retains a small theme selector; server `reset` removes the extension entirely.

All connection data comes from the current user's Guacamole connection tree. History and administration links come from Guacamole's own permitted settings pages. RDP and SSH categories do not prove an operating system; network classification uses group names (Network, Switch, Router, Firewall or Chinese equivalents). Other protocols remain available. Balancing groups retain native connection links.

Host/IP disclosure is explicit and requires system ADMINISTER or UPDATE on that connection. The 1.6.0 native parameters endpoint returns the authorized full parameter map, potentially including passwords; the theme disables caching, retains only hostname in memory, and never renders, logs or persists other parameters. Unauthorized users do not request parameters. No direct SQL or alternate backend is used.

Version 1.1.0 extends the theme to native settings, user/user-group editors, connection/group/sharing-profile editors, history, sessions, preferences and connection import/help. These pages share the sidebar, toolbar and personal palette while retaining native forms, validation, confirmation dialogs and authorized persistence. Login, remote clients and immersive recording playback keep their native presentation. No device-health monitoring, invented metrics, ordinary-user global history or cross-device favorite synchronization is provided.

The extension-loading and HTML-patch mechanisms are official APIs. The Angular services and home template adapter are **version-pinned 1.6.0 internals**. Future Guacamole versions require revalidation; wildcard compatibility is rejected.

## Validation and security

See the [test report](docs/TEST-REPORT.md) and subsequent [deployment verification](docs/DEPLOYMENT-VERIFICATION.md). Security/transaction tests and an isolated official-WAR browser test have been run. LibreNMS has also been activated on an existing Docker deployment, preserving the database/guacd containers and translation JAR. Real RDP/SSH/VNC handshakes remain operator acceptance steps.

The CLI rejects traversal, symlinks, oversized archives, duplicate members, invalid checksums, Java classes, nested JARs, authentication providers, listeners, install scripts and undeclared resources. JavaScript/HTML themes still execute with the signed-in user's origin privileges: checksums establish integrity, not publisher trust. Review third-party themes before activation.

Apache-2.0. No LibreNMS code or assets are included; neither LibreNMS nor Apache Guacamole endorses this project.
