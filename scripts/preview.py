"""Render an SVG of the actual TUI with synthetic data; never live conversations."""

import asyncio
import re
from pathlib import Path

from kaka.app import Composer, KakaApp
from kaka.backends.demo import DemoBackend

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    app = KakaApp(DemoBackend(auto_reply=False), demo=True, poll_interval=60)
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        await app.select_room("102")
        app.query_one("#composer", Composer).load_text("네, 여기서 바로 답장할 수 있어요.")
        await pilot.pause()
        svg = app.export_screenshot()
        # A README preview should not fetch third-party fonts when it is opened.
        svg = re.sub(r"@font-face\s*\{.*?\}", "", svg, flags=re.DOTALL)
        svg = svg.replace(
            "Fira Code, monospace", 'Consolas, "D2Coding", "Malgun Gothic", monospace'
        )
        svg = "\n".join(line.rstrip() for line in svg.splitlines()) + "\n"
        await asyncio.to_thread((ROOT / "docs" / "preview.svg").write_text, svg, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
