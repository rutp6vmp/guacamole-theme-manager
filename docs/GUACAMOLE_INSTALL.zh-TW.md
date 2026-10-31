# Guacamole 完整安裝順序

更新日期：2026-11-01（Asia/Taipei）

適用環境：**全新 Ubuntu 22.04／24.04 VM、Bash、sudo、Docker Compose v2**。

本頁版本：Guacamole **1.6.0**、PostgreSQL **16**；可選主題 **1.1.0**、CLI **1.2.0**。

[返回專案首頁](../README.md) · [含本專案工具的 TXT 操作版](NEW_VM_INSTALL.zh-TW.txt) · [既有部署安裝／還原](INSTALL.md)

這一頁從 **原生 Guacamole** 開始，先確認登入與遠端連線成功，再安裝主題及中文補充。每個步驟都有「完成條件」，上一個步驟未通過就先停下排查。

所有 Compose、資料庫密碼、帳號與設備設定都在**新 VM** 建立，沒有帶入原服務的實際設定。已有 Guacamole 的主機請使用既有部署文件，不要重做本頁的初始化。

## 安裝順序總覽

| 順序 | 要做的事 | 完成條件 |
|---|---|---|
| [1](#1-準備新-vm) | 準備 Ubuntu 與 SSH | 能登入新 VM 並使用 sudo |
| [2](#2-安裝-docker-與-compose) | 安裝 Docker Engine／Compose | Docker 與 Compose 命令可用 |
| [3](#3-建立目錄與私有密碼) | 建立目錄與隨機資料庫密碼 | 私有 .env 已建立 |
| [4](#4-建立三個服務的-compose) | 設定 PostgreSQL、guacd、Web | Compose 範本已存放在新 VM |
| [5](#5-先產生資料庫初始化-sql) | 產生官方資料表與初始管理員 | 初始化 SQL 檔不是空檔 |
| [6](#6-啟動並確認原生-guacamole) | 啟動三個容器 | Web readiness 通過 |
| [7](#7-開啟網頁登入並更換初始密碼) | SSH 轉送、首次登入、換密碼 | 用新密碼重新登入成功 |
| [8](#8-新增並驗證-rdp-或-ssh-連線) | 加入自己的 Windows／Linux | 能看到實際遠端畫面／終端 |
| [9](#9-選用安裝本專案主題與中文補充) | 安裝 GuacTheme Manager | doctor 與主題 marker 通過 |
| [10](#10-正式使用前的設定順序) | HTTPS、權限、備份與可選功能 | 完成自己的部署驗收 |

## 1 準備新 VM

在虛擬化平台建立 Ubuntu Server VM，完成作業系統、管理使用者與網路設定。確認 VM 有足夠磁碟空間供系統、Docker 映像及資料庫使用，並能連外下載套件。

在 VM 的終端執行：

```bash
cat /etc/os-release
sudo -v
```

如果要從自己的電腦用 SSH 管理，而新 VM 尚未安裝 SSH Server，可在 VM 主控台執行：

```bash
sudo apt-get update
sudo apt-get install -y openssh-server
sudo systemctl enable --now ssh
```

[Ubuntu 官方 OpenSSH 說明](https://ubuntu.com/server/docs/how-to/security/openssh-server/)

**完成條件：**知道新 VM 的位址、能登入並使用 sudo。後續第 2～6 步都在新 VM 的 Bash 執行。

## 2 安裝 Docker 與 Compose

全新主機使用以下指令。已有可運作 Docker 的主機，先確認版本即可，不要重裝套件。

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$(dpkg --print-architecture)" "$VERSION_CODENAME" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
```

再確認 Docker daemon 可用：

```bash
sudo docker version
sudo docker compose version
python3 --version
```

**完成條件：**兩個命令都成功。後續 Docker 命令使用 sudo，不需要把一般使用者加入 docker 群組。套件來源依 [Docker 官方 Ubuntu 安裝文件](https://docs.docker.com/engine/install/ubuntu/)核對。

## 3 建立目錄與私有密碼

建立 /opt/guacamole、初始化目錄與 extensions 目錄，並產生隨機資料庫密碼。**若目錄已存在，程式會停止；請改用既有部署流程，不要接著覆寫設定。**

```bash
sudo python3 - <<'PY'
from pathlib import Path
import os
import secrets

root = Path('/opt/guacamole')
if root.exists() or root.is_symlink():
    raise SystemExit('STOP: /opt/guacamole already exists; use the existing-installation guide.')
root.mkdir(mode=0o755)
(root / 'init').mkdir(mode=0o755)
(root / 'custom/extensions').mkdir(mode=0o755, parents=True)
fd = os.open(root / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write('DB_PASSWORD=' + secrets.token_hex(32) + '\n')
print('Created a new deployment directory and private random database password.')
PY
```

| 路徑 | 用途 |
|---|---|
| /opt/guacamole/.env | 此 VM 的私有資料庫密碼，僅 root 可讀寫 |
| /opt/guacamole/init/ | 官方資料庫初始化 SQL |
| /opt/guacamole/custom/extensions/ | 主題、語系與其他擴充 JAR |
| Docker 的 postgres_data Volume | PostgreSQL 的持久資料，與專案來源分開 |

**完成條件：**建立命令成功且未輸出密碼；不要把 .env、資料庫或備份上傳 Git。

## 4 建立三個服務的 Compose

| 服務 | 負責什麼 |
|---|---|
| postgres | 儲存 Guacamole 帳號、權限、設備與連線歷史 |
| guacd | 實際連接 Windows RDP／Linux SSH 等遠端協定 |
| guacamole | 提供登入網頁與管理介面，將使用者的連線交給 guacd |

以下是**通用範本**。Web 只聽本機 8080；資料庫與 guacd 不公開主機連接埠。這樣初次設定可透過 SSH 進行，正式入口之後再設 HTTPS。

```bash
sudo tee /opt/guacamole/compose.yaml > /dev/null <<'YAML'
name: guac-new-vm
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: guacamole_db
      POSTGRES_USER: guacamole_user
      POSTGRES_PASSWORD: ${DB_PASSWORD:?Set DB_PASSWORD in the private .env}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "guacamole_user", "-d", "guacamole_db"]
      interval: 5s
      timeout: 5s
      retries: 30
  guacd:
    image: guacamole/guacd:1.6.0
    restart: unless-stopped
  guacamole:
    image: guacamole/guacamole:1.6.0
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - ./custom/extensions:/etc/guacamole/extensions:ro
    environment:
      GUACD_HOSTNAME: guacd
      POSTGRESQL_ENABLED: "true"
      POSTGRESQL_HOSTNAME: postgres
      POSTGRESQL_DATABASE: guacamole_db
      POSTGRESQL_USERNAME: guacamole_user
      POSTGRESQL_PASSWORD: ${DB_PASSWORD:?Set DB_PASSWORD in the private .env}
    depends_on:
      postgres:
        condition: service_healthy
      guacd:
        condition: service_started
volumes:
  postgres_data:
YAML
```

**完成條件：**新 VM 已建立 compose.yaml；其中 DB_PASSWORD 引用第 3 步產生的 .env，不需要把密碼填進 Compose 文字。[官方 Docker 架構說明](https://guacamole.apache.org/doc/1.6.0/gug/guacamole-docker.html)

## 5 先產生資料庫初始化 SQL

**順序不能跳過：先產生 SQL，再第一次啟動空資料庫。** Guacamole Web 不會自行建立所需資料表。

```bash
set -euo pipefail
sudo docker run --rm --entrypoint /opt/guacamole/bin/initdb.sh guacamole/guacamole:1.6.0 --postgresql | sudo tee /opt/guacamole/init/001-initdb.sql > /dev/null
sudo test -s /opt/guacamole/init/001-initdb.sql
```

**完成條件：**test -s 成功，代表初始化檔有內容。PostgreSQL 官方映像會在新空 Volume 的首次啟動時執行該檔。

已有資料的 Volume 不會再次執行 init 目錄；遇到缺資料表時，先檢查是否跳過本步或用了舊 Volume。不要直接刪掉資料庫 Volume，也不要把初始化 SQL 重複匯入已有資料的資料庫。[官方 PostgreSQL 初始化說明](https://guacamole.apache.org/doc/1.6.0/gug/postgresql-auth.html)

## 6 啟動並確認原生 Guacamole

先啟動原生系統，此時尚未需要下載本專案或安裝主題。

```bash
sudo docker compose -f /opt/guacamole/compose.yaml -p guac-new-vm up -d
sudo docker compose -f /opt/guacamole/compose.yaml -p guac-new-vm ps
```

首次下載映像及啟動需要時間。執行以下 Web 檢查，最久等待約三分鐘：

```bash
python3 - <<'PY'
import time
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for attempt in range(90):
    try:
        with opener.open('http://127.0.0.1:8080/guacamole/', timeout=2) as response:
            if response.status == 200 and b'ng-app="index"' in response.read():
                print('Guacamole Web is ready.')
                break
    except OSError:
        pass
    time.sleep(2)
else:
    raise SystemExit('Web is not ready; check this new deployment before continuing.')
PY
```

**完成條件：**顯示 Guacamole Web is ready.。若逾時，停在這一步，在管理員終端檢查新專案的容器狀態與日誌；不要把完整日誌、inspect 或展開後的 Compose 公開貼出。

## 7 開啟網頁登入並更換初始密碼

在**您自己的電腦**另開終端，把 VM_USER 與 VM_IP 換成新 VM 的 SSH 使用者及位址：

```bash
ssh -N -L 18080:127.0.0.1:8080 VM_USER@VM_IP
```

保持此 SSH 視窗開啟，用自己電腦的瀏覽器進入：

**http://127.0.0.1:18080/guacamole/**

- 新資料庫的官方初始帳號：guacadmin。
- 官方初始密碼：guacadmin。
- 登入後到使用者設定，編輯 guacadmin、設定新密碼並儲存，再登出驗證新密碼。

這組初始值只適用這次新建的官方資料庫，不是原系統的帳密。Web 綁定 VM 的 localhost，因此直接打 VM_IP:8080 不會通；這是本教學的預期配置。

**完成條件：**可以用自己的新管理員密碼登入原生介面。主題與錄影都還不是必要條件。

## 8 新增並驗證 RDP 或 SSH 連線

在設定的連線頁新增設備。請填寫**從 Guacamole／guacd 所在網路可達**的目標，不要只以自己的電腦能連線作判斷。

| 欄位 | Windows RDP | Linux SSH |
|---|---|---|
| 名稱 | 自行取便於辨識的名稱 | 自行取便於辨識的名稱 |
| 協定 | RDP | SSH |
| 參數 → 網路 → 主機名稱 | 目標 Windows 位址 | 目標 Linux 位址 |
| 參數 → 網路 → 連接埠 | 實際 RDP 埠，預設通常是 3389 | 實際 SSH 埠，預設通常是 22 |
| 驗證資料 | 目標 Windows 的帳號與密碼 | 目標 Linux 的帳號及密碼／金鑰 |
| 網域 | 有需要時填 AD 網域或本機 Windows 電腦名稱 | 不適用 |
| RDP 安全性模式 | 可選「任意」，自動協商 | 不適用 |
| guacd 主機／連接埠覆寫 | 一般留白，沿用系統設定 | 一般留白，沿用系統設定 |

**guacd 連接埠不要填 0。**「參數 → 網路」才是目標設備的位址與埠；Guacamole 網頁密碼與目標 Windows／Linux 密碼各有用途。

RDP 憑證需使用可信憑證或經核對的信任方式；不要為了能連線就對所有設備開啟忽略憑證。若使用自己的自簽憑證，先確認主機，再決定是否採首次信任或固定指紋。

**完成條件：**儲存後從首頁連上自己的設備，看到畫面／終端並測試輸入。新增一個項目不代表遠端連線已成功。

## 9 選用：安裝本專案主題與中文補充

原生登入與遠端連線都成功後，先結束測試中的遠端工作階段，再在新 VM 的一般使用者工作目錄執行：

```bash
git clone https://github.com/rutp6vmp/guacamole-theme-manager.git
cd guacamole-theme-manager
python3 scripts/build.py
(cd dist && sha256sum -c SHA256SUMS)
sudo sh scripts/install.sh
```

接著仍在 guacamole-theme-manager 專案目錄執行：

```bash
sudo install -m 0644 dist/guacamole-jdbc-zh-tw-1.0.0.jar /opt/guacamole/custom/extensions/
```
```bash
sudo guac-theme configure \
  --extensions-dir /opt/guacamole/custom/extensions \
  --compose-file /opt/guacamole/compose.yaml \
  --project-name guac-new-vm \
  --service guacamole \
  --web-url http://127.0.0.1:8080/guacamole/ \
  --timeout 120
sudo guac-theme doctor
sudo guac-theme import dist/guac-theme-librenms-1.1.0.zip
sudo guac-theme import dist/guac-theme-dark-1.1.0.zip
sudo guac-theme switch librenms
sudo guac-theme doctor
```

啟用時輸入 TRUST 及 YES，確認信任主題並接受重建 Web；會中斷當下 Web 工作階段。重新登入或按 Ctrl+Shift+R 載入新介面。

- install.sh 只安裝管理 CLI，不會替代第 1～8 步。
- Git 原始碼沒有預建 dist；build.py 用 Python 產生安裝檔，不需要 Java／Maven／Node。
- 本倉庫提供 GTM 與 JDBC 中文補充，**完整核心 guacamole-zh-tw.jar 需另行提供**；沒有核心繁中時，部分原生文字仍可能是英文。
- 如需完整核心繁中，取得可信且相容 1.6.0 的 JAR 後放入同一 extensions 來源目錄，安排重建 Web。
- 若已裝過此管理工具，先讀 [升級與還原](INSTALL.md)，不要重跑 configure 覆蓋既有管理狀態。

**完成條件：**doctor 通過、首頁看得到主題、原有設備與連線仍可使用。

## 10 正式使用前的設定順序

| 順序 | 配置事項 | 說明 |
|---|---|---|
| 1 | HTTPS 與入口 | 使用自己的網域、憑證及反向代理，確認 WebSocket／長連線可用；初次 SSH 轉送不等於正式外部入口 |
| 2 | 帳號與權限 | 建立各自的管理員及操作帳號，只授予需要的設備權限 |
| 3 | 備份 | 備份資料庫、私有 .env、Compose 與需要的擴充；管理工具的主題備份不能取代資料庫備份 |
| 4 | 錄影與遠端儲存 | 另配置 guacd 可寫、Web 可讀的共享儲存及回放模組，實際錄製並回放驗證 |
| 5 | MFA 與外包存取 | 依登入來源與外部接入需求另行配置及驗收 |

[官方 HTTPS／反向代理說明](https://guacamole.apache.org/doc/1.6.0/gug/reverse-proxy.html) · [官方錄影與回放說明](https://guacamole.apache.org/doc/1.6.0/gug/recording-playback.html)

本頁完成核心安裝與可選主題流程；不會自動啟用錄影、NAS、MFA 或本專案的 PAM 試驗模組。其他環境的帳密、設備與網路設定也不會跟著 Git 下載。

## 常見問題對照

| 現象 | 優先核對 |
|---|---|
| Web 開不了 | 容器狀態、PostgreSQL 健康檢查、初始化 SQL、SSH 轉送是否仍開啟 |
| 顯示伺服器內部錯誤 | 先看 Web 與 guacd 日誌，確認 guacd 覆寫埠沒有填 0 |
| 自己的電腦能 RDP，Guacamole 不行 | guacd 對該目標的 DNS、路由、防火牆及實際連接埠；同網路可能需用內網位址 |
| Windows 驗證失敗 | Windows 帳號、密碼、網域／電腦名稱及帳號狀態；不要反覆用錯密碼重試 |
| 原始碼沒有 dist ZIP | 先執行 python3 scripts/build.py |
| 配置工具拒絕執行 | 是否對既有部署重跑初始化、漏掉 Compose overlay，或已有未完成交易 |
| 有歷史紀錄但看不到錄影 | 歷史紀錄不等於錄影；需另設定路徑、權限、回放模組並產生錄影檔 |

## 驗證範圍

Compose、隨機私有密碼、官方 SQL、Web readiness、初始管理員登入及 CLI／主題流程沿用 [TXT 教學中的已驗證範本與紀錄](NEW_VM_INSTALL.zh-TW.txt)。本頁把原生 Guacamole 安裝與可選主題分開排列。

本次另核對步驟依賴、程式區塊語法與連結；Ubuntu apt／systemd 安裝尚未在全新 OS VM 實跑。自己的 RDP／SSH 目標、HTTPS、完整核心繁中、錄影及 MFA 仍須依實際部署驗收。本文沒有帶入使用者的實際設定或秘密。
