# 외부 코드와 출처

## nichirin / kanao

- 저장소: https://github.com/sanguneo/nichirin
- 고정 커밋: `9a686cb8bc32c04e91a30e54c61409b83d6f932a`
- 라이선스: MIT. [원문 사본](docs/NICHIRIN_LICENSE.txt)
- 원 저작권자: Silver Flight Group, LLC. 및 kanao-cli contributors (2026)
- 역할: Windows 카카오톡 로컬 DB 읽기와 로그인된 PC 카톡 창을 통한 텍스트 전송.
- 설치: 사용자의 `setup.ps1` 실행 시 `.engine/nichirin`에 원본 저장소를 clone하고 지정 커밋으로 checkout.
- KAKA는 원본의 공개 CLI 계약을 JSON으로 호출한다. 본문 노출을 줄이기 위해 stdin을 받는 작은
  하위 프로세스가 `sys.argv`를 구성한 뒤 공개 모듈 진입점 `python -m nichirin`과 같은 코드를 실행한다.
  비공개 Reader/Sender API를 직접 사용하지 않는다.
- 원본 TUI는 호출하지 않는다. KAKA TUI는 자체 구현이다.
- `tests/fixtures/rooms.json`, `messages.json`은 원본 `windows/tests/envelopes/`의 합성 fixture를
  JSON 정렬 형식만 바꾸어 포함했다. 실제 사용자의 대화는 아니다.
- 엔진이 사용하는 저수준 방식은 Brian ByungHyun Shin / Silver Flight Group의
  https://github.com/silver-flight-group/kakaocli 에서 유래한다.

## Textual / Rich

- https://github.com/Textualize/textual (MIT)
- https://github.com/Textualize/rich (MIT)
- Textual `1.0.0`을 화면·입력·레이아웃·headless UI 테스트에 사용한다. Rich는 Textual의 의존성이다.
- 패키지 매니저로 설치하며 원본 패키지의 라이선스 고지를 유지한다.

KAKA의 자체 코드는 루트 [LICENSE](LICENSE)의 MIT 라이선스를 따른다.
