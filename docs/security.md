# Security Considerations

Argus exists to demonstrate a real threat: RTSP cameras left exposed on the open internet can be watched by anyone. This document covers how to secure both your cameras and your Argus deployment.

---

## Securing Your RTSP Cameras

If you operate RTSP cameras, this is the section that matters most. These are not suggestions — they are the minimum required to avoid being the next data point in a Shodan search.

### Change default credentials

`admin:admin` is not a password. It is a standing invitation. Most RTSP cameras ship with well-known defaults that are trivially guessable. Change them before the camera touches any network.

### Disable UPnP

UPnP punches holes in your firewall without asking. It broadcasts camera availability to your entire network and, depending on your router, to the internet. Disable it on both the camera and the router.

### Firewall RTSP ports

Block inbound access to RTSP ports from the internet:

| Port | Protocol | Action |
|---|---|---|
| 554 | TCP | Block inbound |
| 8554 | TCP | Block inbound |
| Any custom RTSP port | TCP | Block inbound |

Use a stateful firewall. Only allow RTSP traffic from known management IPs on a VPN.

### Use VPN for remote access

Never expose RTSP streams directly to the internet. Use a VPN (WireGuard, OpenVPN) for remote camera access. If you must have external access, put it behind a reverse proxy with TLS and authentication.

### Audit your network

Run a port scanner against your own infrastructure. Tools like masscan and nmap will show you what's exposed — before someone else does.

```bash
# Scan your public IP for RTSP
masscan 0.0.0.0/0 -p554,8554 --rate=1000

# Or scan a specific target
nmap -sV -p554,8554 <target-ip>
```

---

## Securing Your Argus Deployment

### Run as non-root

Never run Argus as root. The systemd service file creates a dedicated `argus` user with minimal privileges. If running manually:

```bash
sudo useradd -r -s /usr/sbin/nologin argus
sudo -u argus python main.py
```

### Restrict file permissions

Argus stores sensitive data in four directories. Lock them down.

| Directory | Contains | Recommended Permissions |
|---|---|---|
| `config/` | Camera URLs with credentials (`rtsp://user:pass@host/...`) | `700` — owner read/write only |
| `targets/` | Face reference images (biometric data) | `700` — owner read/write only |
| `screenshots/` | Surveillance footage with bounding boxes | `750` — owner full, group read |
| `logs/` | Detection events with timestamps and identities | `750` — owner full, group read |

```bash
chmod 700 config/ targets/
chmod 750 screenshots/ logs/
chown -R argus:argus config/ targets/ screenshots/ logs/
```

### Camera URLs contain credentials

This is easy to overlook. Your `cameras.toml` likely contains:

```toml
url = "rtsp://admin:s3cret_p4ssw0rd@192.168.1.100:554/stream"
```

That file is plaintext. Anyone with read access to the config directory has your camera passwords. Treat `config/` like you would treat an SSH private key.

**Not yet supported:** Environment variable interpolation in TOML values. The current implementation reads URLs as raw strings. If this is a concern, consider using a secrets manager and templating `cameras.toml` at deploy time.

### Webhook security

Webhooks have known limitations in the current implementation:

| Concern | Status |
|---|---|
| TLS certificate verification | **Not verified** — httpx default allows self-signed certs |
| Authentication tokens | **Not built-in** — must be added via `headers` in `webhooks.toml` |
| Request signing | **Not supported** |
| Rate limiting | **Not implemented** on the receiver side |

If your webhook receiver is on the local network, this is acceptable. If it's remote, add authentication via headers and use TLS.

```toml
[webhooks.secure_server]
enabled = true
url = "https://receiver.example.com/webhook"
method = "POST"
headers = { "Authorization" = "Bearer YOUR_TOKEN_HERE" }
body_template = '{"person": "{name}", "camera": "{camera}"}'
```

---

## Network Security

### Isolate RTSP traffic

RTSP streams should be on a **dedicated VLAN** separate from your management and production networks. Camera traffic is unencrypted — anyone on the same VLAN can capture it.

### Firewall the Argus server

Argus makes **outbound** connections only (RTSP to cameras, HTTP to webhooks). It should never receive inbound connections from the public internet.

| Direction | Port | Action |
|---|---|---|
| Outbound TCP | 554, 8554 (RTSP) | Allow to camera VLAN only |
| Outbound TCP | 80, 443 (webhooks) | Allow to webhook endpoints only |
| Inbound (any) | Any | **Deny all** |

### Remote management

Use SSH with key-based auth. If you need a web interface for management, put it behind a VPN. Never expose Argus management to the internet.

---

## Face Data Privacy

### Biometric data

Target reference images are biometric data. They are 128-dimensional face encodings — mathematical representations of facial geometry. In many jurisdictions, biometric data is subject to strict regulations.

### GDPR and privacy laws

If you are deploying Argus in the EU, UK, or other jurisdictions with biometric data regulations:

- **Legal basis required** — You need a lawful reason to collect and process biometric data. Surveillance without consent may require a legitimate interest assessment or explicit authorization.
- **Data protection impact assessment** — May be required for systematic surveillance.
- **Right to erasure** — Subjects may request deletion of their face data.
- **Data minimization** — Only collect what you need. Don't add entire populations to the target database.

Consult a lawyer. The authors are not one.

### Screenshot retention

Screenshots contain identifiable individuals with bounding boxes and names. They are surveillance evidence. Set a retention policy and enforce it:

- Configure the cooldown to reduce screenshot volume
- Implement automated cleanup (cron job or application-level TTL)
- Consider whether screenshots need encryption at rest

---

## Ethical Use

This is a **security research and awareness tool**. That is its purpose, stated clearly in the README and reinforced by the GPL-3.0 license.

The uncomfortable truth: tens of thousands of RTSP cameras are exposed on the public internet right now — default credentials, no authentication, no encryption. If your camera is accessible, someone could already be doing exactly what Argus does. The only difference is you wouldn't know about it.

**This project exists to make that threat tangible.**

- The authors assume no responsibility for misuse.
- Users are responsible for ensuring compliance with all applicable laws.
- Use Argus to audit your own infrastructure, secure your own cameras, and understand the real-world threat landscape.

If you are using Argus to monitor cameras you do not own or operate, without authorization, that is on you. Not on the tool.

---

## Why GPL-3.0 and Not MIT or Apache

This was a deliberate choice. Not a default.

### The problem with permissive licenses

MIT and Apache 2.0 let anyone do anything with your code — including taking it, closing the source, and selling it as a proprietary surveillance product. For most software, that's fine. For a tool that demonstrates mass surveillance capabilities, it's dangerous.

If Argus were MIT-licensed, someone could:
1. Fork it
2. Remove the security disclaimer
3. Remove the ethical use warnings
4. Add a polished UI
5. Sell it as a "loss prevention" or "personnel monitoring" tool
6. Never acknowledge the original project or its security research purpose

The code would be identical. The intent would be erased. The people being watched would never know the tool they're subjected to was built to demonstrate *why they should be protected*.

### What GPL-3.0 actually does

The GNU General Public License v3.0 is a **copyleft** license. It guarantees four things that matter for a project like this:

| Protection | What It Means |
|---|---|
| **Source availability** | Anyone who distributes Argus or a derivative work *must* provide the source code. No black boxes. No hidden modifications. |
| **Same-license propagation** | Derivative works must also be GPL-3.0. You can't take Argus, modify it, and release it under a proprietary license. The copyleft chain is unbroken. |
| **Patent protection** | Contributors grant explicit patent rights. If someone contributes code covered by a patent, they can't later sue users for patent infringement. Apache 2.0 also has this; MIT does not. |
| **Anti-tivoization** | If Argus is deployed on hardware that uses locked-down firmware (like many IoT devices), GPL-3.0 requires that users can still modify and run the software. This prevents hardware manufacturers from using Argus in locked surveillance appliances that owners can't audit. |

### How GPL-3.0 protects "shadow-users"

The people being watched by Argus — the faces in the frame, the targets in the database, the individuals captured on RTSP streams — never consented to surveillance. They are shadow-users: people affected by the software who never installed it, never saw a license, and never had a choice.

GPL-3.0 protects them indirectly:

1. **Transparency through source access.** Anyone — researchers, journalists, regulators, the targets themselves — can examine exactly what Argus does. How faces are matched. What data is logged. Where screenshots are sent. There is no proprietary black box that hides surveillance behavior.

2. **The security research mandate.** Because derivative works must carry the same license, any fork of Argus must also be open source. This means the security research purpose propagates. A company can't fork Argus, strip the README disclaimer, and sell it without revealing exactly what the tool does.

3. **The countermeasure guarantee.** GPL-3.0 ensures that improvements and countermeasures remain open. If someone builds a detection-evasion technique or an anti-surveillance countermeasure on top of Argus, that improvement must also be open source. The arms race stays visible.

4. **Audit trail.** The license requires that the software can be studied. Targets, regulators, and civil liberties organizations can legally obtain, examine, and understand the tool being used against them. You can't study a proprietary black box. You can study a GPL-3.0 project.

### Why not LGPL or AGPL

- **LGPL** would allow proprietary linking — a closed-source application could use Argus as a library without open-sourcing the application. Too permissive for this use case.
- **AGPL** would add network interaction provisions (SaaS must provide source), but Argus is a local deployment tool, not a SaaS platform. GPL-3.0 already covers the deployment scenarios that matter.

### The philosophical statement

GPL-3.0 is a political choice as much as a legal one. It says: *this tool belongs to everyone, and no one can make it belong to only themselves.* For a project that demonstrates a surveillance threat, that's the only license that makes sense.

The README says it plainly: **"This project is open-sourced under the GNU General Public License v3.0 so that people can study it, understand the threat, and develop countermeasures."**

That sentence is enforceable because of GPL-3.0. Under MIT, it would be a suggestion.

---

## Checklist

Before deploying Argus in production, verify:

- [ ] All target cameras have changed default credentials
- [ ] UPnP is disabled on cameras and routers
- [ ] RTSP ports are firewalled from the internet
- [ ] Argus runs as a non-root user
- [ ] `config/` directory permissions are `700`
- [ ] `targets/` directory permissions are `700`
- [ ] `screenshots/` and `logs/` have restricted permissions
- [ ] Camera URLs do not contain plaintext credentials in shared configs
- [ ] Argus server is firewalled from public internet (inbound denied)
- [ ] RTSP traffic is on an isolated VLAN
- [ ] Webhook endpoints use TLS and authentication
- [ ] Screenshot retention policy is in place
- [ ] You have legal authority for the surveillance you are conducting
