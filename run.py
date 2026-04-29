"""RAMIP orchestrator: load env, then run the pipeline end to end."""
from dotenv import load_dotenv

import cluster
import fetch
import format as format_module
import score
import send


def main() -> None:
    load_dotenv()
    fetch.main()
    score.main()
    cluster.main()
    format_module.main()
    send.main()


if __name__ == "__main__":
    main()
