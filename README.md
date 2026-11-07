# Julklappsspelet – Secret Santa (`santa.ante.pub`) 🎅🎄

En lättviktig, krypterad svensk webbapplikation för familjens julklappslottning (Secret Santa), byggd med **FastAPI + SQLite + `cryptography`** och paketerad för **Docker på Raspberry Pi 5 (`linux/arm64`)**.

---

## 🤖 AI Agent Deployment Guide (Raspberry Pi 5 — `santa.ante.pub`)

> **Instructions for the AI Agent running on the Raspberry Pi 5 server:**
> The user wants to deploy this repository (`https://github.com/antedev/santa`) as a Docker container and expose it at **`https://santa.ante.pub`** using the existing reverse proxy / tunnel setup already running on this Raspberry Pi 5.

### Step 1: Inspect Existing Docker & Reverse Proxy Setup
Before starting the container, check what reverse proxy or tunnel is currently routing `*.ante.pub` domains on the server:
```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Networks}}"
docker network ls
```
Look for whichever proxy/tunnel is active on the Pi:
- **Cloudflare Tunnel (`cloudflared`)**
- **Traefik** (check labels on existing containers with `docker inspect <container>`)
- **Caddy** (check `Caddyfile` mount)
- **Nginx Proxy Manager (NPM)** or **Nginx / SWAG**

### Step 2: Clone and Configure the Repository
Clone the repo into your standard services directory (e.g. `~/santa` or `/opt/santa` or wherever other stacks live):
```bash
git clone https://github.com/antedev/santa.git
cd santa
cp .env.example .env
mkdir -p data
```
- Check if port `8085` is free on the host (`ss -tulpn | grep 8085`). If `8085` is used, change `SANTA_PORT` in `.env` to any free port, or attach `secret-santa` directly to the shared Docker proxy network.
- Optionally set a custom `SECRET_SANTA_ADMIN_PASSWORD` in `.env` (default is `tomten`).

### Step 3: Build & Start the Docker Container
```bash
docker compose up -d --build
```
Verify the container is healthy and responding locally:
```bash
curl -I http://127.0.0.1:8085/api/state
```
*(Should return `HTTP/1.1 200 OK` with JSON).*

### Step 4: Wire `santa.ante.pub` to the Container
Match the pattern used by the other `*.ante.pub` containers on this Raspberry Pi 5:

- **If using Traefik:**
  Attach `secret-santa` to the Traefik external Docker network in `docker-compose.yml` and add labels:
  ```yaml
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.santa.rule=Host(`santa.ante.pub`)"
    - "traefik.http.routers.santa.entrypoints=websecure"
    - "traefik.http.routers.santa.tls.certresolver=letsencrypt" # match existing resolver name
    - "traefik.http.services.santa.loadbalancer.server.port=8080"
  ```
- **If using Caddy:**
  Add to the `Caddyfile` and reload Caddy:
  ```caddyfile
  santa.ante.pub {
      reverse_proxy localhost:8085 # or secret-santa:8080 if on same Docker network
  }
  ```
- **If using Cloudflare Tunnel (`cloudflared`):**
  Point public hostname `santa.ante.pub` to `http://localhost:8085` (or `http://secret-santa:8080` on the shared Docker network).
- **If using Nginx / Nginx Proxy Manager:**
  Add a Proxy Host for `santa.ante.pub` forwarding to `http://<host-ip-or-container>:8085` (or `secret-santa:8080`) with WebSockets/SSL enabled.

### Step 5: Persistence & Backups
- The SQLite database is stored on the host at `./data/secret_santa.db` (mounted to `/app/data/secret_santa.db` in the container).
- The seed configuration is mounted at `./seed.json` (`/app/seed.json` in the container), so clicking **"💾 Spara nuvarande till seed.json"** in the web UI writes directly to `./seed.json` on the host.

---

## 🎄 Hur applikationen fungerar (Användarguide)

### 1. Förbered & Seed (`⚙️ Förbered & Seed`-fliken)
- Standardlösenord för admin är **`tomten`** (eller det du satt i `SECRET_SANTA_ADMIN_PASSWORD`).
- Här lägger du in eller redigerar **vuxna** (som ingår i den hemliga lottningskedjan) och **barn** (som hamnar i Barnens Hörna).
- Lägg in **undantagsregler** (t.ex. par som inte ska dra varandra).
- Klicka på **"🎲 Förgenerera lottningskedja nu"** för att skapa hela kedjan i förväg (`A ➔ B ➔ C ➔ ... ➔ A`, aldrig `A ↔ B`).
- I **Utvecklarläge** visas en tabell längst ner där du kan kontrollera kedjan.
- När du är nöjd klickar du på **"🔒 Lås & Gå Live (Radera admin-insyn)"**. Då raderas utvecklar-tabellen permanent ur databasen så att inte ens du som admin kan se vem som har fått vem!

### 2. Logga in & Dra lott (`🎅 Min Julklappslott`-fliken)
- Deltagarna har **inget förbestämt lösenord**.
- **Första gången** en deltagare klickar på sitt namn väljer personen en egen PIN-kod eller ett lösenord (minst 2 tecken). Detta lösenord krypterar deltagarens lott i databasen (`PBKDF2HMAC` + `Fernet`).
- Deltagaren klickar sedan på **"🎲 Dra min julklappslott!"** – ett lotterihjul snurrar genom namnen och avslöjar vem de ska köpa julklapp till, personens önskelista, samt deltagarens eget hemliga täcknamn (alias).

### 3. Kedjan & Bevis (`🔗 Kedjan & Bevis`-fliken)
- Visar hela den sammanhängande kedjan med deltagarnas hemliga täcknamn (`Täcknamn 1 ➔ Täcknamn 2 ➔ ... ➔ Täcknamn 1`) så att alla kan se att samtliga är med i en enda stor cirkel och vilka täcknamn som har dragit sin lott.

### 4. Barnens Hörna (`👶 Barnens Hörna`-fliken)
- Visar barnens önskelistor utanför vuxenlänken.
- Vem som helst (vuxen eller barn) kan paxa att ge en extra julklapp (anonymt som *"En hemlig tomte 🎅"*, med sitt hemliga täcknamn, eller med sitt riktiga namn).

---

## 💻 Lokal utveckling (Windows 11)

```powershell
.\run_dev.ps1
# Öppna http://localhost:8080
```

Kör de automatiska testerna:
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
