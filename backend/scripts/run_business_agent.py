"""Start API or Worker with the same explicit business Agent integration configuration."""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    """Load the dedicated local env and run selected api/worker role; fail on missing configuration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["api", "worker"])
    parser.add_argument("--port", type=int, default=8013)
    args = parser.parse_args()
    env_file = ROOT / ".env.business-agent"
    if not env_file.is_file():
        raise RuntimeError("Configure backend/.env.business-agent using docs/BUSINESS_AGENT_SHOWCASE.md")
    load_dotenv(env_file, override=True)
    if args.role == "api":
        import uvicorn
        uvicorn.run("app.main:app", host="0.0.0.0", port=args.port)
    else:
        from app.worker import main as worker_main
        worker_main()


if __name__ == "__main__":
    main()
