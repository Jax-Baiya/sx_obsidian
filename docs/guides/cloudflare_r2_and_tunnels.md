# Cloudflare Setup Guide: R2 Buckets & Zero-Trust Tunnels

This guide covers how to set up your Cloudflare R2 storage for media syncing and how to expose your local SX Obsidian Web interface to the internet using a secure Cloudflare Tunnel.

---

## 1. Cloudflare R2 Bucket Setup

> **Important Architectural Note:** 
> **Do NOT create a separate bucket for each profile.** You should create **one single bucket** (e.g., `sxo-publishing-assets`). The application is designed to logically separate your media by automatically creating folders based on the profile ID (e.g., `assets_1/video.mp4`, `assets_2/video.mp4`). This makes CORS policies and API credentials significantly easier to manage.

### Step-by-Step R2 Setup

1. **Log into Cloudflare:** Go to your Cloudflare Dashboard and select ** الر R2 Object Storage** from the left-hand sidebar. (You may need to add a payment method if this is your first time using R2, but the free tier gives you 10GB/month).
2. **Create Bucket:**
   - Click **Create bucket**.
   - Name your bucket (e.g., `sxo-publishing-assets`). This name must be unique.
   - Leave Location Hint as Automatic (or select one close to you) and click **Create bucket**.
3. **Generate API Credentials:**
   - In the R2 Dashboard menu, click **Manage R2 API Tokens** (top-right area).
   - Click **Create API token**.
   - **Name:** SX Obsidian Media Sync
   - **Permissions:** Object Read & Write
   - **Specify Bucket(s):** Apply to specific buckets -> select your new bucket.
   - Click **Create API Token**.
4. **Copy credentials to `.env`:** Cloudflare will show you the credentials exactly once. Copy them into your `sx_obsidian/.env` file:
   ```env
   SX_R2_ACCOUNT_ID="<Your Account ID>"
   SX_R2_ACCESS_KEY_ID="<Access Key ID>"
   SX_R2_SECRET_ACCESS_KEY="<Secret Access Key>"
   SX_R2_BUCKET_NAME="sxo-publishing-assets"
   ```
5. **Enable Public Access (Optional but recommended for Web UI playback):**
   - Go to your Bucket's **Settings** tab.
   - Scroll down to **Public Access** -> **Custom Domains**.
   - Click **Connect a domain** and type a subdomain like `sxo-media.yourdomain.com`. Cloudflare will automatically configure the DNS for you.
   - Update your `.env` with the URL: `SX_R2_PUBLIC_DOMAIN="sxo-media.yourdomain.com"`

---

## 2. Setting Up a Cloudflare Tunnel (Subdomain Proxy)

To access your Next.js Web Control Plane securely from anywhere in the world without opening ports on your router, we will use a Cloudflare Zero Trust Tunnel.

### Prerequisites
- You must have a domain name managed by Cloudflare.
- `cloudflared` must be installed on your local Linux machine.

### Step-by-Step Tunnel Setup

1. **Log into Cloudflare Zero Trust:**
   - From the main Cloudflare Dashboard, go to **Zero Trust** -> **Networks** -> **Tunnels**.
   - Click **Create a tunnel**.
   - Select **Cloudflared** type and hit Next.
   - Name your tunnel (e.g., `sxo-web-control-plane`).
2. **Install & Run Connector:**
   - Cloudflare will give you a command to run on your Linux machine. It looks something like:
     ```bash
     sudo cloudflared service install eyJh... (very long token)
     ```
   - Run that command in your terminal. Once it says "Connected," click **Next** in the Cloudflare UI.
3. **Route Traffic to your Next.js Server:**
   - Under the **Public Hostnames** tab, you map a public subdomain to your local `localhost:3000` port.
   - **Subdomain:** e.g., `sx-manager`
   - **Domain:** `yourdomain.com` (select from dropdown)
   - **Service Type:** `HTTP`
   - **URL:** `localhost:3000`
   - Click **Save tunnel**.
4. **Access your Web Interface:**
   - Wait 1-2 minutes for DNS to propagate.
   - You can now access your Next.js UI from anywhere via `https://sx-manager.yourdomain.com`. The Cloudflare Tunnel will securely proxy requests down to your local port `3000`.

### (Optional) Securing the Web UI
Since your tunnel is publicly accessible on the internet, you should put an authentication screen in front of it:
1. In the Zero Trust dashboard, go to **Access** -> **Applications**.
2. Click **Add an application** -> **Self-hosted**.
3. Set the application URL to `sx-manager.yourdomain.com`.
4. Create a policy where only your email address receives a One-Time PIN (OTP) to login. Now, the dashboard is completely invisible to anyone except you!
