# ECP Calendar Sync

Automatically scrapes the [Explorers Club of Pittsburgh](https://pittecp.org/calendar) event calendar and publishes a live `.ics` feed you can subscribe to in Google Calendar, Apple Calendar, or Outlook.

**Runs daily via GitHub Actions. No server or paid services needed.**

---

## Setup (one-time, ~5 minutes)

### 1. Create your GitHub repository

1. Go to [github.com](https://github.com) and sign in (create a free account if needed)
2. Click **+** → **New repository**
3. Name it something like `ecp-calendar`
4. Set it to **Public** (required for free GitHub Pages)
5. Click **Create repository**

### 2. Upload these files

Upload all files from this folder to your new repo, preserving the folder structure:

```
ecp-calendar/
├── scrape.py
├── README.md
├── .github/
│   └── workflows/
│       └── update-calendar.yml
└── docs/
    ├── index.html
    └── ecp.ics
```

You can do this via the GitHub web UI (drag and drop) or with git:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/ecp-calendar.git
git push -u origin main
```

### 3. Enable GitHub Pages

1. In your repo, go to **Settings** → **Pages**
2. Under "Source", select **Deploy from a branch**
3. Branch: `main`, Folder: `/docs`
4. Click **Save**

After a minute, GitHub will give you a URL like:
`https://YOUR_USERNAME.github.io/ecp-calendar/`

### 4. Run the Action for the first time

1. Go to the **Actions** tab in your repo
2. Click **Update ECP Calendar**
3. Click **Run workflow** → **Run workflow**

This populates `docs/ecp.ics` with real events. Future runs happen automatically every day at 6 AM UTC.

### 5. Subscribe in Google Calendar

1. Copy your `.ics` URL: `https://YOUR_USERNAME.github.io/ecp-calendar/ecp.ics`
2. Open [Google Calendar](https://calendar.google.com) on **desktop** (not mobile)
3. Click **+** next to "Other calendars" in the left sidebar
4. Choose **"From URL"**
5. Paste your URL → **Add calendar**

✅ Done! ECP events will appear in your Google Calendar and refresh automatically.

---

## How it works

| Component | Purpose |
|-----------|---------|
| `scrape.py` | Fetches 6 months of ECP calendar pages, parses event links and details, outputs a valid `.ics` file |
| `.github/workflows/update-calendar.yml` | GitHub Action that runs `scrape.py` daily, commits changes |
| `docs/ecp.ics` | The generated calendar file, served as a static file via GitHub Pages |
| `docs/index.html` | Human-readable page with subscribe instructions |

## Notes

- **Member-only events** won't appear (the scraper isn't logged in)
- Google Calendar refreshes subscribed calendars roughly every **12–24 hours**
- You can trigger a manual refresh anytime via the Actions tab → Run workflow
- The scraper fetches **6 months ahead** by default; change `MONTHS_AHEAD` in `scrape.py` to adjust
