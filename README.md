# 🎬 Bazarr Auto-Translate & Acquire

A lightweight Python automation script that interfaces with the Bazarr API to intelligently acquire, extract, transcribe, and translate missing subtitles in your library. 

Currently, Bazarr supports powerful tools like Lingarr (translation), WhisperAI (audio transcription), and Embedded Subtitle extraction. However, it lacks a unified, intelligent background queue to manage them together. This script bridges that gap by continuously scanning your media and running a multi-stage pipeline to get the best possible subtitle without downloading out-of-sync garbage.

> [!CAUTION]
> This fork was modified with the help of LLMs, I am not a professional coder.

---

## ⚠️ Critical Warning

This script is designed to run automatically and continuously. Depending on the size of your library and your configuration, it can trigger **a massive volume of API requests, transcriptions, and translations**.

If you use a **paid translation API service** (like Lingarr + DeepL), this script could result in **unexpected high charges** because it currently has:
- No maximum daily translation caps.
- No rate limiting.
- No limits on consecutive errors.

**Use this script entirely at your own risk.** Please monitor your usage closely, especially when spinning it up for the first time.

---

## ✨ Key Features & The Multi-Stage Pipeline

Instead of blindly translating everything, the script uses a smart fallback engine to save compute resources and guarantee better subtitle quality. When a subtitle is missing, it evaluates options in this exact order:

1. **Direct Acquisition**: Is there an *embedded* subtitle or a *high-scoring* online subtitle (≥ `MIN_SCORE`) for the target language? If yes, extract/download it immediately. No translation needed!
2. **Local Translation**: Do we already have an external base subtitle (e.g., English) on disk? If yes, queue it for Lingarr translation.
3. **Base Acquisition**: Is there an *embedded* base subtitle or a *high-scoring* online base subtitle? If yes, extract/download it to be translated on the next scan.
4. **WhisperAI Fallback**: If absolutely no high-quality subtitles are available online, trigger WhisperAI to transcribe the audio track into a base subtitle.
5. **Profile Migration (Optional)**: Automatically changes a media item's Bazarr Language Profile if specific languages are missing (e.g., automatically shifting `EN+NO` to `EN+NB`).

---

## 🤔 Why use this instead of standalone Lingarr or Whisper?

While Lingarr and Whisper can generate subtitles externally, doing so *outside* of Bazarr causes a desync: Bazarr remains unaware of the new subtitle's existence. Consequently, Bazarr will never attempt to upgrade it if a better, manually-crafted subtitle drops on your indexers later.

By using this script, all actions are strictly routed through **Bazarr’s API**. This guarantees that:
1. Bazarr accurately registers the new extraction, transcription, or translation in its database.
2. Bazarr can flag the subtitle as "Upgradable" and replace it when a native retail version becomes available.

---

## 💡 Use Case: The "English-Only" WhisperAI Trick

**Can I use this if I ONLY want English subtitles?** **Yes! In fact, it solves one of Bazarr's biggest WhisperAI flaws.**

If you want Bazarr to download good online subtitles (e.g., 86%+ score) but fallback to WhisperAI when none exist, you normally have a problem: Bazarr assigns WhisperAI a fixed score of `~66%`. If you lower your Bazarr cutoff to 66% to allow WhisperAI to run, Bazarr will start downloading terrible, out-of-sync online subtitles too!

**The Solution:** Leave your Bazarr minimum score high (e.g., 86%). Run this script with `BASE_LANGUAGES=en` and `TO_LANGUAGES=en`. 
The script will enforce your strict `MIN_SCORE=86` for online providers, but it is programmed to **bypass the score requirement for WhisperAI and Embedded tracks**. You get high-quality online subs when available, and WhisperAI when they aren't, completely avoiding the 66% garbage tier!

---

## ⚙️ Configuration

The script is controlled via environment variables. You can pass these through a `.env` file or directly via your Docker configuration. 

| Variable | Description | Default | Required |
| :--- | :--- | :--- | :--- |
| `BAZARR_BASE_URL` | The full URL to your Bazarr instance (e.g., `http://192.168.1.50:6767`). | None | **Yes** |
| `BAZARR_API_KEY` | Your Bazarr API Key (found in Settings > General). | None | **Yes** |
| `BASE_LANGUAGES` | Comma-separated ISO-639-1 (`code2`) languages to use as the *source* (e.g., `en,fr`). **Prioritized in the order listed.** | None | **Yes** |
| `TO_LANGUAGES` | Comma-separated ISO-639-1 (`code2`) languages you want missing subtitles translated *into* (e.g., `es,de`). | None | **Yes** |
| `MIN_SCORE` | The minimum Bazarr score required to download an online subtitle. (Embedded & Whisper bypass this). | `86` | No |
| `TRANSLATION_REQUEST_TIMEOUT` | Seconds to wait for a translation to finish before marking it as failed. | `900` (15m) | No |
| `NUM_WORKERS` | Number of simultaneous translation/search threads to process at once. | `1` | No |
| `INTERVAL_BETWEEN_SCANS` | Cooldown time (in seconds) between full library scans. | `300` (5m) | No |
| `SOURCE_PROFILE_ID` | The Bazarr Profile ID to target for automatic migration. | None | No |
| `TARGET_PROFILE_ID` | The Bazarr Profile ID to switch the media to during migration. | None | No |
| `SERIES_SCAN` / `MOVIES_SCAN` | Toggle scanning for Shows/Movies respectively (`true` or `false`). | `true` | No |
| `LOG_LEVEL` / `LOG_DIRECTORY` | Logging verbosity (`DEBUG`, `INFO`, `ERROR`) and the output path. | `INFO` / `logs/`| No |

---

## 🚀 Setup & Usage

### Docker Compose
The easiest way to run the script is alongside your existing media stack using Docker Compose:

```yaml
services:
  bazarr-autotranslate:
    image: ghcr.io/newandreas/bazarr_autotranslate:latest
    container_name: bazarr_autotranslate
    restart: unless-stopped
    environment:
      - BAZARR_BASE_URL=http://your_bazarr_ip:6767
      - BAZARR_API_KEY=your_api_key_here
      - BASE_LANGUAGES=en
      - TO_LANGUAGES=es,fr
      - MIN_SCORE=86
      - LOG_LEVEL=info
    volumes:
      - ./logs:/usr/src/app/logs
