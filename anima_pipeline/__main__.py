"""Run local generation with ``python -m anima_pipeline custom|auto``."""

import argparse
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("custom", "auto"):
        if argv[0] == "custom":
            from anima_pipeline.cli.custom_entry import main as run
        else:
            from anima_pipeline.cli.pipeline_character import main as run
        return run(argv[1:])
    parser = argparse.ArgumentParser(description="Anima 本地出图入口。")
    parser.add_argument("mode", choices=("custom", "auto"), help="custom：自选菜单；auto：自动选角")
    parser.parse_args(argv)


if __name__ == "__main__":
    main()
