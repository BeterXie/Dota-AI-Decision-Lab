import argparse
import json
from pathlib import Path
from uuid import UUID

from app.replay import RecordedEvent, ReplayHarness


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a recorded provider timeline offline")
    parser.add_argument("timeline", type=Path)
    parser.add_argument("--canonical-map-id", required=True, type=UUID)
    parser.add_argument("--valve-match-id", required=True, type=int)
    parser.add_argument("--restart-after", type=int)
    args = parser.parse_args()

    payload = json.loads(args.timeline.read_text(encoding="utf-8"))
    events = [RecordedEvent.model_validate(item) for item in payload]
    result = ReplayHarness(
        args.canonical_map_id,
        valve_match_id=args.valve_match_id,
    ).replay(events, restart_after=args.restart_after)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
