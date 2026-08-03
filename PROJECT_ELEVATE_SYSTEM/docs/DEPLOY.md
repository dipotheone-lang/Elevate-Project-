# Deploy the PROJECT ELEVATE Dashboard Online (free)
### United Brothers Co. / الاخوة المتحدين للمقاولات

The dashboard (`dashboard.py`) is a Streamlit app. The easiest, free way to put
it online with a shareable link is **Streamlit Community Cloud**, which deploys
straight from this GitHub repo — no servers, no payment.

نشر لوحة التحكم على الإنترنت مجاناً عبر Streamlit Community Cloud.

---

## Prerequisites
- The code is on GitHub (it is: `dipotheone-lang/Elevate-Project-`).
- A (free) Streamlit Community Cloud account — you sign in with your GitHub login.

---

## Step-by-step

1. Go to **https://share.streamlit.io** and click **Sign in** → **Continue with GitHub**. Authorize it.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `dipotheone-lang/Elevate-Project-`
   - **Branch:** `main`
   - **Main file path:** `PROJECT_ELEVATE_SYSTEM/dashboard.py`
4. Click **Deploy**.
5. Wait ~2–3 minutes for the first build (it installs the dependencies listed in
   the repo-root `requirements.txt`). When it finishes you get a public URL like
   `https://<something>.streamlit.app` — that's your shareable link.

That's it. Send the link to your team; anyone can open it in a browser.

---

## Updating the app
Every time changes are merged to `main`, the app **auto-redeploys** — no action
needed. To force a rebuild: on the app page, **⋮ menu → Reboot**.

---

## Access control (recommended for internal financial data)
A public app URL can be opened by anyone who has the link. To restrict it:

1. On the app page, open **Settings → Sharing**.
2. Turn the app **Private** and add the **email addresses** of your team.
   Only those Google/GitHub accounts can open it.

> The app ships with **sample data**. Any real numbers you type into the browser
> live only in your current session — they are not saved to the repo or shared
> with other viewers. Still, prefer the Private setting for internal use.

---

## Run it locally instead (no internet)
If you'd rather keep everything on your own laptop:

```bash
cd PROJECT_ELEVATE_SYSTEM
# Windows: double-click dashboard.bat
# Mac/Linux:
./dashboard.sh
```
It installs Streamlit and opens the dashboard at `http://localhost:8501`.

---

## Troubleshooting
- **Build fails on dependencies** → confirm the repo-root `requirements.txt`
  exists and lists `streamlit`, `pandas`, `openpyxl`, `tabulate`.
- **"Main file does not exist"** → the path is `PROJECT_ELEVATE_SYSTEM/dashboard.py`
  (note the subfolder).
- **App is slow to wake** → free apps sleep after inactivity; the first visit
  takes a few seconds to wake. That's normal.

---

_United Brothers Co. — PROJECT ELEVATE • Navy `#1B365D` / Gold `#D4AF37`_
