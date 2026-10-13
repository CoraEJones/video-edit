"""Validate an editorial sidecar; no plan or media is modified."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from video_edit.story_decisions import Invalid, main, suggest, validate


if __name__ == '__main__':
    raise SystemExit(main())
