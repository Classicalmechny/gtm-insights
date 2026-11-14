#!/usr/bin/env python3
"""
Download Meta Ad Library video creatives from metadata.json and transcribe them
with faster-whisper. Entirely local — no API keys.

USAGE
  python3 transcribe_pipeline.py <workdir>

Where <workdir> contains metadata.json (produced by scrape_ad_library.py)
and where videos/, audio/, transcripts/ will be created.

REQUIREMENTS
  brew install ffmpeg yt-dlp
  python3 -m pip install --user faster-whisper

The faster-whisper base.en model auto-downloads (~150 MB) on first run.
"""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605 Safari/605"

def download_one(ad: dict, vid_dir: Path) -> tuple[str, str, Path | None]:
    out = vid_dir / f"{ad['library_id']}.mp4"
    if out.exists() and out.stat().st_size > 50_000:
        return ad["library_id"], "cached", out
    if not ad.get("video_url"):
        return ad["library_id"], "no_video_url", None
    r = subprocess.run(
        ["curl", "-sSL", "--fail", "--max-time", "60", "-A", UA,
         "-o", str(out), ad["video_url"]],
        capture_output=True, text=True
    )
    if r.returncode != 0 or not out.exists() or out.stat().st_size < 10_000:
        return ad["library_id"], f"FAIL: {r.stderr[:200]}", None
    return ad["library_id"], "downloaded", out

def extract_audio(video_path: Path, aud_dir: Path) -> Path:
    aud = aud_dir / f"{video_path.stem}.wav"
    if aud.exists() and aud.stat().st_size > 1000:
        return aud
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
         "-ac", "1", "-ar", "16000", "-vn", str(aud)],
        check=True
    )
    return aud

def main(workdir: Path) -> None:
    meta = json.loads((workdir / "metadata.json").read_text())
    vid_dir = workdir / "videos"
    aud_dir = workdir / "audio"
    txt_dir = workdir / "transcripts"
    for d in (vid_dir, aud_dir, txt_dir):
        d.mkdir(parents=True, exist_ok=True)

    ads_with_video = [a for a in meta["ads"] if a.get("video_url")]
    print(f"Downloading {len(ads_with_video)} videos in parallel (6 workers)...")
    t0 = time.time()
    paths = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(download_one, a, vid_dir): a for a in ads_with_video}
        for f in as_completed(futures):
            lid, status, p = f.result()
            print(f"  {lid}: {status}")
            if p is not None:
                paths.append((lid, p))
    print(f"Downloads: {len(paths)}/{len(ads_with_video)} ok in {time.time()-t0:.1f}s")

    print("Extracting audio with ffmpeg...")
    audios = []
    for lid, vp in paths:
        try:
            audios.append((lid, extract_audio(vp, aud_dir)))
        except subprocess.CalledProcessError:
            print(f"  {lid}: audio extract FAILED")
    print(f"Audio ready for {len(audios)} clips")

    print("Loading faster-whisper base.en (CPU int8)...")
    from faster_whisper import WhisperModel
    model = WhisperModel("base.en", device="cpu", compute_type="int8")

    for lid, ap in audios:
        out_txt = txt_dir / f"{lid}.txt"
        if out_txt.exists() and out_txt.stat().st_size > 0:
            print(f"  {lid}: cached")
            continue
        t1 = time.time()
        segments, _ = model.transcribe(str(ap), beam_size=5,
                                       language="en", vad_filter=True)
        lines = []
        for seg in segments:
            ts = f"[{int(seg.start//60):02d}:{int(seg.start%60):02d}]"
            lines.append(f"{ts} {seg.text.strip()}")
        out_txt.write_text("\n".join(lines) + "\n")
        print(f"  {lid}: {len(lines)} segments, {time.time()-t1:.1f}s")

    print("Done. Transcripts in", txt_dir)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: transcribe_pipeline.py <workdir>")
        sys.exit(1)
    main(Path(sys.argv[1]).expanduser().resolve())
