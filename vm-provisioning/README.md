# Google Antigravity — Unified GCP Client VM Provisioning Toolkit (Linux & Windows)

Modular, block-documented Google Compute Engine (GCE) provisioning and teardown suite for deploying **100% Vanilla Google Antigravity** developer workstations on **Ubuntu 22.04 LTS (`linux`)** and **Windows Server 2022 Datacenter (`windows`)**.

Every provisioned VM automatically installs all three official Antigravity surfaces during first boot without pre-applying MDM locks:
1. **Antigravity CLI (`agy` / `agy.exe`)**
2. **Antigravity Desktop Application** (+ **Browser Web UI** on `:4400` via Nginx WebSocket Connect-RPC multiplexing on Linux)
3. **Microsoft Visual Studio Code** + **Official Google Antigravity Extension (`Google.google-antigravity`)** pre-seeded for both existing and future SSH/RDP users

---

## 1. Application Architecture

```text
+---------------------------------------------------------------------------------------------------+
| Operator Workstation / Cloud Shell                                                                |
|   ./install.sh / ./uninstall.sh  -->  common/gcp_vm_lib.sh  <--  settings.env (+ optional .env)   |
+-------------------------------------------------|-------------------------------------------------+
                                                  | gcloud compute (Shielded VM + VPC + Firewall)
                                                  v
+---------------------------------------------------------------------------------------------------+
| Google Cloud Platform Project (Selected interactively via `gcloud projects list`)                 |
|                                                                                                   |
|  Shared VPC Network + Tag-Scoped Firewall (`antigravity-client-vms-allow-access`)                 |
|  Target Tag: `antigravity-client-vm` | Allowed Ingress: TCP 22 (SSH), 3389 (RDP), 4400 (Web UI)   |
|                                                                                                   |
|  +----------------------------------------------+ +---------------------------------------------+ |
|  | Linux GCE VM (`antigravity-linux-vm`)        | | Windows GCE VM (`antigravity-windows-vm`)   | |
|  | Ubuntu 22.04 LTS | Shielded | e2-standard-4  | | Windows Server 2022 | Shielded | e2-std-4   | |
|  | Startup: `linux/startup_linux.sh`            | | Startup: `windows/startup_windows.ps1`      | |
|  |                                              | |                                             | |
|  | - XFCE4 + xrdp (:3389) + Chrome              | | - Machine PATH + Defender Rule (:4400)      | |
|  | - `/usr/local/bin/agy`                       | | - `C:\Program Files\Antigravity\bin\agy.exe`| |
|  | - `/opt/antigravity-app` (`antigravity-      | |   (SHA-512 verified against release JSON)   | |
|  |   desktop` + `.desktop` launcher)            | | - `C:\AntigravitySetup\Antigravity-x64.exe` | |
|  | - `/usr/bin/code` (debconf pre-seeded) +     | |   + `HKLM\...\Run` per-user RDP logon hook  | |
|  |   `Google.google-antigravity` in `/etc/skel` | | - `C:\Program Files\Microsoft VS Code` +    | |
|  |   and `/etc/profile.d/` for OS Login users   | |   `Google.google-antigravity` seeded in     | |
|  | - Nginx `:4400 -> 127.0.0.1:4401` WebSocket  | |   `C:\Users\Default\.vscode\extensions`     | |
|  |   Connect-RPC multiplexer (`useWebSocket`)   | |   and all existing `C:\Users\*` profiles    | |
|  | - `antigravity-login` & `antigravity-web`    | | - Idempotency marker (`antigravity-install  | |
|  | - Idempotency marker (`.done`)               | |   .done`) + Serial Port 1 structured logs   | |
|  +----------------------------------------------+ +---------------------------------------------+ |
+---------------------------------------------------------------------------------------------------+
```

### Key Architectural Highlights
- **DRY Shared Provisioning Engine (`common/gcp_vm_lib.sh`)**: Centralizes configuration loading, semantic logging, interactive `gcloud projects list` selection, region/zone normalization (`europe-west1` $\rightarrow$ `europe-west1-b`), VPC/subnet discovery, Shielded VM creation, and **reference-counted network teardown** (the shared firewall rule and auto-created subnet are preserved if a sibling `antigravity-client-vm` instance is still active).
- **Extracted Block-Documented Startup Scripts**: Instead of embedding hundreds of lines of inline heredoc code inside provisioning wrappers, first-boot guest setup lives cleanly in [`linux/startup_linux.sh`](./linux/startup_linux.sh) and [`windows/startup_windows.ps1`](./windows/startup_windows.ps1).
- **WebSocket Connect-RPC Multiplexing (`:4400`)**: On Linux, Nginx injects `useWebSocket="true"` into `<head>` so `agy --hub` multiplexes all streaming Connect-RPC channels over `/connect-websocket`, preventing Chromium's 6-connection-per-origin HTTP/1.1 stall.
- **Headless Remote OAuth Helper (`antigravity-login`)**: Uses `AGY_CLI_CDE_AUTH_ACTION=login` (`https://antigravity.google/oauth-callback`) and mirrors `~/.gemini/jetski-standalone-oauth-token` to `~/.gemini/antigravity-cli/antigravity-oauth-token` so headless SSH users never hang on `localhost` browser redirects.

---

## 2. Project Directory Structure

```text
vm-provisioning/
├── README.md                        # Architectural overview, configuration reference & cloud playbooks
├── VM_PROVISIONING_GUIDE.md         # Quick-reference SSH, RDP, Web UI (:4400), and teardown cheatsheet
├── settings.env                     # Tracked default settings (zero secrets or hardcoded project IDs)
├── .env.example                     # Optional local workstation override template (copy to git-ignored .env)
├── .gitignore                       # Blocks .env*, .rdp, SSH keys, credentials, and OS/IDE noise
├── install.sh                       # Unified interactive/automated VM installer (both | linux | windows)
├── uninstall.sh                     # Unified reference-safe VM uninstaller (both | linux | windows)
├── common/
│   └── gcp_vm_lib.sh                # Shared 6-block Bash library (settings, logging, project picker, GCE/VPC)
├── linux/
│   ├── startup_linux.sh             # Standalone 6-block Ubuntu 22.04 GCE startup script
│   ├── provision_linux_vm.sh        # Standalone or orchestrated Linux VM provisioner
│   └── deprovision_linux_vm.sh      # Standalone or orchestrated Linux VM deprovisioner
└── windows/
    ├── startup_windows.ps1          # Standalone 6-block Windows Server 2022 GCE PowerShell startup script
    ├── provision_windows_vm.sh      # Standalone or orchestrated Windows VM provisioner
    └── deprovision_windows_vm.sh    # Standalone or orchestrated Windows VM deprovisioner
```

---

## 3. Frameworks & Libraries

| Component | Version / Image Family | Responsibility |
| :--- | :--- | :--- |
| **Google Cloud SDK (`gcloud`)** | Latest | Authenticates operator, lists active GCP projects, enables `compute.googleapis.com`, and manages Shielded GCE VMs, VPC subnets, and firewall rules. |
| **Ubuntu 22.04 LTS (`ubuntu-os-cloud`)** | `ubuntu-2204-lts` (x86_64) | Base OS image for the Linux client workstation VM (`antigravity-linux-vm`). |
| **XFCE4 + xrdp + Nginx** | Ubuntu Apt Stable | Provides lightweight RDP desktop (`TCP:3389`) and reverse-proxied WebSocket Web UI (`TCP:4400`). |
| **Windows Server 2022 Datacenter** | `windows-2022` (`windows-cloud`) | Base OS image with Desktop Experience & RDP (`TCP:3389`) for `antigravity-windows-vm`. |
| **Google Antigravity CLI (`agy`)** | `1.4.8+` (Vanilla) | Installed at `/usr/local/bin/agy` (Linux) and `C:\Program Files\Antigravity\bin\agy.exe` (Windows, SHA-512 verified). |
| **Google Antigravity Desktop App** | `2.26.0+` (Vanilla) | Extracted to `/opt/antigravity-app` on Linux; staged & registered via `HKLM\...\Run` on Windows. |
| **Microsoft Visual Studio Code + Plugin** | `1.143.1+` + `Google.google-antigravity` (`1.5.0+`) | System-wide VS Code pre-seeded with the official Antigravity VSIX across `/etc/skel`, `/etc/profile.d`, and `C:\Users\Default`. |

---

## 4. Environment Variables

All scripts enforce the **No Hardcoding Rule**: [`settings.env`](./settings.env) holds safe non-secret defaults (`PROJECT_ID=""`), while optional workstation-specific overrides can be placed in a git-ignored `.env` file copied from [`.env.example`](./.env.example).

| Variable | Type | Default (`settings.env`) | Purpose & Example Value |
| :--- | :--- | :--- | :--- |
| `PROJECT_ID` | `string` | `""` (interactive picker) | Target Google Cloud Project ID (e.g., `my-gcp-project`). Prompts via `gcloud projects list` if empty. |
| `TARGET_OS` | `string` | `both` | Operating system target for `install.sh` / `uninstall.sh` (`both`, `linux`, or `windows`). |
| `REGION` | `string` | `europe-west1` | Compute Engine region used for VPC subnet resolution. |
| `ZONE` | `string` | `europe-west1-b` | Compute Engine availability zone hosting the VM(s). |
| `LINUX_VM_NAME` | `string` | `antigravity-linux-vm` | GCE instance name for the Ubuntu 22.04 LTS VM. |
| `LINUX_MACHINE_TYPE` | `string` | `e2-standard-4` | GCE machine type for the Linux VM (`4 vCPU, 16 GB RAM`). |
| `LINUX_DISK_SIZE` | `string` | `50GB` | Boot disk capacity for the Linux VM. |
| `LINUX_DISK_TYPE` | `string` | `pd-balanced` | Persistent disk storage class (`pd-balanced` or `pd-ssd`). |
| `LINUX_IMAGE_FAMILY` | `string` | `ubuntu-2204-lts` | GCE Ubuntu LTS image family in `ubuntu-os-cloud`. |
| `WINDOWS_VM_NAME` | `string` | `antigravity-windows-vm` | GCE instance name for the Windows Server 2022 VM. |
| `WINDOWS_MACHINE_TYPE` | `string` | `e2-standard-4` | GCE machine type for the Windows VM (`4 vCPU, 16 GB RAM`). |
| `WINDOWS_DISK_SIZE` | `string` | `60GB` | Boot disk capacity for Windows Server 2022 (`>= 50GB` required). |
| `WINDOWS_DISK_TYPE` | `string` | `pd-balanced` | Persistent disk storage class (`pd-balanced` or `pd-ssd`). |
| `WINDOWS_IMAGE_FAMILY` | `string` | `windows-2022` | GCE Windows Server image family in `windows-cloud`. |
| `WINDOWS_ADMIN_USER` | `string` | `agyadmin` | Administrator username suggested for `gcloud compute reset-windows-password`. |
| `NETWORK_TAG` | `string` | `antigravity-client-vm` | Shared GCE network tag binding client VMs to the ingress firewall rule. |
| `FIREWALL_RULE` | `string` | `antigravity-client-vms-allow-access` | VPC firewall rule allowing `tcp:22,tcp:3389,tcp:4400` to `NETWORK_TAG`. |
| `HUB_WEB_PORT` | `string` | `4400` | Public port exposed for the Antigravity Browser Web UI (`antigravity-web`). |
| `AUTO_RECREATE` | `boolean` | `false` | When `true`, deletes and recreates existing VMs automatically without prompting. |
| `AUTO_APPROVE` | `boolean` | `false` | When `true`, skips interactive confirmation prompts during teardown. |

---

## 5. Local Execution Instructions

### Step 1: Authenticate `gcloud` & Optional `.env` Setup
```bash
gcloud auth login

cd vm-provisioning
# Optional: create a local git-ignored .env override file
cp .env.example .env
```

### Step 2: Run the Unified Interactive Installer
```bash
./install.sh
```
1. Select your target Google Cloud Project from the numbered list returned by `gcloud projects list`.
2. Press **Enter** to accept the [`settings.env`](./settings.env) defaults (`both` Linux and Windows in `europe-west1-b`), or type **`c`** to customize the target OS (`linux`, `windows`, or `both`), region/zone, VM names, or machine types interactively.

*(You can also run single-OS scripts directly at any time via [`./linux/provision_linux_vm.sh`](./linux/provision_linux_vm.sh) or [`./windows/provision_windows_vm.sh`](./windows/provision_windows_vm.sh).)*

### Step 3: Connect & Verify Installed Surfaces
- **Linux VM (`antigravity-linux-vm`)**:
  ```bash
  gcloud compute ssh "antigravity-linux-vm" --zone="europe-west1-b" --project="<YOUR_GCP_PROJECT_ID>"
  # Inside the VM:
  agy --version
  code --list-extensions --show-versions
  antigravity-web   # Starts Browser Web UI on port 4400
  ```
- **Windows VM (`antigravity-windows-vm`)**:
  ```bash
  gcloud compute reset-windows-password "antigravity-windows-vm" \
    --zone="europe-west1-b" \
    --project="<YOUR_GCP_PROJECT_ID>" \
    --user="agyadmin" \
    --quiet
  ```
  Connect via Microsoft Remote Desktop / Remmina / IAP tunnel (`tcp:3389`), open PowerShell, and run `agy --version` and `code --list-extensions --show-versions`.

### Step 4: Tear Down VMs Cleanly
```bash
./uninstall.sh
```

---

## 6. Cloud Deployment Playbooks (Google Cloud Run & GKE Gateway Integration)

Although these VMs boot in **100% Vanilla Antigravity mode** (interactive Google OAuth with zero gateway locks), they are designed to pair seamlessly with the companion **Antigravity Enterprise Gateway** in [`../enterprise-gateway/`](../enterprise-gateway/) hosted on **Google Cloud Run** or **Google Kubernetes Engine (GKE)**.

### Playbook A: Deploy Companion Enterprise Gateway on Google Cloud Run

1. Deploy the unified Enterprise Gateway (+ Model Armor & Cloud SDP) from [`../enterprise-gateway/`](../enterprise-gateway/):
   ```bash
   cd ../enterprise-gateway
   ./install.sh --runtime=python --region="europe-west1"
   ```
2. Connect from your provisioned Linux or Windows GCE VM using Tier-2 environment variables (or push `admin_settings.local.json` to `/etc/antigravity/admin_settings.json` / `%ProgramData%\Antigravity\admin_settings.json`):
   ```bash
   export AGY_LLM_GATEWAY_URL="https://<CLOUD_RUN_GATEWAY_URL>"
   export AGY_LLM_GATEWAY_API_KEY="<GATEWAY_API_KEY>"
   agy -p "Confirm connectivity through the Cloud Run Enterprise Gateway."
   ```

### Playbook B: Deploy Companion Enterprise Gateway on Google Kubernetes Engine (GKE)

1. Build and push the Gateway container image to Artifact Registry, then apply the production GKE manifest in [`../enterprise-gateway/k8s/deployment.yaml`](../enterprise-gateway/k8s/deployment.yaml) (configured with `BackendConfig.spec.timeoutSec: 3600` for 60-minute unbuffered SSE streaming and Workload Identity):
   ```bash
   cd ../enterprise-gateway

   export PROJECT_ID="<YOUR_GCP_PROJECT_ID>"
   export REGION="europe-west1"

   gcloud builds submit ./python \
     --project="${PROJECT_ID}" \
     --tag="${REGION}-docker.pkg.dev/${PROJECT_ID}/antigravity/enterprise-gateway:latest"

   kubectl create namespace antigravity --dry-run=client -o yaml | kubectl apply -f -
   kubectl -n antigravity create secret generic antigravity-gateway-secrets \
     --from-literal=GATEWAY_API_KEY="$(openssl rand -base64 32 | tr -d '\n')" \
     --dry-run=client -o yaml | kubectl apply -f -

   sed -e "s|REPLACE_WITH_PROJECT_ID|${PROJECT_ID}|g" \
       -e "s|europe-west1|${REGION}|g" \
       k8s/deployment.yaml | kubectl apply -f -
   ```
2. Point the provisioned GCE Linux/Windows client VMs inside the same VPC to the internal or external GKE Gateway LoadBalancer URL via `AGY_LLM_GATEWAY_URL` or Tier-1 MDM `admin_settings.json`.
