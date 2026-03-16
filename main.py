import os
import sys
import time
import httpx
import queue
import signal
import asyncio
import logging
import threading
from dotenv import load_dotenv
from typing import List, Optional
from unique_queue import UniqueQueue
from logging.handlers import TimedRotatingFileHandler
from class_types import Serie, Movie, SubtitleTranslate

def get_env_or_default(env, default):
    val = os.getenv(env)
    return val if val is not None else default

def get_attr_or_key(obj, name):
    if hasattr(obj, name):
        return getattr(obj, name)
    elif isinstance(obj, dict) and name in obj:
        return obj[name]
    else:
        raise AttributeError(f"Missing attribute or key '{name}'")

# Get configuration and setup things
load_dotenv()
base_languages_env = os.getenv("BASE_LANGUAGES")
base_languages = [lang.strip() for lang in base_languages_env.split(",")] if base_languages_env else []

to_languages_env = os.getenv("TO_LANGUAGES")
to_languages = [lang.strip() for lang in to_languages_env.split(",")] if to_languages_env else []

translation_request_timeout = int(get_env_or_default("TRANSLATION_REQUEST_TIMEOUT", 15 * 60))
num_workers = int(get_env_or_default("NUM_WORKERS", 1))
interval_between_scans = int(get_env_or_default("INTERVAL_BETWEEN_SCANS", 5 * 60))
log_level = get_env_or_default("LOG_LEVEL", "INFO")
log_directory = get_env_or_default("LOG_DIRECTORY", "logs/")
series_scan = bool(get_env_or_default("SERIES_SCAN", True))
movies_scan = bool(get_env_or_default("MOVIES_SCAN", True))

# Profile Migration Env Vars
source_profile_id = get_env_or_default("SOURCE_PROFILE_ID", None)
target_profile_id = get_env_or_default("TARGET_PROFILE_ID", None)
if source_profile_id: source_profile_id = int(source_profile_id)
if target_profile_id: target_profile_id = int(target_profile_id)

action_cooldown_cache = {}
ACTION_COOLDOWN_SECONDS = 3600

key_fn = lambda x: f" {"s" if get_attr_or_key(x, "is_serie") else "m"} {get_attr_or_key(x, "video_id")}_{get_attr_or_key(x, "to_language")}"
search_key_fn = lambda x: f"search_{'s' if get_attr_or_key(x, 'is_serie') else 'm'}_{get_attr_or_key(x, 'video_id')}"
migration_key_fn = lambda x: f"mig_{x['type']}_{x['id']}"

task_queue = UniqueQueue(key_fn=key_fn)
search_task_queue = UniqueQueue(key_fn=search_key_fn)
migration_queue = UniqueQueue(key_fn=migration_key_fn)
shutdown_event = asyncio.Event()
logger = logging.getLogger("bazarr_lingarr")

def check_and_queue_migrations(data: list, media_type: str):
    """Intercepts raw JSON data to check if profiles need to be migrated to NB"""
    if not source_profile_id or not target_profile_id:
        return
        
    for obj in data:
        profile_id = obj.get("language_profile_id")
        if profile_id == source_profile_id:
            missing = obj.get("missing_subtitles", [])
            # If the specific language 'no' is missing, queue migration
            if any(isinstance(sub, dict) and sub.get("code2") == "no" for sub in missing):
                video_id = obj.get("radarrId") if media_type == "movies" else obj.get("sonarrEpisodeId")
                
                # Fallback if raw keys differ
                if not video_id:
                    video_id = obj.get("radarr_id") if media_type == "movies" else obj.get("sonarr_episode_id")
                    
                if video_id and not migration_queue.check({"type": media_type, "id": video_id, "target_profile": target_profile_id}):
                    migration_queue.put({"type": media_type, "id": video_id, "target_profile": target_profile_id})

async def get_episodes_metadata(base_url: str, api_key: str, episode_ids: Optional[List[int]] = None) -> List[Serie] | None:
    endpoint = f"{base_url}/api/episodes"
    headers = {"X-API-KEY": api_key}
    try:
        async with httpx.AsyncClient() as client:
            if not episode_ids:
                response = await client.get(endpoint, headers=headers)
                response.raise_for_status()
                return [Serie.from_dict(obj) for obj in response.json()["data"]]
            
            all_episodes = []
            chunk_size = 50
            for i in range(0, len(episode_ids), chunk_size):
                chunk = episode_ids[i:i + chunk_size]
                params = {"episodeid[]": chunk}
                response = await client.get(endpoint, headers=headers, params=params)
                response.raise_for_status()
                all_episodes.extend([Serie.from_dict(obj) for obj in response.json()["data"]])
                
            return all_episodes
    except Exception:
        logger.exception("Error while getting episode metadata:")
        return None

async def get_wanted_episodes(base_url: str, api_key: str) -> List[Serie] | None:
    endpoint = f"{base_url}/api/episodes/wanted"
    headers = {"X-API-KEY": api_key}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(endpoint, headers=headers, params={"start": 0, "length": -1})
            response.raise_for_status()
            data = response.json()["data"]
            check_and_queue_migrations(data, "episodes")
            return [Serie.from_dict(obj) for obj in data]
    except Exception:
        logger.exception("Error while getting wanted episodes:")
        return None

async def get_movies_metadata(base_url: str, api_key: str, movie_ids: Optional[List[int]] = None) -> List[Movie] | None:
    endpoint = f"{base_url}/api/movies"
    headers = {"X-API-KEY": api_key}
    try:
        async with httpx.AsyncClient() as client:
            if not movie_ids:
                response = await client.get(endpoint, headers=headers)
                response.raise_for_status()
                return [Movie.from_dict(obj) for obj in response.json()["data"]]
            
            all_movies = []
            chunk_size = 50
            for i in range(0, len(movie_ids), chunk_size):
                chunk = movie_ids[i:i + chunk_size]
                params = {"radarrid[]": chunk}
                response = await client.get(endpoint, headers=headers, params=params)
                response.raise_for_status()
                all_movies.extend([Movie.from_dict(obj) for obj in response.json()["data"]])
                
            return all_movies
    except Exception:
        logger.exception("Error while getting movies metadata:")
        return None

async def get_wanted_movies(base_url: str, api_key: str) -> List[Movie] | None:
    endpoint = f"{base_url}/api/movies/wanted"
    headers = {"X-API-KEY": api_key}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(endpoint, headers=headers, params={"start": 0, "length": -1})
            response.raise_for_status()
            data = response.json()["data"]
            check_and_queue_migrations(data, "movies")
            return [Movie.from_dict(obj) for obj in data]
    except Exception:
        logger.exception("Error while getting wanted movies:")
        return None

def is_external_subtitle(sub, video_path) -> bool:
    if not sub.path:
        return False
    if video_path and sub.path == video_path:
        return False
    if sub.path.lower().endswith(('.srt', '.ass', '.vtt', '.sub')):
        return True
    return False

async def find_base_language_subtitles_from_missing_sutitles(base_url, api_key, videos: List[Serie] | List[Movie]):
    video_id_language_map = {}
    for video in videos:
        video_id = video.sonarr_episode_id if isinstance(video, Serie) else video.radarr_id
        for missing_sub in video.missing_subtitles:
            if missing_sub.code2 in to_languages:
                video_id_language_map[video_id] = missing_sub.code2

    if not video_id_language_map:
        return [], []

    metadata = None
    if isinstance(videos[0], Serie):
        metadata = await get_episodes_metadata(base_url, api_key, episode_ids=list(video_id_language_map.keys()))
    else:
        metadata = await get_movies_metadata(base_url, api_key, movie_ids=list(video_id_language_map.keys()))

    if not metadata:
        return [], []
    
    video_id_to_video_map = { (v.sonarr_episode_id if isinstance(v, Serie) else v.radarr_id): v for v in metadata }
    
    subtitles_to_translate = []
    items_to_search = []

    for video_id, language in video_id_language_map.items():
        video = video_id_to_video_map.get(video_id)
        if not video:
            continue

        if video.subtitles is None:
            video.subtitles = []

        base_subs = [sub for sub in video.subtitles if sub.code2 in base_languages]
        external_base_subs = [sub for sub in base_subs if is_external_subtitle(sub, getattr(video, 'path', None))]

        if external_base_subs:
            if not task_queue.check({"is_serie": isinstance(video, Serie), "video_id": video_id, "to_language": language}):
                subtitles_to_translate.append(SubtitleTranslate(external_base_subs[0], language, video_id, isinstance(video, Serie)))
        else:
            series_id = getattr(video, 'sonarr_series_id', None) or getattr(video, 'series_id', None) if isinstance(video, Serie) else None
            
            if not search_task_queue.check({"is_serie": isinstance(video, Serie), "video_id": video_id}):
                items_to_search.append({
                    "video_id": video_id, 
                    "is_serie": isinstance(video, Serie),
                    "series_id": series_id
                })

    return subtitles_to_translate, items_to_search

def migration_worker(worker_id, base_url, api_key):
    headers = {"X-API-KEY": api_key}
    with httpx.Client(timeout=15) as client:
        while True:
            item = None
            try:
                item = migration_queue.get()
                media_type = item["type"]
                video_id = item["id"]
                target_profile = item["target_profile"]
                
                logger.info(f"[Migration Worker: {worker_id}] Changing {media_type} ID {video_id} to Profile {target_profile}")
                
                endpoint = f"{base_url}/api/{media_type}"
                params = {"radarrid[]": video_id} if media_type == "movies" else {"episodeid[]": video_id}
                payload = {"language_profile_id": target_profile}

                response = client.patch(endpoint, headers=headers, params=params, json=payload)
                response.raise_for_status()
                logger.info(f"[Migration Worker: {worker_id}] Profile changed successfully!")

            except Exception:
                logger.exception(f"[Migration Worker: {worker_id}] Error in profile migration:")
            finally:
                if item: migration_queue.done(item)

def translation_worker(worker_id, base_url, api_key):
    endpoint = f"{base_url}/api/subtitles"
    headers = {"X-API-KEY": api_key}
    with httpx.Client(timeout=translation_request_timeout) as client:
        while True:
            sub = None
            try:
                sub = task_queue.get()
                logger.info(f"[Translate Worker: {worker_id}] Translating: {sub.base_subtitle.path} to: {sub.to_language}")

                params = {
                    "action": "translate",
                    "language": sub.to_language,
                    "path": sub.base_subtitle.path,
                    "type": "episode" if sub.is_serie else "movie",
                    "id": sub.video_id,
                    "forced": sub.base_subtitle.forced,
                    "hi": sub.base_subtitle.hi,
                    "original_format": True,
                }
                response = client.patch(endpoint, headers=headers, params=params)
                response.raise_for_status()
                logger.info(f"[Translate Worker: {worker_id}] Translation finished")

            except Exception:
                logger.exception(f"[Translate Worker: {worker_id}] Error in translation:")
            finally:
                if sub: task_queue.done(sub)

def search_worker(worker_id, base_url, api_key):
    headers = {"X-API-KEY": api_key}
    with httpx.Client(timeout=translation_request_timeout) as client:
        while True:
            item = None
            try:
                item = search_task_queue.get()
                is_serie = item["is_serie"]
                video_id = item["video_id"]
                series_id = item.get("series_id")
                
                logger.info(f"[Search Worker: {worker_id}] Querying Providers for {'Episode' if is_serie else 'Movie'} ID: {video_id}")
                
                if is_serie:
                    get_endpoint = f"{base_url}/api/providers/episodes"
                    get_params = {"episodeid": video_id}
                else:
                    get_endpoint = f"{base_url}/api/providers/movies"
                    get_params = {"radarrid": video_id}

                get_response = client.get(get_endpoint, headers=headers, params=get_params)
                get_response.raise_for_status()
                data = get_response.json().get("data", [])
                
                candidates = [
                    c for c in data 
                    if c.get("language") in base_languages and c.get("provider") in ["embedded_subtitles", "whisperai"]
                ]
                
                if not candidates:
                    logger.info(f"[Search Worker: {worker_id}] No embedded or Whisper candidates found for ID: {video_id}")
                    continue
                    
                candidates.sort(key=lambda c: 0 if c.get("provider") == "embedded_subtitles" else 1)
                best_sub = candidates[0]
                
                logger.info(f"[Search Worker: {worker_id}] Found {best_sub['provider']} candidate. Triggering download/extraction...")
                
                if is_serie:
                    post_endpoint = f"{base_url}/api/providers/episodes"
                    post_params = {
                        "seriesid": series_id,
                        "episodeid": video_id,
                    }
                else:
                    post_endpoint = f"{base_url}/api/providers/movies"
                    post_params = {
                        "radarrid": video_id,
                    }
                    
                hi_flag = "true" if str(best_sub.get("hearing_impaired", "False")).lower() == "true" else "false"
                forced_flag = "true" if str(best_sub.get("forced", "False")).lower() == "true" else "false"

                post_params.update({
                    "hi": hi_flag,
                    "forced": forced_flag,
                    "original_format": "true",
                    "provider": best_sub.get("provider"),
                    "subtitle": best_sub.get("subtitle")
                })

                post_response = client.post(post_endpoint, headers=headers, params=post_params)
                post_response.raise_for_status()
                
                logger.info(f"[Search Worker: {worker_id}] Successfully triggered {best_sub['provider']} for ID: {video_id}")

            except Exception:
                logger.exception(f"[Search Worker: {worker_id}] Error in provider search/download:")
            finally:
                if item: search_task_queue.done(item)

async def scan_and_process(base_url, api_key, media_type="episodes"):
    logger.info(f"Scanning for {media_type}")
    if media_type == "episodes":
        items = await get_wanted_episodes(base_url, api_key)
    else:
        items = await get_wanted_movies(base_url, api_key)

    if not items:
        logger.info(f"Found no missing subtitles for {media_type}")
        return
    
    subs_to_translate, items_to_search = await find_base_language_subtitles_from_missing_sutitles(base_url, api_key, items)
    
    current_time = time.time()
    
    for sub in subs_to_translate:
        cache_key = f"trans_{sub.video_id}"
        if current_time - action_cooldown_cache.get(cache_key, 0) > ACTION_COOLDOWN_SECONDS:
            action_cooldown_cache[cache_key] = current_time
            task_queue.put(sub)
            logger.info(f"Queued Translate: {sub.base_subtitle.path} -> {sub.to_language}")

    for item in items_to_search:
        cache_key = f"search_{item['video_id']}"
        if current_time - action_cooldown_cache.get(cache_key, 0) > ACTION_COOLDOWN_SECONDS:
            action_cooldown_cache[cache_key] = current_time
            search_task_queue.put(item)
            logger.info(f"Queued Extract/Whisper check: {'Episode' if item['is_serie'] else 'Movie'} ID {item['video_id']}")

async def main(base_url, api_key):
    for i in range(num_workers):
        threading.Thread(target=translation_worker, args=(i, base_url, api_key), daemon=True).start()
        threading.Thread(target=search_worker, args=(i, base_url, api_key), daemon=True).start()
        threading.Thread(target=migration_worker, args=(i, base_url, api_key), daemon=True).start()
    
    while not shutdown_event.is_set():
        try:
            if series_scan: await scan_and_process(base_url, api_key, "episodes")
            if movies_scan: await scan_and_process(base_url, api_key, "movies")
        except Exception:
            logger.exception("Uncaught exception:")
        
        await asyncio.sleep(interval_between_scans)

def handle_shutdown():
    logger.info("Received exit signal")
    sys.exit(1)

if __name__ == "__main__":
    base_url = os.getenv("BAZARR_BASE_URL")
    api_key = os.getenv("BAZARR_API_KEY")

    if not base_url or not api_key:
        print("BAZARR_BASE_URL or BAZARR_API_KEY missing")
        sys.exit(1)

    os.makedirs(log_directory, exist_ok=True)
    file_handler = TimedRotatingFileHandler(os.path.join(log_directory, "bazarr_lingarr_autotranslate.log"), when="midnight", interval=1, backupCount=4)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(console_handler)

    logger.setLevel(logging.INFO if log_level.lower() == "info" else logging.DEBUG)

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown)
    loop.run_until_complete(main(base_url, api_key))
