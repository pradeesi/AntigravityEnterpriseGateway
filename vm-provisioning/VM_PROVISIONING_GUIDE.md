# GCP VM Provisioning & Verification Quick Reference

> **Note:** For full architectural diagrams, directory structure, environment variable reference, and Cloud Run / GKE Enterprise Gateway integration playbooks, see [README.md](./README.md).

---

## 1. Interactive One-Command Provisioning (Recommended)

Lists all accessible Google Cloud projects via `gcloud projects list`, displays defaults from [`settings.env`](./settings.env), and lets you provision `both`, `linux`, or `windows`:

```bash
cd vm-provisioning
./install.sh
```

### Non-Interactive / Single-OS Shortcuts

```bash
# Provision ONLY the Ubuntu 22.04 LTS Linux VM
./install.sh --project="<YOUR_GCP_PROJECT_ID>" --os=linux --non-interactive

# Provision ONLY the Windows Server 2022 VM
./install.sh --project="<YOUR_GCP_PROJECT_ID>" --os=windows --non-interactive

# Provision BOTH Linux and Windows VMs in europe-west1-b
./install.sh --project="<YOUR_GCP_PROJECT_ID>" --os=both --zone="europe-west1-b" --non-interactive
```

---

## 2. Verify Linux VM (`antigravity-linux-vm`)

### A. Check First-Boot Installation Log & Installed Versions via SSH
```bash
gcloud compute ssh "antigravity-linux-vm" \
  --zone="europe-west1-b" \
  --project="<YOUR_GCP_PROJECT_ID>" \
  --command="
    ls -la /var/log/antigravity-install.done &&
    agy --version &&
    /opt/antigravity-app/antigravity --version --no-sandbox &&
    code --version --no-sandbox --user-data-dir=/tmp/vscode-root &&
    code --list-extensions --show-versions --no-sandbox --user-data-dir=/tmp/vscode-root
  "
```

### B. Launch Browser Web UI (`:4400` over Nginx WebSocket Multiplexer)
```bash
gcloud compute ssh "antigravity-linux-vm" \
  --zone="europe-west1-b" \
  --project="<YOUR_GCP_PROJECT_ID>" \
  -- -L 4400:localhost:4400
# Inside VM:
antigravity-web
```

### C. Connect to XFCE4 Graphical Desktop via IAP RDP Tunnel
```bash
gcloud compute start-iap-tunnel "antigravity-linux-vm" 3389 \
  --zone="europe-west1-b" \
  --project="<YOUR_GCP_PROJECT_ID>" \
  --local-host-port=localhost:23389
```

---

## 3. Verify Windows VM (`antigravity-windows-vm`)

### A. Check Startup Installation Progress from Workstation (Serial Port 1)
```bash
gcloud compute instances get-serial-port-output "antigravity-windows-vm" \
  --zone="europe-west1-b" \
  --project="<YOUR_GCP_PROJECT_ID>" \
  --port=1 \
  --quiet | tail -n 35
```

### B. Generate RDP Password & Connect via IAP Tunnel
```bash
gcloud compute reset-windows-password "antigravity-windows-vm" \
  --zone="europe-west1-b" \
  --project="<YOUR_GCP_PROJECT_ID>" \
  --user="agyadmin" \
  --quiet

gcloud compute start-iap-tunnel "antigravity-windows-vm" 3389 \
  --zone="europe-west1-b" \
  --project="<YOUR_GCP_PROJECT_ID>" \
  --local-host-port=localhost:13389
```

### C. Verify Installed Versions Inside Windows PowerShell
```powershell
agy --version
code --version
code --list-extensions --show-versions
Get-Content C:\AntigravitySetup\antigravity-install.log -Tail 30
```

---

## 4. Clean Teardown / Deprovisioning

```bash
# Interactive project & OS selection
./uninstall.sh

# Non-interactive teardown of both VMs + unused shared firewall/subnet
./uninstall.sh --project="<YOUR_GCP_PROJECT_ID>" --os=both --non-interactive --yes
```
