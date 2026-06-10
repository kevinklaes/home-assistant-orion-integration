# Networking Guide — Redirecting Orion Traffic to the Local Server

This guide explains how to make both the **Home Assistant integration** and, optionally, the **physical Orion device** connect to the locally-hosted server instead of Orion's cloud at `api1.orionbed.com`.

---

## Overview of the challenge

The Orion device and the HA integration both connect to:

| Service | Real endpoint |
|---------|---------------|
| REST API | `https://api1.orionbed.com` (port 443) |
| WebSocket | `wss://live.api1.orionbed.com` (port 443) |

To redirect traffic you need to solve **two problems**:

1. **DNS** — Make those hostnames resolve to your local server's IP instead of Orion's servers.
2. **TLS** — The connections use HTTPS/WSS. Your local server needs a certificate that the client (HA, or the device) will accept.

---

## Step 0 — Generate TLS certificates

Run this once before starting the server:

```bash
python setup_certs.py --out-dir certs
```

This produces:
- `certs/ca.crt` — your local root CA (needs to be trusted by clients)
- `certs/server.crt` / `certs/server.key` — the server certificate

---

## Option A — HA integration only (no device changes)

The simplest path: only the HA integration is redirected. The physical device still talks to Orion's real cloud; the integration gets state from your local server (initially showing mock/default values).

### 1. Edit the integration's `const.py`

Change the two URL constants to point to your local server. If running on the same machine as HA (port 8080, no TLS for simplicity):

```python
# custom_components/orion_sleep/const.py
API_BASE_URL = "http://192.168.1.100:8080"   # your local server IP:port
WS_BASE_URL  = "ws://192.168.1.100:8080"
```

If using HTTPS (port 443):
```python
API_BASE_URL = "https://api1.orionbed.com"   # DNS points here locally
WS_BASE_URL  = "wss://live.api1.orionbed.com"
```
…and use the DNS methods below + install `certs/ca.crt` on the HA machine.

### 2. Trust the CA on the HA machine (HTTPS only)

```bash
sudo cp certs/ca.crt /usr/local/share/ca-certificates/orion-local-ca.crt
sudo update-ca-certificates
```

Then restart the HA integration.

### 3. Start the local server

```bash
ORION_TLS=0 ORION_PORT=8080 ORION_DEVICE_SERIALS=YOUR_SERIAL python run_local_server.py
```

---

## Option B — Full DNS redirect (HA + physical device)

Route all traffic from **both** the HA machine and the Orion device to the local server.

### B1 — Pi-hole (most common for home automation)

In the Pi-hole admin panel → **Local DNS Records**, add:

```
api1.orionbed.com        → 192.168.1.100
live.api1.orionbed.com   → 192.168.1.100
```

Replace `192.168.1.100` with the IP of the machine running `run_local_server.py`.

### B2 — AdGuard Home

**Filters → DNS rewrites**, add:

```
Domain                      Answer
api1.orionbed.com           192.168.1.100
live.api1.orionbed.com      192.168.1.100
```

### B3 — dnsmasq (OpenWrt / pfSense / any Linux router)

Add to `/etc/dnsmasq.conf` (or a file in `/etc/dnsmasq.d/`):

```
address=/api1.orionbed.com/192.168.1.100
address=/live.api1.orionbed.com/192.168.1.100
```

Then restart dnsmasq:
```bash
service dnsmasq restart
```

### B4 — `/etc/hosts` (HA machine only, quick test)

Edit `/etc/hosts` on the HA host:
```
192.168.1.100  api1.orionbed.com
192.168.1.100  live.api1.orionbed.com
```

> This only affects the machine whose hosts file you edit. The physical device won't be redirected this way.

### B5 — iptables DNAT (router / gateway)

If you control the router and can't use DNS, redirect port-443 traffic destined for Orion's IP ranges using DNAT. First find Orion's IPs:

```bash
dig +short api1.orionbed.com
```

Then on the gateway (replace `1.2.3.4` with Orion's IP and `192.168.1.100` with yours):

```bash
# Redirect TCP/443 aimed at the real Orion server to the local server
iptables -t nat -A PREROUTING -p tcp -d 1.2.3.4 --dport 443 \
    -j DNAT --to-destination 192.168.1.100:443

# Also redirect for the HA machine's outbound traffic
iptables -t nat -A OUTPUT -p tcp -d 1.2.3.4 --dport 443 \
    -j DNAT --to-destination 192.168.1.100:443
```

> IP-based DNAT is brittle if Orion's IP changes. DNS override is preferred.

---

## TLS — Making the device trust your certificate

This is the hardest part. The Orion device (OSCT001-1) uses HTTPS, so it validates the server's TLS certificate. There are several scenarios:

### Scenario 1 — Device does standard TLS (no pinning)

If the device only checks that the certificate is valid and issued by a trusted CA, you can install your local CA (`certs/ca.crt`) into the device's trust store.

The device likely runs embedded Linux or Android. Without shell access this is difficult. Possible approaches:
- Find a firmware update mechanism that lets you push a CA cert
- Check if the device exposes an admin web UI that allows cert upload
- Extract and repack the firmware (advanced)

### Scenario 2 — Device does certificate pinning

If the firmware has the real Orion certificate or public key hardcoded, none of the DNS tricks will work without modifying the firmware binary.

To detect pinning: set up a MITM proxy (see Option C below) and watch whether the device drops the connection immediately after the TLS handshake.

### Scenario 3 — Downgrade to HTTP (last resort)

Some IoT devices support an HTTP fallback. You could:
1. Configure the local server without TLS (`ORION_TLS=0`)
2. Use iptables to redirect port 80 traffic from the device to the local server
3. Additionally use iptables to drop the device's port-443 connection to force an HTTP fallback

This only works if the device actually falls back to HTTP.

---

## Option C — mitmproxy (protocol capture first)

Before building a full replacement, capture exactly what the physical device sends to the server. This lets you understand the device-to-cloud protocol and build a proper replacement.

### Setup

```bash
pip install mitmproxy
```

### Transparent proxy mode

On a Linux machine sitting between the device and the internet (or on the router):

```bash
# Enable IP forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward

# Redirect Orion traffic through mitmproxy
iptables -t nat -A PREROUTING -p tcp -d api1.orionbed.com --dport 443 -j REDIRECT --to-port 8080
iptables -t nat -A PREROUTING -p tcp -d live.api1.orionbed.com --dport 443 -j REDIRECT --to-port 8080

# Start mitmproxy in transparent mode
mitmproxy --mode transparent --listen-port 8080
```

### Install mitmproxy's CA on the device

mitmproxy generates its own CA at `~/.mitmproxy/mitmproxy-ca-cert.pem`. Install this as a trusted root on the device (same challenge as Scenario 1 above).

### What to look for in captured traffic

Once you can see the device's requests, capture and document:
- How the device authenticates (device serial + shared secret? client certificate?)
- How the device sends sensor readings (WebSocket? MQTT? periodic HTTP POST?)
- What the server sends to the device (commands, schedules)
- The exact request/response schemas

That information then feeds back into `local_server/app.py` to implement real device support.

---

## Starting the server on port 443

Port 443 requires root (or `CAP_NET_BIND_SERVICE`) on Linux:

```bash
# Option 1: Run as root (simplest)
sudo ORION_DEVICE_SERIALS=ABC123 python run_local_server.py

# Option 2: Grant the Python binary the capability (no persistent root)
sudo setcap 'cap_net_bind_service=+ep' $(which python3)
ORION_DEVICE_SERIALS=ABC123 python run_local_server.py

# Option 3: Run on a high port and use iptables to redirect 443 → 8443
ORION_PORT=8443 ORION_DEVICE_SERIALS=ABC123 python run_local_server.py
sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 8443
sudo iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port 8443
```

---

## Verifying the setup

### Test REST (HA integration perspective)

```bash
# Request a verification code (prints to server stdout)
curl -sk https://api1.orionbed.com/v1/auth/code \
  -X POST -H "Content-Type: application/json" \
  -d '{"email":"test@example.com"}'

# Verify the code (printed in server logs)
curl -sk https://api1.orionbed.com/v1/auth/do \
  -X POST -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","code":"123456"}'
```

### Test WebSocket

```bash
# Install websocat: cargo install websocat  OR  apt install websocat
TOKEN="<access_token from above>"
SERIAL="<your device serial>"
websocat "wss://live.api1.orionbed.com/device/${SERIAL}?token=${TOKEN}"
```

You should immediately receive a `live_device.snapshot` JSON frame.

### Test admin endpoint (register a device)

```bash
curl -sk http://localhost:8080/admin/devices \
  -X POST -H "Content-Type: application/json" \
  -d '{"serial_number":"ABC123","name":"My Bed"}'
```

### Inject fake sensor data (test HA sensors without a real device)

```bash
SERIAL="ABC123"
curl -sk http://localhost:8080/admin/devices/${SERIAL}/sensors \
  -X PUT -H "Content-Type: application/json" \
  -d '{
    "sensor1": {"heart_rate": 62, "breath_rate": 14, "status_text": "normal"},
    "sensor2": {"heart_rate": 58, "breath_rate": 13, "status_text": "normal"}
  }'
```

---

## Summary of current limitations

| Feature | Status |
|---------|--------|
| HA integration auth | ✅ Works (code printed to console) |
| HA device list | ✅ Works (pre-registered via env var) |
| HA live state / WebSocket | ✅ Works (mock state, push every 2s) |
| HA power / temperature control | ✅ Works (state stored in memory) |
| HA sleep schedules | ✅ Works |
| Sleep insights / history | ⚠️ Returns empty (needs real device data) |
| Physical device connection | ❓ Unknown device-to-cloud protocol |
| Real sensor data from device | ❓ Requires protocol capture first |
| Persisted state across restarts | ❌ In-memory only (add JSON file persistence if needed) |
