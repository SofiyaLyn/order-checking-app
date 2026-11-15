"""Start the local HTML application with bundled Python dependencies."""
import sys
from pathlib import Path

def configure():
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required. Install Python, then open this launcher again.")
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "vendor"))
    return root

def main(argv=None):
    configure()
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check-setup" in args:
        import openpyxl
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Vienna")
        print("Setup OK. Bundled Excel reader and timezone data are available.")
        return 0
    from local_app import main as start
    return start(args)

if __name__ == "__main__":
    raise SystemExit(main())

