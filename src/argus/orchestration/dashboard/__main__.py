"""Launch with python -m argus.orchestration.dashboard [Streamlit options]."""

import sys
from pathlib import Path

if __name__ == "__main__":
    from streamlit.web import cli

    sys.argv = [
        "streamlit",
        "run",
        str(Path(__file__).with_name("app.py")),
        "--server.address",
        "127.0.0.1",
        *sys.argv[1:],
    ]
    raise SystemExit(cli.main())
