# 部署驗證紀錄

日期：2026-10-30（Asia/Taipei）。已在一套既有的官方 Guacamole 1.6.0 Docker Compose 部署完成串接，啟用 **LibreNMS Style 1.0.0**。Dark 已匯入，可由管理員日後切換。

後續已將同一部署升級至 **1.1.0**，補齊系統設定頁面，詳見 [1.1.0 交付與驗證](SETTINGS-1.1.md)。下方初次部署的 1.0.0 紀錄保留供追溯。

## 已確認

- CLI 已安裝，部署設定已保存；`current` 顯示 `librenms`，`recoveryRequired` 為 false，`doctor` 通過。
- 切換前已建立原生介面的自動備份。
- 只有 Web 容器重建；PostgreSQL 與 guacd 的容器 ID 維持原值，三個服務均正常執行。
- 以掛載目的地比對，三個容器的掛載設定與原有來源保持一致；原 Compose 檔案 SHA-256 未變。
- 原有繁體中文 JAR 的 SHA-256 未變；只新增管理工具專用主題 JAR，內容與 Release 的 LibreNMS JAR 完全相同。
- 實際 Web 回傳 `gtm-librenms` 的 1.0.0 marker，且官方擴充載入紀錄通過 CLI 驗證。
- 以真實瀏覽器驗證正式 Web 已註冊主題控制器，`GTM.DASHBOARD` 顯示「儀表板」、原生登入文字顯示「登入」，未發現未處理的 JavaScript 錯誤。

這次串接沒有讀寫既有 PostgreSQL 內容。管理員密碼未保存到專案、設定檔或 Release；部署前後的容器與檔案比對紀錄保存在管理員專用狀態位置，不隨公開套件散布。

## 乾淨 Docker 環境驗收

後續執行 `tests/docker_acceptance.py` **通過**。在隨機專案名稱、隨機本機 port、新建 tmpfs PostgreSQL 資料庫及唯讀測試擴充掛載下，實際完成：

- 原生 doctor、兩套 ZIP 匯入、LibreNMS install、備份。
- 五種權限帳號的 28 項真實瀏覽器檢查。
- Dark switch、reset、從備份 restore，每次重新驗證 Web 與主題。
- 注入不可用的 readiness URL，確認切換失敗時還原先前檔案；驗證仍不可用時保留 pending。修正測試 URL 後 recover 成功，pending 清除。
- 全程保持該測試專案 PostgreSQL／guacd 容器 ID 與繁體中文 fixture JAR 校驗不變。
- 完成後清理自己建立的隔離容器及暫存資料，正式部署仍持續提供 LibreNMS。

測試 fixture 使用官方 guacd 映像相同的健康檢查命令，將探測間隔從五分鐘縮短為兩秒，以便在測試期限內完成 `compose --wait`；此設定只作用於隔離測試專案。

此結果補足初次開發報告中「乾淨 Docker 部署」與「實際 Compose 切換／故障復原」的待驗證項目。實際 RDP、SSH、VNC 目標的握手、畫面、輸入及重連仍須由有連線權限的使用者驗收。

## 如何看到主題

登入原本的 Guacamole 網址，返回設備首頁，按 **Ctrl+Shift+R** 強制重新整理。主題修改的是登入後的設備首頁；登入畫面、遠端連線畫面、原生設定與歷史頁面仍保留原本介面。

若個人外觀選擇了 Default，可用外觀選單切回 LibreNMS。首次驗收仍需由具有實際連線權限的使用者登入，操作自己的 RDP、SSH、VNC 目標。

原始 [測試報告](TEST-REPORT.md) 中「無 Docker 權限、尚未正式部署」描述的是初次開發時的狀態；目前部署狀態以本紀錄為準。
