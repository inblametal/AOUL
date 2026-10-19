#!/usr/bin/env python3
"""
RoboSage Application Launcher.
Starts the RoboSage Web Application Dashboard or launches the CLI.

Usage:
    python3 run.py                 # Launch Web Application & open browser
    python3 run.py --port 9000     # Run on custom port
    python3 run.py --no-browser    # Run server without opening browser
    python3 run.py --cli           # Run terminal CLI interactive assistant
"""

import argparse
import os
import sys
import threading
import time
import webbrowser

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from robosage.cli import Colors, print_banner
from robosage.server import start_server


def open_browser(url: str, delay_sec: float = 0.8):
    """Opens browser or native desktop window after server starts."""
    time.sleep(delay_sec)
    if sys.platform == "win32":
        import subprocess
        for browser_path in [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        ]:
            if os.path.exists(browser_path):
                try:
                    subprocess.Popen([browser_path, f"--app={url}"])
                    return
                except Exception:
                    pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="RoboSage: AI Senior Robotics Assistant & Safety Copilot Application",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to run the application server on (default: 8765)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind the server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the browser",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Launch the interactive terminal CLI instead of the web dashboard",
    )

    args, unknown = parser.parse_known_args()

    if args.cli:
        from robosage.cli import main as cli_main
        sys.argv = [sys.argv[0]] + unknown
        cli_main()
        return

    url = f"http://{args.host}:{args.port}/"

    print_banner()
    print(f"  {Colors.BOLD}{Colors.GREEN}► Starting RoboSage Desktop Web Application...{Colors.RESET}")
    print(f"  {Colors.BOLD}► Dashboard URL:{Colors.RESET} {Colors.CYAN}{Colors.UNDERLINE}{url}{Colors.RESET}")
    print(f"  {Colors.BOLD}► Press {Colors.RED}Ctrl+C{Colors.RESET} to stop the server.{Colors.RESET}\n")

    if not args.no_browser:
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    try:
        start_server(host=args.host, port=args.port)
    except KeyboardInterrupt:
        print(f"\n{Colors.GREEN}RoboSage application shutdown gracefully.{Colors.RESET}")


if __name__ == "__main__":
    main()
