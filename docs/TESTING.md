# 測試與人工驗收

## 自動化單元／交易測試

開發機需 Python 3.10+ 及 Node.js 22+。安裝使用者不需要 Node。

```bash
sh scripts/test.sh
```

涵蓋惡意 ZIP/JAR、校驗、版本、路徑、重複檔案／JSON、Java 認證提供者拒絕、完整切換／reset／restore、切換失敗 rollback、rollback 失敗保留 pending、寫入中斷 recover、未知 JAR 保護、唯讀掛載／服務映像／跨服務掛載檢查、信任及重啟確認、非主題 JAR 保留。交易測試使用**假 Docker adapter**，不代表真實 Docker 已通過。

前端 Node 測試涵蓋資料來源／物件 ID 隔離、平衡群組、遞迴群組、搜尋分類、授權後收藏交集、hostname 權限及空資料。

## 官方 Web 的瀏覽器測試

G01 最小 Java 探針與隔離實測見 [G01 操作／限制（TXT）](PAM_G01_PROBE.zh-TW.txt)。
使用 `scripts/build_pam_probe.py` 另外建置，`tests/gate_acceptance.py` 會測新建 JDBC fixture、
HTTP/WebSocket 及原生 client URL，並清理自己的測試容器。切勿安裝 probe 到正式環境。
`scripts/check_acceptance.py` 核對 [152 項驗收表（TXT）](PAM_ACCEPTANCE.zh-TW.txt) 的日期、
證據與規劃指紋，只驗資料一致性，不會把項目自動標成通過。

真實 SSH 與單節點控制另由 `tests/session_acceptance.py` 驗證，需另外以
`scripts/build_pam_probe.py --probe session --war /path/to/guacamole-1.6.0.war` 建置。
測試會建立新的 OpenSSH image、隨機 localhost fixture 與合成帳密，驗證 context 綁定、
一次性資格、真實 active join、新共享拒絕、到期、撤銷及不誤殺；操作和限制見
[Session probe（TXT）](PAM_SESSION_PROBE.zh-TW.txt)。不接受正式路徑作為目標。

目前 session 產物為 0.2.0。加 `--suite sharing` 可執行 53 項舊共享憑證／已連 HTTP/WS／
政策故障專項，見 [共享驗證（TXT）](PAM_SHARING_PROBE.zh-TW.txt)。它會先用明確的測試
sharing-control 模式建立正向對照，再在同一 Web 收緊政策，不用重啟來假裝舊 key 已被攔截。

PAM 前置驗證另由 `python3 tests/pam_acceptance.py` 執行，需 Docker 操作權。
會自行建立隨機 localhost 專案及合成資料庫，測官方 TOTP、部分原生 API 權限及主題操作的安全設定持續性。
操作與限制見 [TXT 試點手冊](PAM_PILOT_RUNBOOK.zh-TW.txt)。不需要真實帳號或正式環境路徑，也不需要 Node。
GitHub 另提供手動觸發的 `Isolated PAM acceptance` workflow；本機通過不表示已在 GitHub 執行。

`tests/seed.py` 只用於**新建隔離資料庫**。產生五種使用者與文件保留網段 `192.0.2.10` 的合成設備：管理員、讀取者、單一連線編輯者、稽核員、空權限。請勿套用到正式資料庫。

`tests/browser.mjs` 以 Playwright 驗證真實 Guacamole UI 和實際 PostgreSQL 認證後的權限。安裝測試依賴到專案外或未追蹤目錄：

```bash
npm install --prefix /tmp/gtm-browser playwright
/tmp/gtm-browser/node_modules/.bin/playwright install chromium
export GTM_PLAYWRIGHT_MODULE=/tmp/gtm-browser/node_modules/playwright/index.mjs
export GTM_TEST_URL=http://127.0.0.1:18080/guacamole/
# GTM_TEST_PASSWORD 須與建立隔離資料庫時的隨機密碼相同；勿寫入 repo。
node tests/browser.mjs
```

可指定 `GTM_SCREENSHOT_DIR`，截圖只使用合成資料。瀏覽器測試不輸出 token、密碼、HTTP headers 或完整 response。包含搜尋、群組、收藏 reload、個人配色、原生 fallback、RWD 及不同權限的可見資訊。

1.1.0 的 `tests/settings-browser.mjs` 另覆蓋各管理頁及原生 CRUD，必須只對 `seed.py` 建立的新測試資料庫執行。Docker acceptance 會在 LibreNMS 與 Dark 下各執行一次，之後驗證切換、reset、restore 及故障 recover。只測設定頁時可設 `GTM_TEST_SUITE=settings`。開發除錯可設 `GTM_TEST_RETAIN_ON_FAILURE=1` 保留自己建立的私有 fixture；此模式需手動清理顯示的隨機測試專案及暫存目錄，禁止公開其中的測試憑證檔。預設自動清理。

2026-11-01 起 Docker fixture 也載入獨立 JDBC 繁中套件，設定頁另檢查新增連線、連線群組及使用者編輯頁的實際中文標籤；切換、reset、restore 前後比對語系 JAR 校驗。測試前先執行建置，讓 dist 包含 guacamole-jdbc-zh-tw-1.0.0.jar。詳見 [本次中文化紀錄](JDBC_TRANSLATION.zh-TW.txt)。

沒有 Docker 權限時，可先下載官方 WAR、Tomcat 9、Guacamole JDBC PostgreSQL extension、PostgreSQL JDBC driver，準備普通使用者可啟動的 Java runtime 與 PostgreSQL 16 binaries，執行完整隔離驗收：

```bash
python3 tests/standalone_acceptance.py \
  --java-home /path/to/java-home \
  --tomcat /path/to/apache-tomcat-9 \
  --pg-bin /path/to/postgresql/16/bin \
  --war /path/to/guacamole-1.6.0.war \
  --jdbc-extension /path/to/guacamole-auth-jdbc-postgresql-1.6.0.jar \
  --jdbc-driver /path/to/postgresql-driver.jar \
  --schema /path/to/postgresql/schema/001-create-schema.sql \
  --translation-jar /path/to/guacamole-zh-tw.jar
```

若 PostgreSQL binaries 的動態函式庫不在系統路徑，可加 `--pg-lib /path/to/libs`。需設好 Playwright 的 module path，Node 需在 PATH。腳本拒絕 root，僅建立新的臨時 cluster、Tomcat base 與隨機 port，使用同一個隔離資料庫測試原生 → LibreNMS → Dark → 原生，每次實際重啟 Web 並登入，結束自動停止並刪除測試環境。既有翻譯 JAR 只讀取及複製，不會修改來源。

## 新的 Docker Compose 環境

`tests/docker_acceptance.py` 會在臨時目錄與隨機 project name 建立獨立 Guacamole 1.6.0 / guacd 1.6.0 / PostgreSQL 16，僅綁定 `127.0.0.1` 隨機測試 port。測試使用 tmpfs 資料庫與臨時 fixture bind mount，不會接觸 `/opt/guacamole` 或既有 Volumes。需要已可用的 Docker 權限及 Playwright。

```bash
python3 tests/docker_acceptance.py
```

測試會明確建立新專案，做 import、install、dark switch、reset、restore、CLI doctor 以及瀏覽器檢查；結束時只清理自己建立的隨機測試專案，不接受外部 compose 路徑或 project name。這個測試 harness 的建立／清理操作不屬於正式 CLI 的操作範圍。

初次開發時沒有 Docker socket 權限；後續已有管理員授權並完成既有 Docker 部署串接。乾淨 Docker 驗收的最新結果以 [部署驗證紀錄](DEPLOYMENT-VERIFICATION.md) 為準。

## 人工正式驗收

在維護時段，以擁有 Docker 權限的管理員執行。以下項目必須逐一記錄 pass/fail，不能由單元測試結果代替。

| 項目 | 操作與預期 |
| --- | --- |
| 原生基準 | 安裝前登入、語系、RDP/SSH/VNC 各建立一次實際 session；確認使用者／連線／權限數量 |
| 翻譯 | 啟用前後核對 `guacamole-zh-tw.jar` SHA-256 相同，登入與原生設定仍為繁體中文 |
| 主題載入 | `doctor` 通過；首頁有側邊欄、真實設備及正確人數權限；無 JS console error |
| 權限矩陣 | 一般使用者不看到未授權設備／hostname／歷史／管理入口；編輯者只可查看自己有 UPDATE 的 hostname |
| 搜尋分類 | 名稱、協定、群組搜尋；巢狀群組；空結果；收藏切換及重新登入；不同帳號收藏互不混用 |
| 原生連線 | 從主題連結實際連線 RDP、SSH、VNC，測試鍵盤、畫面及斷線／重連。URL 正確不等同 handshake 成功 |
| RWD | 手機導航可開關，表格內可橫向捲動，主頁不溢出；鍵盤 focus 可見 |
| 主題切換 | LibreNMS → Dark → reset → restore，每次確認僅 Web container ID 改變，guacd／PostgreSQL container ID 不變 |
| DB 保留 | 由管理員在本機比對非敏感計數／權限；不要將資料庫內容或憑證印到公開報告。連線歷史因登入／連線會自然增加 |
| 異常還原 | **只在隔離環境**模擬新主題無法載入，確認前一 JAR 校驗恢復，Web 可登入；若 daemon 故障則應保留 pending 並可 recover |
| 可分享 | 另一台乾淨 Docker 1.6.0 執行同樣流程；不需安裝 Java/Maven/Node 即可使用預建 CLI 與 JAR |
| 升級 | 此版本只支援 1.6.0；換版前重做整份矩陣 |

不要故意破壞正式 Web、DB 或掛載來測 rollback。工具的失敗注入測試使用臨時目錄與模擬 adapter；真正容器故障驗收只能在隔離環境執行。
