"""Fetch a portable, attributed, independently sourced video test corpus.

Only Wikimedia Commons file-page licenses explicitly reporting CC0, CC BY,
CC BY-SA or public domain are accepted. Official derivatives are downloaded
unchanged; discovery tags are source metadata, never visual/speech ground truth.
No API key or third-party package is required. Network requests use bounded
retries, a descriptive User-Agent, serial API access and three download workers.
Run --help for discovery, repeatable manifest replay and full-decode verification.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "VideoEditBenchmark/1.0 (open-source evaluation; https://github.com/CoraEJones/video-edit)"
GROUPS = {
    "nature_landscape": ["waterfall", "forest", "mountain", "waves", "snow"],
    "urban_transport": ["tram", "train", "traffic", "bicycle", "market"],
    "people_events": ["festival", "parade", "walking", "dancing", "ceremony"],
    "animals": ["bird", "dog", "cat", "insect", "elephant"],
    "food_crafts": ["cooking", "bread", "pottery", "weaving", "coffee"],
    "sports_performance": ["football", "gymnastics", "surfing", "juggling", "orchestra"],
    "science_industry": ["microscopy", "factory", "robot", "experiment", "machine"],
    "underwater_night_animation": ["underwater", "coral", "fireworks", "night", "animation"],
}
LABEL_NOTICE = "Discovery group/query, title, description and categories are source metadata, not human-verified visual, speech, shot-size, motion, lighting, HDR or story ground truth."


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default


def clean_text(value):
    return html.unescape(re.sub(r"<[^>]+>", " ", str(value))).strip()


def accepted_license(metadata):
    name = clean_text(metadata.get("LicenseShortName", {}).get("value", ""))
    code = clean_text(metadata.get("License", {}).get("value", ""))
    url = metadata.get("LicenseUrl", {}).get("value", "")
    allowed = bool(re.fullmatch(r"CC BY(?:-SA)? [\d.]+", name, re.I)
                   or re.fullmatch(r"CC0(?: [\d.]+)?|Public domain", name, re.I))
    if not allowed:
        return None
    if not url and name.lower() == "public domain":
        url = "https://commons.wikimedia.org/wiki/Commons:Public_domain"
    if not url and name.upper().startswith("CC0"):
        url = "https://creativecommons.org/publicdomain/zero/1.0/"
    if not url:
        return None
    return {"license": name, "license_code": code, "license_url": url}


def choose_variant(info, max_bytes=40 * 1024 * 1024):
    duration = float(info.get("duration", 0))
    if not 5 <= duration <= 90 or info.get("mediatype") != "VIDEO":
        return None
    variants = []
    for derivative in info.get("derivatives", []):
        key = derivative.get("transcodekey", "original")
        width, height = derivative.get("width", 0), derivative.get("height", 0)
        shortest = min(width, height)
        if not 360 <= shortest <= 720 or "webm" not in derivative.get("type", ""):
            continue
        estimate = derivative.get("bandwidth", 0) * duration / 8
        if estimate > max_bytes:
            continue
        variants.append((abs(shortest - 480), estimate or max_bytes, {
            "download_url": derivative["src"], "download_variant": key,
            "expected_width": width, "expected_height": height,
            "estimated_bytes": round(estimate), "estimated_duration": duration,
        }))
    if variants:
        return min(variants, key=lambda value: (value[0], value[1]))[2]
    if (360 <= min(info.get("width", 0), info.get("height", 0)) <= 720
            and info.get("size", max_bytes + 1) <= max_bytes):
        return {"download_url": info["url"], "download_variant": "original",
                "expected_width": info["width"], "expected_height": info["height"],
                "estimated_bytes": info["size"], "estimated_duration": duration}
    return None


class CommonsAPI:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.last_request = 0.0

    def get(self, params):
        params = dict(params, action="query", format="json", formatversion="2", maxlag="5")
        query = urlencode(params)
        cache = self.cache_dir / (hashlib.sha256(query.encode()).hexdigest() + ".json")
        if cache.exists():
            return read_json(cache)
        for attempt in range(4):
            time.sleep(max(0, 0.7 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                with urlopen(Request(API + "?" + query, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
                    result = json.load(response)
                if "error" in result:
                    raise RuntimeError(str(result["error"]))
                write_json(cache, result)
                return result
            except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
                if attempt == 3:
                    raise
                wait = min(30, 2 ** (attempt + 1))
                if isinstance(error, HTTPError) and error.code == 429:
                    wait = min(60, float(error.headers.get("Retry-After", wait)))
                print(f"API retry in {wait}s: {error}", file=sys.stderr, flush=True)
                time.sleep(wait)


def discover(root, per_group, max_bytes):
    api = CommonsAPI(root / "source-api-cache")
    candidates = read_json(root / "candidates.json", [])
    used = {row["page_id"] for row in candidates}
    used_sha1 = {row["source_sha1"] for row in candidates if row.get("source_sha1")}
    completed_queries = read_json(root / "discovery-queries.json", [])
    for group, queries in GROUPS.items():
        for query in queries:
            query_id = group + ":intitle:" + query
            if query_id in completed_queries:
                continue
            search = api.get({"list": "search", "srsearch": "filetype:video intitle:" + query,
                              "srnamespace": "6", "srlimit": "50", "srprop": ""})
            hits = search.get("query", {}).get("search", [])
            for offset in range(0, len(hits), 25):
                chunk = hits[offset:offset + 25]
                result = api.get({"prop": "videoinfo", "pageids": "|".join(str(hit["pageid"]) for hit in chunk),
                                  "viprop": "url|size|dimensions|mime|mediatype|sha1|timestamp|extmetadata|derivatives"})
                for page in result.get("query", {}).get("pages", []):
                    if page.get("pageid") in used or not page.get("videoinfo"):
                        continue
                    info = page["videoinfo"][0]
                    if info.get("sha1") and info["sha1"] in used_sha1:
                        continue
                    metadata = info.get("extmetadata", {})
                    license_info = accepted_license(metadata)
                    variant = choose_variant(info, max_bytes)
                    if not license_info or not variant:
                        continue
                    candidates.append({"id": "commons-" + str(page["pageid"]), "page_id": page["pageid"],
                        "title": page["title"], "source_page": info["descriptionurl"],
                        "source_type": "Wikimedia Commons file", "source_sha1": info.get("sha1"),
                        "source_timestamp": info.get("timestamp"), "source_original_url": info["url"],
                        "source_original_bytes": info["size"], "source_original_width": info["width"],
                        "source_original_height": info["height"], "group": group, "discovery_query": query,
                        "author": clean_text(metadata.get("Artist", {}).get("value", "Unknown; see source page")),
                        "author_html": metadata.get("Artist", {}).get("value", ""),
                        "credit": clean_text(metadata.get("Credit", {}).get("value", "")),
                        "description": clean_text(metadata.get("ImageDescription", {}).get("value", "")),
                        "categories": metadata.get("Categories", {}).get("value", "").split("|"),
                        "label_provenance": LABEL_NOTICE, "discovered_at": utc_now(), **license_info, **variant})
                    used.add(page["pageid"])
                    if info.get("sha1"):
                        used_sha1.add(info["sha1"])
                write_json(root / "candidates.json", candidates)
            completed_queries.append(query_id)
            write_json(root / "discovery-queries.json", completed_queries)
            print(f"Discovered {group}: {sum(row['group'] == group for row in candidates)} candidates", file=sys.stderr, flush=True)
    return candidates


def safe_relative(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Manifest path escapes corpus directory")
    return path


def hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_and_decode(path, ffprobe, ffmpeg):
    result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    probed = json.loads(result.stdout)
    streams = probed.get("streams", [])
    video = [stream for stream in streams if stream.get("codec_type") == "video"]
    duration = float(probed.get("format", {}).get("duration", 0))
    if not video or not 4.9 <= duration <= 90.5:
        raise ValueError("Downloaded video duration outside 5–90 seconds")
    # WebM/Ogg already carry packet boundaries. Disable the optional elementary
    # parser, which some FFmpeg versions flush with an empty Opus packet at EOF.
    # Actual video/audio decoders still consume the complete file with -xerror.
    command = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-threads", "1",
               "-fflags", "+noparse+nofillin",
               "-i", str(path), "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"]
    checked = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=max(60, duration * 5))
    if checked.returncode != 0 or checked.stderr.strip():
        raise ValueError("Full decode failed: " + checked.stderr[-2000:])
    probed.get("format", {}).pop("filename", None)
    return probed


def download_one(root, row, ffprobe, ffmpeg, max_bytes):
    if urlparse(row["download_url"]).scheme != "https" or urlparse(row["download_url"]).hostname != "upload.wikimedia.org":
        raise ValueError("Only HTTPS Wikimedia official media URLs are accepted")
    suffix = Path(urlparse(row["download_url"]).path).suffix.lower()
    if suffix not in (".webm", ".ogv", ".ogg", ".mp4", ".mov"):
        raise ValueError("Unexpected video extension")
    relative = "media/" + row["group"] + "/" + row["id"] + suffix
    final = safe_relative(root, relative)
    metadata_path = root / "items" / (row["id"] + ".json")
    previous = read_json(metadata_path)
    if previous and final.exists() and final.stat().st_size == previous.get("bytes") and hash_file(final) == previous.get("sha256"):
        if row.get("sha256") and row["sha256"] != previous["sha256"]:
            raise ValueError("Existing item bytes differ from pinned manifest")
        return previous
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise ValueError("Existing unverified file; refusing to overwrite: " + relative)
    partial = final.with_suffix(final.suffix + ".part")
    for attempt in range(3):
        try:
            count = 0
            with urlopen(Request(row["download_url"], headers={"User-Agent": USER_AGENT}), timeout=90) as response:
                expected = int(response.headers.get("Content-Length", 0))
                if expected > max_bytes:
                    raise ValueError("Content-Length exceeds per-file size budget")
                with partial.open("wb") as target:
                    while True:
                        block = response.read(256 * 1024)
                        if not block:
                            break
                        count += len(block)
                        if count > max_bytes:
                            raise ValueError("Download exceeds per-file size budget")
                        target.write(block)
            if not count or (expected and count != expected):
                raise ValueError("Incomplete HTTP body")
            probe = probe_and_decode(partial, ffprobe, ffmpeg)
            digest = hash_file(partial)
            if row.get("sha256") and row["sha256"] != digest:
                raise ValueError("Pinned manifest SHA-256 differs; source bytes changed")
            partial.replace(final)
            completed = dict(row, relative_path=relative, bytes=count, sha256=digest, ffprobe=probe,
                             full_decode={"status": "passed", "checked_at": utc_now(), "all_video_frames_and_audio": True,
                                          "demuxer_flags": "+noparse+nofillin", "ffmpeg_error_policy": "-xerror; reject nonempty error log"},
                             downloaded_at=utc_now())
            write_json(metadata_path, completed)
            return completed
        except (HTTPError, URLError, TimeoutError, ValueError, subprocess.SubprocessError, OSError) as error:
            partial.unlink(missing_ok=True)
            if attempt == 2:
                raise
            wait = 2 ** (attempt + 1)
            if isinstance(error, HTTPError) and error.code == 429:
                wait = min(60, float(error.headers.get("Retry-After", wait)))
            time.sleep(wait)


def summary(rows):
    durations = [float(row["ffprobe"].get("format", {}).get("duration", 0)) for row in rows]
    audio_count = sum(any(stream.get("codec_type") == "audio" for stream in row["ffprobe"]["streams"]) for row in rows)
    videos = [next(stream for stream in row["ffprobe"]["streams"] if stream.get("codec_type") == "video") for row in rows]
    return {"file_count": len(rows), "unique_source_pages": len({row["page_id"] for row in rows}),
            "unique_sha256": len({row["sha256"] for row in rows}), "total_bytes": sum(row["bytes"] for row in rows),
            "total_duration_seconds": round(sum(durations), 3), "with_audio_stream": audio_count,
            "duration_min_seconds": round(min(durations), 3) if durations else None,
            "duration_max_seconds": round(max(durations), 3) if durations else None,
            "without_audio_stream": len(rows) - audio_count, "groups": dict(Counter(row["group"] for row in rows)),
            "licenses": dict(Counter(row["license"] for row in rows)),
            "video_codecs": dict(Counter(stream.get("codec_name", "unknown") for stream in videos)),
            "video_dimensions": dict(Counter(f"{stream.get('width')}x{stream.get('height')}" for stream in videos)),
            "pixel_formats": dict(Counter(stream.get("pix_fmt", "unknown") for stream in videos)),
            "color_transfer_metadata": dict(Counter(stream.get("color_transfer", "unspecified") for stream in videos)),
            "color_primaries_metadata": dict(Counter(stream.get("color_primaries", "unspecified") for stream in videos)),
            "average_frame_rate_rationals": dict(Counter(stream.get("avg_frame_rate", "unknown") for stream in videos)),
            "label_notice": LABEL_NOTICE, "speech_listening_and_visual_ground_truth": "not yet annotated",
            "full_decode_passed": sum(row.get("full_decode", {}).get("status") == "passed" for row in rows)}


def source_work_key(row):
    """Conservatively collapse named parts/alternate encodes; not a content ID."""
    title = Path(row["title"].removeprefix("File:")).stem.lower()
    svs = re.search(r"\bsvs[ _-]?(\d+)", title)
    if svs:
        return "nasa-svs-" + svs.group(1)
    title = re.sub(r"\(cira.*", "", title)
    title = re.sub(r"\(\d+\)$", "", title).strip()
    title = re.sub(r"(?:movie|video|part|clip|s)[ _.-]*\d+", "", title)
    title = re.sub(r"[ _.-]+\d{1,3}$", "", title)
    title = re.sub(r"\b(?:caption|clean|labels|nolabels|portrait|9x16|16x9|\d{3,4}p\d*)\b", "", title)
    return re.sub(r"[\W_]+", "", title)


def fits_discovery_group(row):
    """Remove obvious metadata false positives; this is not visual annotation."""
    if row["group"] in ("science_industry", "underwater_night_animation"):
        return True
    title = row["title"].lower()
    if re.search(r"\bcira\b|\bsvs\d+\b|visuali[sz]ation|simulation|animation|gravity waves|lunar|nymph of the waves|satellite|forest.?arrows|wp25|wikipedia 25", title):
        return False
    if row["group"] == "nature_landscape" and re.search(r"mountain division|soldier|smokejumper|hot spring suite|snow white|snow.?globe|forest service career|engineer shares|forest rally", title):
        return False
    if row["group"] == "urban_transport" and re.search(r"chemical|experiment|swarm example|traffic.?light reaction", title):
        return False
    if row["group"] == "people_events" and re.search(r"peacock|dancing lights|\bdog\b|\bcat\b|\bhorse\b|\bbird\b", title):
        return False
    if row["group"] == "food_crafts" and re.search(r"spider|nephila|hen.?&.?chicks|chicks eating|weaver bird|bird weaving", title):
        return False
    if row["group"] == "sports_performance" and re.search(r"microct|macromolecular|ubiquitylation", title):
        return False
    return True


def balanced_pool(candidates, group):
    queues = {}
    for row in candidates:
        if row["group"] == group and fits_discovery_group(row):
            queues.setdefault(row["discovery_query"], []).append(row)
    result = []
    while any(queues.values()):
        for queue in queues.values():
            if queue:
                result.append(queue.pop(0))
    return result


def download_corpus(root, candidates, per_group, ffprobe, ffmpeg, max_bytes, total_bytes):
    rows = read_json(root / "manifest.json", [])
    pinned = bool(candidates) and all(row.get("sha256") for row in candidates)
    pinned_hashes = {row["page_id"]: row["sha256"] for row in candidates} if pinned else {}
    if pinned and not {row["page_id"] for row in rows}.issubset({row["page_id"] for row in candidates}):
        raise ValueError("Replay output already contains a different corpus")
    for row in rows:
        if pinned and row["sha256"] != pinned_hashes[row["page_id"]]:
            raise ValueError("Existing corpus bytes differ from pinned manifest")
        media = safe_relative(root, row["relative_path"])
        if not media.is_file() or media.stat().st_size != row["bytes"] or hash_file(media) != row["sha256"]:
            raise ValueError("Existing manifest entry is missing or corrupt: " + row["id"])
    source_ids = {row["page_id"] for row in rows}
    hashes = {row["sha256"] for row in rows}
    work_keys = {source_work_key(row) for row in rows}
    # Recover completed items after an interrupted checkpoint without redownloading.
    for path in sorted((root / "items").glob("*.json")) if (root / "items").exists() else []:
        row = read_json(path)
        if row["page_id"] not in source_ids and row["sha256"] not in hashes:
            if pinned and row["sha256"] != pinned_hashes.get(row["page_id"]):
                raise ValueError("Recovered item bytes differ from pinned manifest")
            media = safe_relative(root, row["relative_path"])
            if media.is_file() and hash_file(media) == row["sha256"]:
                rows.append(row); source_ids.add(row["page_id"]); hashes.add(row["sha256"]); work_keys.add(source_work_key(row))
    failures = read_json(root / "download-failures.json", [])
    attempted = {entry["id"] for entry in failures}
    for group in GROUPS:
        ordered = [row for row in candidates if row["group"] == group] if pinned else balanced_pool(candidates, group)
        pool = [row for row in ordered if row["page_id"] not in source_ids and row["id"] not in attempted]
        while sum(row["group"] == group for row in rows) < per_group and pool:
            author_counts = Counter(row["author"] for row in rows if row["group"] == group)
            if not pinned:
                pool = [row for row in pool if source_work_key(row) not in work_keys and author_counts[row["author"]] < max(5, per_group // 5)]
            if not pool:
                break
            needed = per_group - sum(row["group"] == group for row in rows)
            batch = []
            batch_keys = set()
            while pool and len(batch) < min(3, needed):
                row = pool.pop(0)
                key = source_work_key(row)
                if not pinned and (key in batch_keys or author_counts[row["author"]] >= max(5, per_group // 5)):
                    continue
                batch.append(row); batch_keys.add(key); author_counts[row["author"]] += 1
            if sum(row["bytes"] for row in rows) + len(batch) * max_bytes > total_bytes:
                raise ValueError("Storage budget reached (including in-flight maximum)")
            with ThreadPoolExecutor(max_workers=3) as workers:
                futures = {workers.submit(download_one, root, row, ffprobe, ffmpeg, max_bytes): row for row in batch}
                for future in as_completed(futures):
                    row = futures[future]
                    try:
                        completed = future.result()
                        if completed["sha256"] in hashes:
                            # This file belongs to this downloader invocation.
                            safe_relative(root, completed["relative_path"]).unlink()
                            (root / "items" / (completed["id"] + ".json")).unlink()
                            raise ValueError("Duplicate downloaded content")
                        if not pinned and source_work_key(completed) in work_keys:
                            safe_relative(root, completed["relative_path"]).unlink()
                            (root / "items" / (completed["id"] + ".json")).unlink()
                            raise ValueError("Alternate part/encode from an already selected named source work")
                        rows.append(completed); source_ids.add(row["page_id"]); hashes.add(completed["sha256"])
                        work_keys.add(source_work_key(completed))
                        write_json(root / "manifest.json", rows)
                        write_json(root / "summary.json", summary(rows))
                        print(f"Downloaded/decoded {len(rows)}: {group} {completed['title']} ({completed['bytes']} bytes)", file=sys.stderr, flush=True)
                    except Exception as error:
                        failures.append({"id": row["id"], "title": row["title"], "error": str(error), "at": utc_now()})
                        write_json(root / "download-failures.json", failures)
                        print(f"Skipped {row['title']}: {error}", file=sys.stderr, flush=True)
    return rows


def verify(root, ffprobe, ffmpeg):
    def check(row):
        try:
            path = safe_relative(root, row["relative_path"])
            if path.stat().st_size != row["bytes"] or hash_file(path) != row["sha256"]:
                raise ValueError("Size or SHA-256 mismatch")
            probe_and_decode(path, ffprobe, ffmpeg)
            return {"id": row["id"], "status": "passed"}
        except Exception as error:
            return {"id": row["id"], "status": "failed", "error": str(error)}
    rows = read_json(root / "manifest.json", [])
    results = []
    with ThreadPoolExecutor(max_workers=3) as workers:
        for result in workers.map(check, rows):
            results.append(result)
            if len(results) % 25 == 0:
                print(f"Hash/full-decode verified {len(results)}/{len(rows)}", file=sys.stderr, flush=True)
    report = {"checked_at": utc_now(), "checked": len(results), "failed": sum(row["status"] != "passed" for row in results), "results": results}
    write_json(root / "verification.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("all", "discover", "download", "replay", "verify"), default="all")
    parser.add_argument("--input-manifest", type=Path, help="With --mode replay, download these exact pinned sources without querying search")
    parser.add_argument("--per-group", type=int, default=25)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--max-file-mib", type=int, default=40)
    parser.add_argument("--max-total-gib", type=float, default=4.0)
    args = parser.parse_args()
    if not 1 <= args.per_group <= 100:
        parser.error("--per-group must be 1–100")
    root = args.output.resolve(); root.mkdir(parents=True, exist_ok=True)
    if not (root / "corpus-metadata.json").exists():
        versions = {}
        for name, binary in (("ffmpeg", args.ffmpeg), ("ffprobe", args.ffprobe)):
            try:
                versions[name] = subprocess.run([binary, "-version"], check=True, capture_output=True,
                                                text=True, encoding="utf-8", errors="replace", timeout=15).stdout.splitlines()[0]
            except (OSError, subprocess.SubprocessError):
                versions[name] = "unavailable (required for download/verify, not discovery)"
        write_json(root / "corpus-metadata.json", {"schema_version": 1, "created_at": utc_now(),
            "source": "Wikimedia Commons MediaWiki API and official original/transcode media URLs",
            "selection": "Round robin across source-title discovery topics; unique page IDs, source SHA-1 and downloaded SHA-256; conservative named-part collapse; author cap per group.",
            "selection_mode": "pinned_manifest" if args.mode == "replay" else "discovery",
            "requested_groups": GROUPS, "requested_per_group": args.per_group,
            "max_file_bytes": args.max_file_mib * 1024 ** 2, "max_total_bytes": int(args.max_total_gib * 1024 ** 3),
            "license_policy": "Explicit per-file CC0, CC BY, CC BY-SA or public-domain metadata only",
            "label_notice": LABEL_NOTICE, "tools": versions})
    candidates = read_json(root / "candidates.json", [])
    if args.mode == "replay":
        if not args.input_manifest or not args.input_manifest.is_file():
            parser.error("--mode replay requires --input-manifest")
        candidates = read_json(args.input_manifest)
        if not isinstance(candidates, list) or not candidates:
            parser.error("Pinned manifest must be a nonempty list")
        for row in candidates:
            permission = accepted_license({"LicenseShortName": {"value": row.get("license", "")},
                                           "LicenseUrl": {"value": row.get("license_url", "")}})
            if row.get("group") not in GROUPS or not row.get("sha256") or not permission:
                parser.error("Pinned manifest contains unsupported group, missing hash or unacceptable license")
        write_json(root / "candidates.json", candidates)
    if args.mode in ("all", "discover"):
        candidates = discover(root, args.per_group, args.max_file_mib * 1024 ** 2)
    if args.mode in ("all", "download", "replay"):
        rows = download_corpus(root, candidates, args.per_group, args.ffprobe, args.ffmpeg,
                               args.max_file_mib * 1024 ** 2, args.max_total_gib * 1024 ** 3)
        report = summary(rows)
        write_json(root / "summary.json", report)
        print(json.dumps(report, ensure_ascii=False))
        if len(rows) < len(GROUPS) * args.per_group:
            return 2
    elif args.mode == "verify":
        report = verify(root, args.ffprobe, args.ffmpeg)
        print(json.dumps(report, ensure_ascii=False))
        if report["failed"]:
            return 2
    else:
        print(json.dumps({"candidate_count": len(candidates), "groups": dict(Counter(row["group"] for row in candidates))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
