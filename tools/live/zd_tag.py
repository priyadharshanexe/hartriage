"""Tag a live Zendesk ticket and wait until HAR Triage has handled it.

uv run python -m tools.live.zd_tag <ticket id> [timeout seconds]
"""

from __future__ import annotations

import sys
import time

from tools.live.zd_setup import zendesk


def main() -> None:
    tid, limit = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 180
    with zendesk() as z:
        r = z.put(f"/api/v2/tickets/{tid}/tags.json", json={"tags": ["har_analyze"]})
        print("tag:", r.status_code)
        start = time.time()
        while time.time() - start < limit:
            time.sleep(5)
            tags = z.get(f"/api/v2/tickets/{tid}.json").json()["ticket"]["tags"]
            if "har_analyze" not in tags:
                print(f"handled after {time.time() - start:.0f}s, tags {tags}")
                break
        else:
            print("not handled within", limit, "s")
        for c in z.get(f"/api/v2/tickets/{tid}/comments.json").json()["comments"]:
            files = [(a["file_name"], a["size"]) for a in c["attachments"]]
            print(
                "comment",
                c["id"],
                "public" if c["public"] else "private",
                files,
                c["body"][:70].replace("\n", " "),
            )


if __name__ == "__main__":
    main()
