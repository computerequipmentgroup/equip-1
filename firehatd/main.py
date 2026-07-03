from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("FIREHAT_HOST", "0.0.0.0")
    port = int(os.environ.get("FIREHAT_PORT", "8000"))
    uvicorn.run("firehatd.api:app", host=host, port=port)


if __name__ == "__main__":
    main()
