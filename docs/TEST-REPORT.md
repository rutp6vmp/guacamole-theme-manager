# 實際測試報告

2026-10-31：Session probe 0.2.0 新增共享專項 **53 項通過**；有效舊 key 原生仍可登入，
但 connect 被政策拒絕，已連 HTTP/WS／active join 也實際斷開。政策回退/缺失/換內容/schema
失效、父 revoke 關 tracked child 與不誤殺 primary 均驗證。原 session 57、gate 21＋5、TOTP 46
已重跑通過；本輪沒有重跑整套 132 項 UI/CRUD。參考 [新證據與限制](PAM_SHARING_PROBE.zh-TW.txt)。

最新續作：真實 OpenSSH session suite **57 項通過**；新 module 驗證每次登入綁定、
一次性消耗／併發、真實 active/share 正向對照與拒絕、手動 close、deadline 及 context revoke。
原 G01 21＋5 及 TOTP 46 已重跑通過。單次本機 close 18ms、native remove 47ms、
context revoke 18ms；非正式 SLA。見 [Session probe 證據／限制](PAM_SESSION_PROBE.zh-TW.txt)。
仍無正式 grant/MFA 政策整合、其他協定／錄影、失聯／重啟與跨節點保證；正式服務未變更。

本輪接續：152 項 TXT ledger 已逐項核對並記日期；53 項 Python 檢查、G01 probe
21 項 server＋5 項 browser 通過，原 46 項 TOTP/安全持續性亦重新執行通過。
G01 限 deny-only 隔離試驗；真正活動／共享加入、admission/session 綁定與 G02 未完成。
本輪未重跑下面歷史紀錄中的 132 項 UI/CRUD；主題內容未修改。

CLI 1.2.0 的 PAM 前置部署保護：47 項 Python 檢查、6 項模型檢查、官方容器 TOTP
隔離驗收 46 項、既有 UI／CRUD 回歸 132 項及 Docker rollback / recover 均通過。
詳見 [本批實作狀態（TXT）](PAM_IMPLEMENTATION_STATUS.zh-TW.txt)；沒有正式啟用 MFA
或完成實際 SSH/RDP/VNC 錄影驗收。下方保留既有主題交付報告。

日期：**2026-10-30（Asia/Taipei）**。交付為可安裝的 1.0.0 套件，正式環境與實際遠端工作階段仍須完成下列管理員驗收。

後續已完成既有 Docker 部署串接；本報告下方的權限不足與尚未正式部署為初次開發時狀態，目前情況請見 [部署驗證紀錄](DEPLOYMENT-VERIFICATION.md)。

## 已執行

| 測試 | 結果 | 證據與範圍 |
| --- | --- | --- |
| Python 安全／CLI／交易測試 | 35 項通過 | ZIP/JAR、校驗、路徑、相容版本、信任確認、Compose 範圍與設定變更拒絕、非主題保留、switch/reset/restore/remove/install、失敗 rollback、缺少 Web 容器的 recover、備份獨立還原；Docker 使用模擬 adapter |
| Node 前端模型測試 | 6 項通過 | 授權資料樹、資料來源及物件 ID 隔離、平衡群組、搜尋／分類／子群組、收藏授權交集、主機讀取權限 |
| JavaScript、Python、shell 語法 | 通過 | frontend 語法、Python compile、全部 shell wrapper `sh -n` |
| CLI 安裝及卸載 | 通過 | 在臨時 PREFIX 實際安裝獨立 CLI，執行 version、import、list、remove、uninstall；無 root 或正式檔案變更 |
| 官方原生 Web 登入與繁中 | 前後各 6 項通過 | 無主題時以英文／繁體中文登入，驗證已授權設備數與原生翻譯；主題移除後重做同樣測試 |
| LibreNMS 主題真實瀏覽器 | 28 項通過 | 官方 1.6.0 WAR + 真實 PostgreSQL 認證 + 五種權限帳號；非 REST mock |
| Dark 主題真實瀏覽器 | 28 項通過 | 更換獨立 Dark JAR、實際重啟 Web，重做同一套權限與互動測試 |
| 完整隔離生命週期 | 通過 | 同一個新建測試資料庫，原生 → LibreNMS → Dark → 原生；所有步驟實際重啟 Web，資料與翻譯 JAR 保留 |
| 預建套件與完整性 | 通過 | 兩次建置的所有 SHA-256 相同；驗證兩個主題 ZIP/JAR、外部 SHA256SUMS；完整 release ZIP 解壓後實際安裝 CLI、匯入／列出主題、卸載，並通過內部 checksum |
| 正式環境唯讀檢查 | 通過 | 既有 Web HTTP 200；擴充掛載及服務名稱確認；工作前後現有擴充檔名／SHA-256 相同；未讀取正式 DB 或 .env |
| 無 Docker 權限時的保護 | 通過 | 使用暫存 state 指向正式部署執行 doctor，安全拒絕，未變更正式服務；Docker acceptance harness 在連線 daemon 階段停止 |

合計 **41 項單元／交易測試**，完整生命週期 **68 項瀏覽器檢查**（兩套主題各 28、原生前後各 6）。未把重跑次數額外加總。

瀏覽器測試使用全新隔離資料庫的合成設備 `Windows Lab`、`Linux Lab`、`Router Lab`、`VNC Lab`、`Hidden Lab`，主機為文件保留網段 `192.0.2.10`；帳密由每次執行隨機生成，不出現在報告、專案或 Release。截圖只包含這些合成資料。

讀取者僅看到四個授權設備，沒有 hidden、管理或歷史入口，也不能透過伺服器參數端點讀取主機。編輯者只能顯示單一 UPDATE 授權主機；稽核員可進入原生歷史但不能顯示連線參數；管理員可看到五個設備及原生管理連結；空權限帳號顯示空清單。測試確認連線密碼沒有被渲染。

另涵蓋搜尋、分類、群組、收藏重新載入、個人 Dark / Default、原生 fallback、390px 手機選單與主頁寬度、RDP/SSH/VNC 原生 client URL 及無未處理 JS error。

## 隔離環境

- 官方 Apache Guacamole **1.6.0 WAR**，對照 upstream tag commit `0537c89cd783681b986ff8f8c4e0b97ec6873371`。
- Apache Tomcat **9.0.123**、OpenJDK **21**；PostgreSQL **16.15**（獨立普通使用者 cluster，未連到既有 Docker DB）。
- 官方 Guacamole JDBC PostgreSQL extension **1.6.0**、PostgreSQL JDBC **42.7.8**，僅供測試，不隨 Release 散布。
- Node **22.23.4**、Playwright **1.64.1**、Chromium headless。
- 使用現有 `guacamole-zh-tw.jar` 的只讀副本，核對重啟前後校驗相同。
- 對外僅使用本機 `127.0.0.1` 隨機測試 port；測試 cluster 與 Tomcat base 完成後自動停止並移除。

可透過 `tests/standalone_acceptance.py` 重現。Docker 另有 `tests/docker_acceptance.py`，兩者使用相同合成帳號資料及瀏覽器測試。

## 尚未通過／尚未執行

| 項目 | 原因與下一步 |
| --- | --- |
| 正式 `/opt/guacamole` 的 CLI 切換 | 目前帳號沒有 Docker socket 與免密 sudo 權限；沒有改動正式擴充、Compose、認證或資料庫。管理員依 INSTALL.md 在維護時段執行 |
| 真實 Docker Compose 重建／rollback | 本機 daemon 權限不足。交易邏輯已用模擬 Docker 測試；官方 Web/JAR 已用獨立程序測試，但這不代替 Docker 驗收 |
| 另一套乾淨 Docker 1.6.0 | 提供隔離 harness，需在可使用 Docker 的環境執行，核對 db/guacd container ID 與翻譯校驗保持不變 |
| 真實 RDP 工作階段 | 已驗證原生 RDP client 入口，未提供可用目標及測試授權，尚未驗證握手、畫面與輸入 |
| 真實 SSH 工作階段 | 同上，未宣稱已驗證 shell／鍵盤／重連 |
| 真實 VNC 工作階段 | 同上，未宣稱已驗證畫面／輸入／重連 |
| 正式 PostgreSQL 業務資料保留 | 程式沒有 DB 操作路徑，正式 DB 也未被存取；但正式容器切換後的實際數據核對仍須由管理員完成 |
| GitHub 公開發布 | 已有本機專案、預建 Release、checksum 與 draft-release workflow；未建立／推送遠端 repository，未公開發布 |

CLI 的載入驗證是容器狀態、官方 extension 日誌及 HTTP marker，不是瀏覽器視覺檢查，也不能驗證任意第三方 JavaScript 是否正常運作。第三方主題啟用前仍須審查及執行瀏覽器驗收。任何升級至非 1.6.0 的相容性均未宣告。
