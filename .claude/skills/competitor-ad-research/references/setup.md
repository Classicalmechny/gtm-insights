# Setup — Competitor Ad Research toolchain

One-time install. After this, the skill runs entirely offline (no API keys).

## Required

```bash
# macOS
brew install ffmpeg yt-dlp

# Python — faster-whisper is the local transcription engine
python3 -m pip install --user faster-whisper
```

Verify:

```bash
which ffmpeg yt-dlp                                              # both paths present
python3 -c "from faster_whisper import WhisperModel; print('ok')"  # prints "ok"
```

## Model auto-download

First transcription downloads `Systran/faster-whisper-base.en` (~150 MB) to
`~/.cache/huggingface/hub/`. Subsequent runs are instant.

If you want better accuracy at the cost of ~2x runtime, swap `base.en` →
`small.en` in `scripts/transcribe_pipeline.py`. Stay on `*.en` models unless
the ads are non-English — multilingual models are slower and less accurate
on English.

## Why no OpenAI / Gemini

- No API key required → skill works on any user environment without
  credential setup.
- Whisper API would cost ~$0.006/min — negligible at 14 ads, but the local
  path keeps the skill self-contained.
- If you want to switch to OpenAI Whisper API for very large batches, the
  drop-in is in `scripts/transcribe_pipeline.py` — replace the `model.transcribe`
  block with `openai.audio.transcriptions.create(file=..., model="whisper-1")`.

## Playwright

This skill uses the Playwright MCP server already configured in the host.
No local Playwright install needed — the orchestrator (Claude) drives the
browser via the MCP tools.
