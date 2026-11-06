from __future__ import annotations

import argparse
import asyncio
import math
import os
from pathlib import Path

from kaka import __version__
from kaka.backends import BackendError


def interval(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.5:
        raise argparse.ArgumentTypeError("조회 간격은 0.5초 이상이어야 합니다.")
    return number


def default_engine() -> Path:
    if value := os.environ.get("KAKA_ENGINE_PATH"):
        return Path(value).expanduser()
    # An editable install / git checkout finds its sibling .engine regardless of cwd.
    for parent in Path(__file__).resolve().parents:
        if (parent / "engine.lock.json").is_file():
            return parent / ".engine" / "nichirin"
    return Path.cwd() / ".engine" / "nichirin"


async def doctor(backend) -> int:
    try:
        status = await backend.status()
        if status.get("running") is False:
            print("카카오톡이 실행되지 않았습니다. 로그인한 뒤 다시 실행하세요.")
            return 1
        # Only aggregate status. Never dump room titles or decrypted conversation data.
        print("연동 엔진 응답: 정상")
        if status.get("demo"):
            print("데모 모드: 실제 카카오톡에 접근하지 않습니다.")
        if status.get("decryptableDatabases") == 0:
            print("열 수 있는 DB: 0. 64비트 카카오톡에서 방을 한 번 열고 재확인하세요.")
            return 1
        return 0
    except BackendError as error:
        print(f"{error.code}: {error}")
        return 1
    finally:
        await backend.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="ORCA에서 직접 대화하는 카카오톡 TUI")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--demo", action="store_true", help="합성 데이터로 실행 (실제 전송 없음)")
    parser.add_argument("--doctor", action="store_true", help="화면을 열지 않고 연결 상태 확인")
    parser.add_argument(
        "--engine-path", type=Path, default=default_engine(), help="nichirin 체크아웃 경로"
    )
    parser.add_argument("--room", help="시작할 채팅방의 정확한 이름 (중복이면 직접 선택)")
    parser.add_argument("--poll", type=interval, default=2, help="새 메시지 조회 간격 (기본 2초)")
    args = parser.parse_args()
    if args.demo:
        from kaka.backends.demo import DemoBackend

        backend = DemoBackend()
    else:
        from kaka.backends.nichirin import NichirinBackend

        backend = NichirinBackend(args.engine_path)
    if args.doctor:
        return asyncio.run(doctor(backend))
    from kaka.app import KakaApp

    KakaApp(backend, demo=args.demo, poll_interval=args.poll, room_name=args.room).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
