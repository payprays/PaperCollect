import argparse

from src.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PaperCollect web UI.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind")
    args = parser.parse_args()

    app = create_app(args.config)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
