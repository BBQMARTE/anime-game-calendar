# Anime Game Event Calendar (动漫游戏活动日历)

[简体中文](README.md) | [English](README_EN.md) | [日本語](README_JA.md)

> **This entire project was written by AI agents** — from the prototype, front-end and back-end code, scraping kernel and Android app, to the daily verification of event schedules, all done by AI agents working in relay.

Anime Game Event Calendar (动漫游戏活动日历) aggregates event schedules and announcements from the **official public APIs** of popular anime gacha games into an iOS-style **monthly calendar** (tap any day to see that day's schedule) and event lists, with countdowns and progress bars. Available as a **PC web app** and an **Android app**.

> The supported games are their CN-server versions; all data comes from official Chinese channels.

## Feature overview

| Feature | Description |
|---|---|
| 7 games aggregated | Honkai: Star Rail, Zenless Zone Zero, Arknights: Endfield, Arknights, Wuthering Waves, Ananta, Reverse: 1999 + official Bilibili posts |
| Dual-engine data | scrapers fetch official APIs every 30 min for freshness; an AI agent web-verifies & corrects daily for accuracy |
| Monthly calendar | iOS-style event calendar — tap any day to see events starting / ongoing / ending that day |
| Image-only schedules | schedules published only as images (e.g. Endfield) are read via browser screenshots + multimodal vision |
| Multi-platform | PC web / Android APK / PWA ("Add to Home Screen", works offline) |
| Subscriptions & reminders | ICS calendar feed, Feishu/Bark event-start push, Tailscale remote access |
| Event detail popup | thumbnails in the list; tap for the full schedule image, countdown, official link |

## Contents

1. [Quick start: one message, your AI agent deploys it all](#quickstart)
2. [Install & usage](#install): [Android app](#android) / [PC web app](#pc) / [Subscriptions & reminders](#notify)
3. [Supported games & data sources](#games)
4. [Why the data is accurate: scraper + AI dual engine](#why)
5. [Appendix](#appendix): [AI agent daily automation prompt](#automation) / [Time parsing kernel](#timeparse) / [Adding events manually](#manual-add)
6. [Notes](#notes)

---

<a id="quickstart"></a>

## Quick start: send the repo link to your AI agent

Installing, configuring and scheduling this project is one message. Open your favorite AI agent app (anything with terminal / file / web-search access — TRAE, Claude Code, Cursor, …) and send:

> https://github.com/BBQMARTE/anime-game-calendar Deploy this project for me and set up the daily automation described in the README

The agent will read this document and do everything else: install dependencies → start the server → create the daily automation (web-search & verify new events, update the calendar, clean up expired ones). No manual steps, nothing to copy by hand.

Prefer doing it yourself? See [Install & usage](#install) below; the Android app can be downloaded directly from [Releases](https://github.com/BBQMARTE/anime-game-calendar/releases).

> **Agent software notice**: this project has **only been tested with [TRAE Work](https://www.trae.ai/)**; the author has not tested it with other agent apps (Claude Code, Cursor, etc.) — when in doubt, treat TRAE Work as the reference environment.

<a id="install"></a>

## Install & usage

<a id="android"></a>

### Android app

The Android app is a native WebView shell with two built-in modes: **server mode** (connect to the PC server for the most complete & accurate data) and **scraper mode** (fetch official APIs on-device, no PC needed).

**Direct download:** grab the APK from [Releases](https://github.com/BBQMARTE/anime-game-calendar/releases), transfer it to your phone and install (allow installing from unknown sources).

The web app's **gear button** (top-right) opens settings: one-tap toggle for the calendar view, and per-game checkboxes for what shows on the monthly calendar (independent of the list filters).

**Build on this machine (SDK installed on D:):**

Double-click `构建APK.bat`. On first run it generates a release signing key (`android/ycal.keystore`, password in `android/keystore.properties`); the output lands in `android/app/build/outputs/apk/release/app-release.apk`. If keytool is missing, the script falls back to a debug APK.

> **Back up `android/ycal.keystore`**: without it you cannot upgrade an installed app — only uninstall & reinstall.

**Build elsewhere:** open the `android/` folder in Android Studio, sync, then `Build > Build APK(s)`.

Minimum Android 8.0 (API 26).

> The Android project bundles its pages from `android/app/src/main/assets/www/` (a copy of `static/`).
> **After editing `static/`, copy it to `android/app/src/main/assets/www/` before rebuilding.**

<a id="pc"></a>

### PC web app (manual install)

1. Install dependencies (first run): `pip install -r requirements.txt`
2. Double-click `启动.bat` (or run `python app.py`)
3. Your browser opens <http://127.0.0.1:5000> automatically

- Fetches once on startup, then auto-refreshes every 30 minutes; manual refresh button top-right.
- Results are cached in `data/cache.json` and restored instantly on restart.
- Follows the system light/dark mode automatically.

Other devices on the LAN (tablet/phone) can use `http://<pc-ip>:5000`; for access away from home see the Tailscale option under [Subscriptions & reminders](#notify).

<a id="notify"></a>

### Subscriptions & reminders

| Feature | Usage |
|---|---|
| **ICS calendar feed** | In your system / Google Calendar, subscribe to `http://<server>:5000/api/calendar.ics` — all real events land in your native calendar |
| **PWA install** | Open the web app on a tablet/phone browser → "Add to Home Screen" for a full-screen app icon with offline data |
| **Event-start reminders** | Edit `data/notify.json` with a webhook (Feishu group bot / Bark); a daily digest of events starting today & tomorrow is pushed |
| **Access away from home** | Install [Tailscale](https://tailscale.com) on the PC and tablet with the same account, then reach the server via `http://100.x.x.x:5000` anywhere |

Example `data/notify.json`:

```json
{
  "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx",
  "time": "08:30"
}
```

- **Feishu/Lark**: group settings → bots → add a "Custom Bot", paste its webhook URL
- **Bark** (iOS app): use `https://api.day.app/<your-key>`
- Leave empty to disable; changes take effect on the next cycle

<a id="games"></a>

## Supported games & data sources

| Game | Source |
|---|---|
| Honkai: Star Rail / Zenless Zone Zero | **in-game announcement API** (same source as the in-game "Notices" panel) + version update article splitting |
| Arknights: Endfield | official website news pages (with detail links) + version update article splitting |
| Wuthering Waves | official website article API + automatic splitting of version notes into events |
| Ananta | Perfect World official news pages (notices/events/news) |
| Official Bilibili accounts of all 5 games | public Bilibili post API (categorized as info) |

### Display logic: real events vs. info

Everything fetched falls into two tiers:

| Tier | Content | Where it shows |
|---|---|---|
| **Event** | limited-time events, character & weapon banners with **start/end times**, auto-shortened titles, countdown & progress bar | Ongoing / Upcoming |
| **Info** | fix notices, gameplay guides, shop updates, surveys, official news, Bilibili posts | "All info" tab only |

The top filter bar filters by game and by category (events / check-in / characters & weapons / notices / info). **Daily sign-in and cumulative login events are auto-tagged "check-in" (签到)** — filter them out in one click if you don't want the daily grind.

Each game's **version update article** is automatically split into individual events ("new events", "new banners", …); the article itself goes to the info tab.

<a id="why"></a>

## Why the data is accurate: scraper + AI dual engine

The initial prototype was built by **Kimi K3**, then developed in relay across **several AI agent apps** (switching whenever credits ran out), and finally completed and fully tested in [TRAE Work](https://www.trae.ai/) — this project really is written by AI.

The first version was a pure scraper: fetch official APIs, split version-update articles into events, parse time ranges with regex. It worked — sort of.

In practice, the scraped data was riddled with errors: swapped start/end times, article body fragments leaking into event titles, occasionally broken API responses producing garbage entries… Rule-based parsing can never plug all of these edge cases.

Then came the idea: **agent apps can search the web — what if an AI agent searched official announcements and verified the schedules every day?**

The result was excellent: the agent's search results were accurate and complete, with times precise to the minute — far beyond what regex parsing could ever achieve. Every AI-verified entry in the calendar came from this channel.

So the project settled on a **dual-engine** design:

| Engine | Frequency | Responsibility |
|---|---|---|
| Scrapers | every 30 min | auto-fetch official APIs for freshness |
| AI agent search | once a day | web-search, verify & correct schedules for accuracy |

<a id="appendix"></a>

## Appendix

<a id="automation"></a>

### AI agent daily automation prompt

The data accuracy comes down to a single automation prompt. Send the repo link to your agent as described in [Quick start](#quickstart) — it will read this section and **create the scheduled task itself**, filling in the project path for you. Nothing to copy.

The full prompt is included below for two purposes: ① for agents to consume directly, and ② for anyone who prefers manual setup (create a once-a-day scheduled task in your agent app, e.g. 20:00, paste the prompt, replace `<project-path>` with your local repo path).

Every day the agent will automatically: make sure the server is up → web-search & verify new events → recognize image-only schedules (browser-screenshot method) → update the calendar → clean up expired ones.

```text
Daily maintenance task for the anime game event calendar. Project directory: <project-path>. Follow the steps below strictly. Do not modify any source code.

[Step 1: make sure the local server is running]
Probe http://127.0.0.1:5000/api/events; if unreachable, start "python app.py" in the project directory in the background and wait ~10s; if the server is already running, skip — never restart a running server.

[Step 2: web-search new events for the 5 games]
Search for events/banners officially published in the last 1–2 days for:
- Honkai: Star Rail (game_id: hsr)
- Zenless Zone Zero (game_id: zzz)
- Arknights: Endfield (game_id: endfield)
- Wuthering Waves (game_id: wuwa)
- Ananta (game_id: ananta)
Look for: version update notes / event overviews, limited-time events, character & weapon banners with exact start/end times.
Verification standard: times must be cross-confirmed by official sources (official site news, official Bilibili account, in-game announcements); times are in Beijing time, precise to HH:MM; if a time cannot be verified, do not record it.

[Image-only schedules (browser-screenshot method, no third-party API)]
Some games (typically Arknights: Endfield) publish event schedules as images — plain text search cannot see them. Note: WebSearch/WebFetch return text only; even a multimodal model cannot "see" images that never enter its context. The solution: let the agent look at the image with browser tools:
1. Find the direct URL of the "version calendar / event overview" image (extractable from official Bilibili posts or the official site)
2. Dispatch a browser subagent to open the image (load it via this project's /api/img proxy to bypass hotlink protection), take a screenshot, and transcribe every event name and start/end date from the screenshot; for tall images, scroll and take multiple screenshots to cover the whole thing
3. Sanity-check the transcription (dates within the version cycle, no conflicts with existing entries), then record per Step 3 with the schedule image URL in the image field; if the image shows no HH:MM, fill in the game's habitual update time (Endfield: 12:00, ends 11:59 next day) and note it in the report
4. If the agent platform has no browser/screenshot tools, fall back to text-only search and list the unrecognized image URLs in the report; never guess image contents

[Step 3: update data/manual.json]
1. Read all existing entries first
2. Deduplicate by (game_id + title); do not add entries that already exist
3. Append new entries at the end of the JSON array:
   {"game_id": "hsr", "title": "Event Name", "category": "活动", "start": "2026-08-20T10:00", "end": "2026-09-03T03:59", "link": "official link", "image": "image URL, optional"}
   image: direct URL of the official artwork/schedule image — shown as list thumbnail & detail popup; empty string if none
   category values: 活动 (event) / 角色与专武 (character & weapon banner) / 公告 (notice) / 资讯 (info)
   Leave end as an empty string for permanent/no-end events; only record events whose end time is in the future
4. Cleanup: delete entries whose end is a valid date earlier than now; keep entries with an empty end
5. Save as UTF-8 and keep the JSON valid

[Step 4: refresh the server]
If the server is up, POST to http://127.0.0.1:5000/api/refresh with the header X-Requested-With: ycal

[Report]
Briefly report: ① server status; ② new events recorded per game; ③ how many expired entries were cleaned; ④ say "no new events" where applicable; ⑤ image-schedule recognition: which schedule images were read, how many entries transcribed, which existing entries corrected. Do not record events whose times you are unsure about — state the uncertainty instead.
```

<a id="timeparse"></a>

### Time parsing kernel

Event times are extracted by `timeparse.py` (web/server) and `static/scraper.js` (Android, isomorphic). It covers most real-world announcement formats:

- **Dates**: `2026年7月10日` / `2026/07/10` / `2026.07.10` / `07.10` / `7月10日` / `7/10` / full-width digits
- **Times**: `12:00` / `12:00:00` / `12点` / `12点30分` / `12时30分`
- **Ranges**: `x月x日 ~ x月x日` (separators `~ ～ — –`, ` 至 `, ` 到 `, ` - `)
  - Even **without** an "event time:" keyword, two adjacent dates are recognized as a range
  - Year-crossing ranges like `12月30日 ~ 1月5日` roll the end date into the next year
- **Permanent**: keywords like 长期/常驻/永久/持续开放 mark an event as never-ending
- **Event names**: brackets `「」『』【】[]（）〈〉` and `■/◆/✦` heading lines; generic titles (e.g. "version event") are filtered
- **Missing end time**: events with a start but no end get a default **2-day** window

<a id="manual-add"></a>

### Adding events manually (fallback channel)

If the automatic fetch misses an event, there are two ways to add it (this is also the channel the agent automation uses):

**Option 1: edit it yourself** — edit `data/manual.json` (a JSON array, multiple entries allowed); the next refresh merges it in:

```json
[
  {
    "game_id": "ananta",
    "title": "「像素溢出」限时活动",
    "category": "活动",
    "start": "2026-08-01T10:00",
    "end": "2026-08-15T04:00",
    "link": "https://yh.wanmei.com/",
    "image": ""
  }
]
```

- `game_id` optional: `hsr / zzz / endfield / arknights / wuwa / ananta / r1999`
- `category` optional: `活动 / 签到 / 角色与专武 / 公告 / 资讯`
- Manual entries count as events (kind=event) and appear in Ongoing/Upcoming with a gray "manual" tag.
- On Android: write the same JSON array to the localStorage key `ycal_manual`.

**Option 2: hand it to an AI** — send the official schedule image (e.g. an event calendar picture) or text to your AI assistant and let it write the entry into `data/manual.json`.

<a id="notes"></a>

## Notes

> **Data copyright notice: all event schedules and announcement content displayed by this project are entirely copyrighted by the games' official publishers (HoYoverse/miHoYo, Hypergryph, Kuro Games, Perfect World, etc.).** This project is an information-aggregation display for personal learning and exchange only; it contains no official asset files and is not used for any commercial purpose. For official details of each event, refer to the games' official channels. Contact me for removal in case of infringement.

- All data comes from official public pages/APIs and public Bilibili posts; no logins, no exploits. Please keep request rates low.
- Times are in Beijing time; events with an official start~end range get a countdown and progress bar.
- To add a game: register it in `REGISTRY` in `scrapers.py` (web) or in `RUNNERS` in `scraper.js` (Android).
- The classification word lists live in `scrapers.py` (`_NOISE_RE` noise / `_SHOP_RE` shop / `_POOL_RE` banner / `_ACT_TITLE_RE` event-title patterns) and the same-named constants in `scraper.js` — tweak as needed.
