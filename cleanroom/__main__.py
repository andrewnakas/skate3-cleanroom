"""n64cleanrecomp command line.

    python -m cleanroom extract <game> <retail rom>      # dirty room: write spec/
    python -m cleanroom build <game> [--out F] [--code BIN | --code-from-retail ROM]
    python -m cleanroom taint <game> <retail rom> <clean image>
    python -m cleanroom preview <game> <image> [out_dir]
    python -m cleanroom briefs <game> [out_dir]           # authoring briefs for overrides
"""
import importlib
import sys


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd, game, rest = argv[1], argv[2], argv[3:]
    pkg = f"games.{game}"
    if cmd == "extract":
        importlib.import_module(pkg + ".extract_spec").main([None] + rest)
    elif cmd == "build":
        importlib.import_module(pkg + ".pack").main(rest)
    elif cmd == "taint":
        importlib.import_module(pkg + ".taint_report").main([None] + rest)
    elif cmd == "preview":
        importlib.import_module(pkg + ".preview").main([None] + (rest if len(rest) > 1 else rest + ["build/preview"]))
    elif cmd == "briefs":
        importlib.import_module(pkg + ".briefs").main([None] + rest)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
