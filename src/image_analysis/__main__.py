from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

import uvicorn

from image_analysis.adapters import ServiceAuthenticator
from image_analysis.app import create_app
from image_analysis.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Local image analysis API")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--mode", choices=("cure", "cure-trufor", "cure-fused", "mock"), default="cure"
    )
    parser.add_argument("--cure-root", type=Path)
    parser.add_argument("--probe-cure-checkpoint", type=Path)
    parser.add_argument("--trufor-root", type=Path)
    parser.add_argument("--fused-weights", type=Path)
    parser.add_argument(
        "--fe-compat", action="store_true", help="Enable local FE test gateway"
    )
    args = parser.parse_args()
    if args.probe_cure_checkpoint and args.mode == "mock":
        parser.error("--probe-cure-checkpoint requires a CuRe execution mode")
    settings = Settings.from_file(args.config) if args.config else Settings()
    if args.mode == "cure-trufor":
        from image_analysis.cure import CureAdapter
        from image_analysis.trufor import TruForAdapter, dual_settings

        cure_root = args.cure_root or os.environ.get("DUNDEUNI_CURE_ROOT")
        trufor_root = args.trufor_root or os.environ.get("DUNDEUNI_TRUFOR_ROOT")
        if not cure_root or not trufor_root:
            parser.error("Set CuRe and TruFor roots through arguments or environment")
        if args.fe_compat:
            parser.error("Dual localization requires a new BE/FE response contract")
        settings = dual_settings()
        if args.config:
            settings = replace(
                settings,
                **{
                    key: value
                    for key, value in json.loads(
                        args.config.read_text(encoding="utf-8")
                    ).items()
                    if key
                    not in ("mode", "generation_only", "fe_compatibility", "probe_cure")
                },
            )
        if args.probe_cure_checkpoint:
            settings = replace(
                settings,
                probe_cure=True,
                generation_threshold=0.5,
                generation_hold_low=0.5,
                generation_hold_high=0.5,
            )
        token = os.environ.get("DUNDEUNI_AI_SERVICE_TOKEN")
        app = create_app(
            settings,
            adapters={
                "generation": (
                    CureAdapter(
                        Path(cure_root), probe_checkpoint=args.probe_cure_checkpoint
                    )
                    if args.probe_cure_checkpoint
                    else CureAdapter(Path(cure_root))
                ),
                "manipulation": TruForAdapter(Path(trufor_root)),
            },
            authenticator=ServiceAuthenticator(token) if token else None,
        )
    elif args.mode == "cure-fused":
        from image_analysis.cure import CureAdapter
        from image_analysis.fused_adapter import FusedAdapter

        token = os.environ.get("DUNDEUNI_AI_SERVICE_TOKEN")
        cure_root = args.cure_root or os.environ.get("DUNDEUNI_CURE_ROOT")
        if not token or not cure_root or not args.fused_weights or args.fe_compat:
            parser.error(
                "CuRe + FUSED requires the service token, CuRe root and FUSED weights"
            )
        settings = replace(
            settings,
            mode="CURE_FUSED",
            generation_only=False,
            hold_enabled=True,
            generation_hold_low=Settings().generation_hold_low,
            generation_hold_high=Settings().generation_hold_high,
            fe_compatibility=False,
            model_timeout_seconds=120,
            response_reserve_seconds=1,
        )
        if args.probe_cure_checkpoint:
            settings = replace(
                settings,
                probe_cure=True,
                generation_threshold=0.5,
                generation_hold_low=0.5,
                generation_hold_high=0.5,
            )
        app = create_app(
            settings,
            adapters={
                "generation": CureAdapter(
                    Path(cure_root), probe_checkpoint=args.probe_cure_checkpoint
                ),
                "manipulation": FusedAdapter(args.fused_weights),
            },
            authenticator=ServiceAuthenticator(token),
        )
    elif args.mode == "cure":
        from image_analysis.cure import CureAdapter, cure_settings

        cure_root = args.cure_root or os.environ.get("DUNDEUNI_CURE_ROOT")
        if not cure_root or not str(cure_root).strip():
            parser.error("Set --cure-root or DUNDEUNI_CURE_ROOT")
        settings = cure_settings(settings if args.config else None)
        settings = replace(settings, fe_compatibility=args.fe_compat)
        if args.probe_cure_checkpoint:
            settings = replace(
                settings,
                probe_cure=True,
                generation_threshold=0.5,
                generation_hold_low=0.5,
                generation_hold_high=0.5,
            )
        token = os.environ.get("DUNDEUNI_AI_SERVICE_TOKEN")
        app = create_app(
            settings,
            adapters={
                "generation": (
                    CureAdapter(
                        Path(cure_root), probe_checkpoint=args.probe_cure_checkpoint
                    )
                    if args.probe_cure_checkpoint
                    else CureAdapter(Path(cure_root))
                )
            },
            authenticator=ServiceAuthenticator(token) if token else None,
        )
    else:
        app = create_app(settings)
    # Single worker: admission is process-local. Never bind a public interface.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        workers=1,
        access_log=False,
        log_level="warning",
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
