# RYDER AI app

Phone-first, read-only paper-trading dashboard. No wallet, keys, signing, or real orders.

## Open the app

Published app: https://ryder-ai-night-desk.gardenanole35.chatgpt.site

On iPhone, open in Safari, choose Share → Add to Home Screen.

## Files

- index.html, style.css, app.js: app interface.
- manifest.webmanifest, sw.js, icon-*.png: Home Screen support using the original star mascot.
- snapshot.json: supplied historical bot snapshot, clearly labeled in the UI.
- data.json: empty placeholder reserved for future live stats.

## Data connection

Settings lets you import a snapshot or connect an HTTPS JSON endpoint using the same schema as snapshot.json. The endpoint must allow CORS from the app origin. Feeds refresh every 45 seconds while the app is open. The empty data.json is not a valid live snapshot yet. No bot runtime or automatic data publisher is included in this repository.

Serve this folder with an HTTP server for local preview. Production Home Screen features require HTTPS. This repository upload does not enable GitHub Pages or change the existing hosted app.
