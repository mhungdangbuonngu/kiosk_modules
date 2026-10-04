from __future__ import annotations

import argparse
import json
import logging

import uvicorn

from .calibration import calibrate_file
from .config import load_config
from .doctor import installation_report
from .replay import replay_jsonl
from .service import create_app
from .visual_calibration import run_visual_calibration


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="kiosk-vision")
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-config")
    validate.add_argument("config", nargs="?", default="config/kiosk.video.yaml")
    serve = commands.add_parser("serve")
    serve.add_argument("config", nargs="?", default="config/kiosk.video.yaml")
    serve.add_argument("--development-tracker", action="store_true")
    serve.add_argument("--preview", action="store_true",
                       help="show a local annotated live camera window")
    serve.add_argument("--record-preview", metavar="OUTPUT.mp4",
                       help="save annotated preview video; Ctrl+C finalizes the MP4")
    replay = commands.add_parser("replay")
    replay.add_argument("config")
    replay.add_argument("observations")
    calibrate = commands.add_parser("calibrate")
    calibrate.add_argument("correspondences")
    calibrate.add_argument("output")
    visual = commands.add_parser(
        "calibrate-visual",
        help="calibrate from a live camera preview with projected zone overlays",
    )
    visual.add_argument("config", nargs="?", default="config/kiosk.video.yaml")
    visual.add_argument("--output")
    visual.add_argument("--correspondences")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("config", nargs="?", default="config/kiosk.video.yaml")
    doctor.add_argument("--camera", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "calibrate":
        calibrate_file(args.correspondences, args.output)
        return
    config, checksum = load_config(args.config)
    if args.command == "validate-config":
        print(json.dumps({"valid": True, "checksum": checksum}))
    elif args.command == "doctor":
        report = installation_report(config, args.camera)
        print(json.dumps(report, indent=2))
        if not report["ok"]:
            raise SystemExit(1)
    elif args.command == "replay":
        for event in replay_jsonl(config, args.observations):
            print(json.dumps(event))
    elif args.command == "calibrate-visual":
        run_visual_calibration(config, args.config, args.output, args.correspondences)
    elif args.command == "serve":
        logging.basicConfig(level=config.service.log_level,
                            format="%(asctime)s %(levelname)s %(name)s %(message)s")
        app = create_app(config, checksum, run_vision=True,
                         development_tracker=args.development_tracker,
                         preview=args.preview, record_preview=args.record_preview)
        uvicorn.run(app, host=config.service.host, port=config.service.port)


if __name__ == "__main__":
    main()
