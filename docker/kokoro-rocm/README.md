# Kokoro TTS – ROCm Docker Setup

Runs [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) with **AMD GPU (ROCm)** acceleration in Docker, plus a **Wyoming protocol proxy** so Home Assistant can use it natively for voice pipelines.

## Architecture

> **HAOS and ROCm cannot share the same machine.** HAOS is a locked-down OS with no kernel module support. ROCm's userspace lives entirely inside the container image — the host only needs the `amdgpu`/`amdkfd` kernel modules, which are **upstreamed into the standard Linux kernel** (5.x+). No ROCm host installation is required on modern Linux.

```
Linux host (TrueNAS SCALE, Ubuntu, etc.)         Home Assistant OS
  /dev/kfd  /dev/dri  ↕ kernel modules           VM or separate machine
  ┌─────────────────────────────┐                  ┌──────────────────┐
  │ Docker                      │                  │                  │
  │  kokoro-tts  (port 8880)   │◄── LAN ─────────►│ Wyoming          │
  │  kokoro-wyoming (port 10200)│                  │ integration      │
  └─────────────────────────────┘                  └──────────────────┘
```

## GPU Compatibility

| GPU family | Example cards | Min ROCm | LLVM target |
|------------|---------------|----------|-------------|
| RDNA 2 | RX 6600 – 6950 XT | 5.x | gfx1030 |
| RDNA 3 | RX 7600 – 7900 XTX | 6.x | gfx1100 / gfx1101 |
| RDNA 3.5 / Strix Point | **Ryzen AI 9 HX 370** | **7.1.1** | **gfx1150** |
| RDNA 4 | RX 9070 XT | 7.1.1 | gfx1200 / gfx1201 |
| CDNA (Instinct) | MI100 – MI350 | 5.x | gfx908 / gfx90a / gfx942 |

`setup.sh` defaults to **ROCm 7.2.0** (which covers all rows above). Override with:
```bash
ROCM_VERSION=6.4.4 bash setup.sh   # only if you need the older version for RDNA 2/3
```

---

## Option 1 – TrueNAS SCALE (recommended for HAOS-on-VM setups)

TrueNAS SCALE runs a standard Linux 6.6 kernel, so `/dev/kfd` and `/dev/dri` exist without any extra installation. Docker is available from the TrueNAS shell.

### 1. Verify GPU device nodes

SSH into TrueNAS or open **System → Shell**:

```bash
ls -la /dev/kfd /dev/dri/renderD*
# Both must exist. If /dev/kfd is missing, check the AMD GPU is not
# fully passed-through to a VM (PCIe passthrough removes it from the host).
```

### 2. Create a dataset for app data

In the TrueNAS UI: **Storage → Create Dataset** → e.g. `tank/apps/kokoro`.
This stores model weights and MIOpen cache across container rebuilds.

### 3. Clone and start

```bash
# In TrueNAS shell, navigate to the dataset
cd /mnt/tank/apps/kokoro          # adjust pool/dataset name

# Clone the repo
git clone https://github.com/rwfsmith/llm_assistant .

# Enter the Docker setup directory
cd docker/kokoro-rocm

# Clone Kokoro-FastAPI source (required for the ROCm build)
git clone https://github.com/remsky/Kokoro-FastAPI src

# Detect GPU group IDs and start the stack
export VIDEO_GID=$(getent group video | cut -d: -f3)
export RENDER_GID=$(getent group render | cut -d: -f3)
export KOKORO_DATA_DIR=/mnt/tank/apps/kokoro/docker/kokoro-rocm/data

# Set your GPU's GFX target (setup.sh injects this into the Dockerfile):
#   gfx1150 = Ryzen AI 9 HX 370 / Strix Point (RDNA 3.5)
#   gfx1100 = RX 7900 XTX / 7800 XT (RDNA 3)
#   gfx1030 = RX 6800 XT / 6950 XT (RDNA 2)
export GFX_ARCH=gfx1150

docker compose -f truenas-compose.yml up -d --build
```

First build takes ~10–20 minutes (downloading the ROCm base image + Kokoro deps).

### 4. Watch startup

```bash
docker compose -f truenas-compose.yml logs -f kokoro-tts
```

Ready when you see: `Application startup complete.`

---

## Option 2 – Generic Linux (Ubuntu 22.04 / 24.04)

On a standard Linux desktop/server the ROCm userspace is still in the container, but if you want `rocminfo` and other host-side tools too:

```bash
# Optional: install host ROCm tools
wget https://repo.radeon.com/amdgpu-install/6.4.4/ubuntu/jammy/amdgpu-install_6.4.4.60404-1_all.deb
sudo apt install ./amdgpu-install_6.4.4.60404-1_all.deb
sudo amdgpu-install --usecase=rocm
sudo usermod -aG render,video $USER && newgrp render

# Install Docker Engine
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

Then clone the repo and run the included setup script:

```bash
cd docker/kokoro-rocm
export GFX_ARCH=gfx1150   # set to your GPU's target
bash setup.sh          # clones Kokoro-FastAPI source, patches Dockerfile, starts stack
```

Verify:
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

**`/dev/kfd` does not exist (TrueNAS SCALE)**
The GPU may be fully PCIe-passed-through to a VM, which removes it from the host. To use the GPU for Kokoro while also having HAOS, you have two options:
1. Run Kokoro on a **separate Ubuntu VM** with PCIe passthrough (not HAOS)
2. Use the GPU on the TrueNAS host only — do not pass it through to any VM

**gfx1150 "HIP error: invalid device function" (Ryzen AI 9 HX 370 / Strix Point)**
PyTorch ROCm wheels don't include compiled gfx1150 kernels yet. The compose files set `HSA_OVERRIDE_GFX_VERSION=11.0.0` by default, which tells HIP to use the binary-compatible gfx1100 (RDNA 3) kernels. If you built before this fix, do a full no-cache rebuild:
```bash
docker compose -f truenas-compose.yml build --no-cache kokoro-tts
docker compose -f truenas-compose.yml up -d
```

**Container exits immediately**
- Check logs: `docker compose logs kokoro-tts` (or `docker compose -f truenas-compose.yml logs kokoro-tts`)
- Ensure `/dev/kfd` and `/dev/dri` exist: `ls -la /dev/kfd /dev/dri`

**No GPU acceleration / falls back to CPU**
- Test GPU access: `docker run --rm --device /dev/kfd --device /dev/dri rocm/dev-ubuntu-24.04:6.4.4-complete rocminfo`
- Check group IDs: `getent group render video` — make sure the GIDs match what's in `group_add`

**Wrong render GID**
- Find the correct GID: `getent group render | cut -d: -f3`
- Export before starting: `export RENDER_GID=$(getent group render | cut -d: -f3)`

**TrueNAS: `git` or `docker compose` not found**
- TrueNAS SCALE has both in the default shell. If missing, use the TrueNAS App catalog to install Docker, or SSH in.

**Model not downloading**
- The container needs internet access. Check proxy/firewall settings.
- Models are cached in `data/models/` (or `$KOKORO_DATA_DIR/models/`) — delete to force re-download.
