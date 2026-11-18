"""Command-line pipeline.

    python -m caribou fetch          # download all open data (~2.5 GB)
    python -m caribou prepare        # clean + reproject into data/interim
    python -m caribou pixels         # rasterize each range into a pixel-class table
    python -m caribou vector         # exact vector shares of the official layers
    python -m caribou analyze        # scorecard, split, recovery, forecast tables
    python -m caribou figures        # poster and manuscript figures
    python -m caribou report         # refresh the results section of README.md
    python -m caribou all            # everything above, in order

Options: --res (metres, default 100), --alt-res (extra resolutions for the
band), --workers, --codes (subset of range codes), --new-human (name of an
extra mask column from the detector).
"""

from __future__ import annotations

import argparse
import json
import time

from . import config as C


def main(argv=None):
    p = argparse.ArgumentParser(prog="caribou", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("steps", nargs="+",
                   choices=["fetch", "prepare", "pixels", "vector", "analyze", "figures",
                            "report", "all"])
    p.add_argument("--res", type=float, default=C.DEFAULT_RES)
    p.add_argument("--alt-res", type=float, nargs="*", default=[250.0])
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--codes", nargs="*")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--new-human", default=None,
                   help="interim layer with detector clearings, buffered 500 m")
    a = p.parse_args(argv)
    steps = ["fetch", "prepare", "pixels", "vector", "analyze", "figures", "report"] \
        if "all" in a.steps else a.steps

    extras = {"new_h": a.new_human} if a.new_human else None
    tag = "_det" if a.new_human else ""
    nh = "new_h" if a.new_human else None

    for step in steps:
        t0 = time.time()
        print(f"=== {step}")
        if step == "fetch":
            from .fetch import fetch_all
            fetch_all()
        elif step == "prepare":
            from .prepare import prepare_all
            prepare_all()
        elif step == "pixels":
            from .pixels import build_all
            for res in [a.res, *a.alt_res]:
                build_all(res, a.workers, a.codes, extras=extras if res == a.res else None,
                          tag=tag if res == a.res else "", overwrite=a.overwrite)
        elif step == "vector":
            from .scorecard import vector_reproduction
            vector_reproduction(a.workers)
        elif step == "analyze":
            from .forecast import build_forecast
            from .recovery import build_recovery, build_split
            from .scorecard import build_scorecard, summarize
            sc = build_scorecard(a.res, a.alt_res, nh, tag)
            summary = summarize(sc)
            (C.TABLES / f"summary{tag}.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps(summary, indent=2))
            build_split(sc)
            build_recovery(a.res, nh, tag=tag)
            # with the detector, the post-2020 footprint is mapped (no catch-up) and
            # its 2020-2025 pace becomes the forward rate
            rate = (sc.set_index("CODE")["new_industry"] / (C.UPDATE_YEAR - C.BASELINE_YEAR)
                    if nh else None)
            build_forecast(a.res, nh, new_human_rate=rate, tag=tag)
        elif step == "figures":
            from .figures import make_all
            make_all(tag)
        elif step == "report":
            from .report import update_readme
            update_readme(tag)
        print(f"=== {step} done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
