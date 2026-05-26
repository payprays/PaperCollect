import argparse
import os

from src.web import create_app


def create_wsgi_app():
    return create_app(os.environ.get("PAPERCOLLECT_CONFIG", "config.yaml"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the PaperCollect web UI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind")
    parser.add_argument(
        "--no-threaded",
        action="store_true",
        help="Disable Flask dev server threading.",
    )
    args = parser.parse_args()

    app = create_app(args.config)
    app.run(host=args.host, port=args.port, threaded=not args.no_threaded)


if __name__ == "__main__":
    main()
