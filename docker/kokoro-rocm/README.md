# Kokoro TTS – ROCm Docker Setup

This directory contains everything needed to run [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) with **AMD GPU (ROCm)** acceleration in Docker.

The resulting server exposes an OpenAI-compatible TTS API on port `8880` that the **Kokoro TTS** Home Assistant integration connects to.

---

## Requirements

### Host OS
- Linux (Ubuntu 22.04 / 24.04 recommended) or Windows with WSL 2
- ROCm-compatible AMD GPU: RX 6000, RX 7000, RX 9000, Instinct series

### ROCm Drivers
Install the ROCm stack on the host **before** running Docker:

```bash
# Ubuntu 22.04 / 24.04 – quick install
wget https://repo.radeon.com/amdgpu-install/6.4.4/ubuntu/jammy/amdgpu-install_6.4.4.60404-1_all.deb
sudo apt install ./amdgpu-install_6.4.4.60404-1_all.deb
sudo amdgpu-install --usecase=rocm
sudo reboot

# Add your user to the required groups
sudo usermod -aG render,video $USER
newgrp render
```

Verify ROCm is working:
```bash
rocminfo | grep "Agent 2"   # should show your GPU
```

### Docker
```bash
# Install Docker Engine (not Docker Desktop)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

---

## Quick Start

```bash
# 1. Clone this repo (or navigate here if already cloned)
cd docker/kokoro-rocm

# 2. Run setup (clones Kokoro-FastAPI source, builds image, starts container)
bash setup.sh

# 3. Watch logs until model downloads and server is ready (~2 min first time)
docker compose logs -f kokoro-tts
```

The server is ready when you see:
```
Application startup complete.
```

Verify it works:
```bash
curl http://localhost:8880/v1/audio/voices
```

---

## Persistent Data

| Path | Contents |
|------|----------|
| `data/models/` | Downloaded Kokoro model weights (~326 MB) – preserved across container rebuilds |
| `data/miopen-config/` | MIOpen kernel shape config (RDNA 2 tuning) |
| `data/miopen-cache/` | MIOpen kernel shape cache |

---

## RDNA 2 Performance Tuning (RX 6000 series)

RDNA 2 GPUs (RX 6600–6950 XT) require a one-time MIOpen warm-up to build kernel shape files. Without this, the first few requests will be slow.

**Step 1** – Enable tuning mode in `docker-compose.yml`:
```yaml
environment:
  - MIOPEN_FIND_MODE=3
  - MIOPEN_FIND_ENFORCE=3
```

**Step 2** – Restart and generate several long TTS requests (e.g. first few paragraphs of a book). This may take 10–30 minutes.

**Step 3** – Switch to cached mode:
```yaml
environment:
  - MIOPEN_FIND_MODE=2
  # Remove MIOPEN_FIND_ENFORCE
```

Restart: subsequent runs will be **significantly faster**.

---

## Updating Kokoro-FastAPI

```bash
cd docker/kokoro-rocm
git -C src pull
docker compose up -d --build
```

---

## Connecting to Home Assistant

Two integration options are available:

### Option A – Wyoming integration (recommended)

The stack starts a **Wyoming proxy** on port `10200` that HA auto-discovers.

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Wyoming**
3. Enter the host IP and port `10200`

Home Assistant will see all available Kokoro voices and let you select one per voice assistant pipeline.

Or, if you prefer a manual YAML entry in `configuration.yaml`:
```yaml
wyoming:
  - host: 192.168.1.100
    port: 10200
```

### Option B – Kokoro TTS custom integration (HTTP)

Install the **Kokoro TTS** integration via HACS (Custom repository: `https://github.com/rwfsmith/llm_assistant`) and configure the server URL as:

```
http://<HOST_IP>:8880
```

Where `<HOST_IP>` is the IP address of the machine running Docker. Use `http://localhost:8880` only if HA runs on the same machine.

### Port reference

| Port | Protocol | Service |
|------|----------|---------|
| `8880` | HTTP | Kokoro-FastAPI (OpenAI-compatible TTS API) |
| `10200` | TCP | Wyoming protocol proxy |

---

## Troubleshooting

**Container exits immediately**
- Check `docker compose logs kokoro-tts` for the error
- Ensure `/dev/kfd` and `/dev/dri` exist: `ls -la /dev/kfd /dev/dri`

**No GPU acceleration**
- Run `rocminfo` on the host to verify ROCm is working
- Check group membership: `groups $USER` must include `render` and `video`

**Wrong render GID**
- Find the correct GID: `getent group render | cut -d: -f3`
- Override in `docker-compose.yml` under `group_add` or export before running setup: `export RENDER_GID=110`

**Model not downloading**
- The container needs internet access. Check proxy/firewall settings.
- Models are cached in `./data/models/` – delete to force re-download.
