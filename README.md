# 🎬 Bazarr Auto-Translate

A lightweight Python automation script that interfaces with the Bazarr API to automatically detect missing subtitles and generate them by translating existing subtitles in your library. 

Currently, Bazarr supports subtitle translation via providers like Lingarr, but it lacks a built-in automation queue to translate subtitles seamlessly in the background. This script bridges that gap by continuously scanning your media, finding available subtitles, and queuing them for translation directly through Bazarr's native request system.

> [!CAUTION]
> This fork was modified with the help of LLMs, I am not a professional coder.

---

## ⚠️ Critical Warning

This script is designed to run automatically and continuously. Depending on the size of your library and your configuration, it can trigger **a massive volume of translation requests**.

If you use a **paid translation API service**, this script could result in **unexpected high charges** because it currently has:
- No maximum daily translation caps.
- No rate limiting.
- No limits on consecutive errors.

**Use this script entirely at your own risk.** Please monitor your usage closely, especially when spinning it up for the first time.

---

## ✨ Key Features

- **Automated Scanning**: Periodically scans your mapped Movies and TV Series libraries in Bazarr for missing subtitles.
- **Intelligent Fallback**: Checks if an existing subtitle in your library (e.g., English) can be used as a base source to translate into your desired missing languages.
- **Native Integration**: Pushes translation requests securely through the Bazarr API. This ensures Bazarr properly tracks the new subtitle and allows for future quality upgrades.
- **Concurrency**: Supports multiple worker threads to process multiple translation requests in parallel.

---

## 🤔 Why use this instead of standalone Lingarr?

While Lingarr can auto-translate subtitles externally, translating subtitles *outside* of Bazarr causes a desync: Bazarr remains unaware of the new subtitle's existence. Consequently, Bazarr will never attempt to upgrade it if a better, manually-crafted subtitle drops on your indexers later.

By using this script, translations are strictly routed through **Bazarr’s API**. This guarantees that:
1. Bazarr accurately registers the new translation in its database.
2. Bazarr can flag the subtitle as "Upgradable" and replace it when a native version becomes available.

---

## ⚙️ Configuration

The script is controlled via environment variables. You can pass these through a `.env` file or directly via your Docker configuration. 

| Variable | Description | Default | Required |
| :--- | :--- | :--- | :--- |
| `BAZARR_BASE_URL` | The full URL to your Bazarr instance (e.g., `http://192.168.1.50:6767`). | None | **Yes** |
| `BAZARR_API_KEY` | Your Bazarr API Key (found in Settings > General). | None | **Yes** |
| `BASE_LANGUAGES` | Comma-separated ISO-639-1 (`code2`) languages to use as the *source* for translations (e.g., `en,fr`). | None | **Yes** |
| `TO_LANGUAGES` | Comma-separated ISO-639-1 (`code2`) languages you want the missing subtitles translated *into* (e.g., `es,de`). | None | **Yes** |
| `TRANSLATION_REQUEST_TIMEOUT` | Seconds to wait for a translation to finish before marking it as failed. **Note:** Set this high enough to prevent duplicate requests. | `900` (15m) | No |
| `NUM_WORKERS` | Number of simultaneous translation threads to process at once. | `1` | No |
| `INTERVAL_BETWEEN_SCANS` | Cooldown time (in seconds) between full library scans. | `300` (5m) | No |
| `SERIES_SCAN` / `MOVIES_SCAN` | Toggle scanning for Shows/Movies respectively (`true` or `false`). | `true` | No |
| `LOG_LEVEL` / `LOG_DIRECTORY` | Logging verbosity (`DEBUG`, `INFO`, `ERROR`) and the output path. | `INFO` / `logs/`| No |

---

## 🚀 Setup & Usage

### Docker Compose
The easiest way to run the script is alongside your existing media stack using Docker Compose:

```yaml
services:
  bazarr-autotranslate:
    image: ghcr.io/zelak312/bazarr_autotranslate:latest
    container_name: bazarr_autotranslate
    restart: unless-stopped
    environment:
      - BAZARR_BASE_URL=http://your_bazarr_ip:6767
      - BAZARR_API_KEY=your_api_key_here
      - BASE_LANGUAGES=en
      - TO_LANGUAGES=es,fr
      - LOG_LEVEL=info
    volumes:
      - ./logs:/usr/src/app/logs
```

### Bazarr Settings Prerequisites
To ensure everything operates smoothly, verify the following settings inside Bazarr:
1. **Enable a Translator**: Navigate to `Settings -> Subtitles -> Translating` and ensure a provider (like Lingarr) is selected and configured.
2. **Enable Upgrades**: Navigate to `Settings -> Subtitles -> Upgrading Subtitles` and enable `Upgrade Manually Downloaded or Translated Subtitles`. This allows Bazarr to eventually replace the machine translations with real ones.

---

## 🤝 Contributing & License
Contributions, issue reports, and pull requests are highly welcome. 
Distributed under the **MIT License**.
