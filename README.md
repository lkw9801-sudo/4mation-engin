# 4Mation 레퍼런스 엔진

Piatnik 공식 규칙서를 따르는 4Mation 룰 엔진과, 가능한 국면은 **완전히 풀고(exact)** 풀 수 없는 국면은 최대한 깊게 탐색하며 두 경우를 명확히 구분해 돌려주는 탐색 엔진입니다.

- 규칙: `fourmation/rules.py` (원본 그대로 + `State.from_compact`)
- 탐색 코어: `fourmation/native/core.c` (C, 첫 import 때 자동 컴파일, ctypes로 호출)
- 고수준 API: `fourmation/engine.py` (`Engine.play / think / solve / analyze`)
- 해결된 국면 book: `fourmation/book.py` (대칭 정규화, 선공 필승 전략 book 생성)
- 순수 Python 버전: `fourmation/pyengine.py` (C 컴파일러가 없을 때의 대체재, 같은 알고리즘)
- 기존 엔진: `fourmation/bots.py`의 `AlphaBetaBot` (비교 기준으로 그대로 둠)

결과 보고서는 `REPORT.md`, 측정 원자료는 `bench/results/`에 있습니다.

## 요구 사항

Python 3.10 이상, C 컴파일러(gcc/clang/cc). numpy는 평가함수 튜닝 스크립트(`bench/tune_eval.py`)에서만 씁니다.
C 컴파일러가 없거나 `FOURMATION_NO_NATIVE=1`이면 native 코어 없이 `PyEngine`만 쓸 수 있습니다(약 90배 느림).

- 확인한 환경: Linux(gcc, clang), Python 3.10, 3.11, 3.13.
- 시험하지 않은 환경: Python 3.9, macOS, Windows(MinGW gcc 또는 MSVC `cl` 빌드 경로는 넣어 두었습니다).

**엔진 여러 개와 스레드**
- `Engine`마다 자기 TT(`tt_mb`, 기본 128MB)와 수 정렬 기록을 따로 가집니다. 한 프로그램에서 여러 개를 만들어도 서로 영향이 없습니다.
- 메모리는 엔진 수만큼 듭니다.
- native 호출은 프로세스 안에서 한 번에 하나씩(잠금) 실행되므로, 여러 스레드에서 써도 안전하지만 빨라지지는 않습니다. 병렬로 빠르게 하려면 프로세스를 나누세요(`fourmation.book prove --procs`처럼).

## 규칙과 가정

| 규칙 | 구현 | 근거 |
|---|---|---|
| 판 7×7, 색당 큐브 24개 | 그대로 | 규칙서 |
| 첫 수 아무 칸 | 그대로 | 규칙서 |
| 직전 큐브의 8방향 이웃 칸에 둠 | 그대로 | 규칙서 |
| 막힘: 직전 큐브 주변이 꽉 참 → 직전 수를 둔 색 큐브 아무거나의 이웃 빈칸 | 그대로 | 규칙서 (독/프 원문 확인) |
| 4개 이상 연속(가로·세로·대각) 즉시 승 | 그대로 | 규칙서 |
| 아무도 4줄을 만들 수 없으면 무승부 | `draw_rule="open_line"` (정적 검사) | 규칙서 문장 해석. `exhaustion`과 **게임 값은 동일**, 끝나는 시점만 다름 |
| 막힘 + 상대 색 큐브 주변에도 빈칸 없음 | `no_move_fallback="any_empty"`(기본) 또는 `"draw"` | **규칙서에 없음 (가정)** |

마지막 항목은 규칙서가 정하지 않은 유일한 부분입니다.
- 엔진은 이 상황을 탐색 중에 만나면 결과에 `rule_sensitive=True`를 붙입니다.
- 무작위 3,000판과 엔진 대국 수백 판에서 실제로 나온 적은 없습니다.
- 선공 필승 증명(초기 국면 X 승 29 ply)은 이 상황을 한 번도 거치지 않아서 이 가정과 무관합니다.

## 사용법

```bash
# 전체 테스트 (원본 23개 + 새 테스트)
python -m unittest discover -s tests -t .

# 사람 대 엔진 (터미널)
python -m fourmation.play --bot new --time 1 --first human   # 새 엔진 (1초/수, 선공 book 사용)
python -m fourmation.play --bot ab4 --first human            # 기존 봇
```

```python
from fourmation.rules import State, new_game, apply_move, parse_coord
from fourmation.engine import Engine

eng = Engine(tt_mb=512, book="default")   # book: 선공 필승 전략 (ply 16까지, fourmation/data/)
st = State.from_compact("....X.....XOO...O.X.............................. X c3")   # ply 6, X 차례

# 1) 대국용: book → exact solve(시간의 절반) → iterative deepening
info = eng.play(st, time=1.0)
print(info.move, info.result, info.distance, info.depth, info.source)
# d4 HEURISTIC None 15 search        (이 국면은 1초 안에 exact로 안 풀림)

# 2) 순수 탐색(ID + PVS): 반복 깊이별 수렴 기록 포함
info = eng.think(st, time=5.0)
for it in info.iterations:
    print(it.depth, it.move, it.score, it.nodes)

# 3) 정답(게임 이론적 값)과 게임 끝까지 남은 수(ply)
sol = eng.solve(st, time=30)          # 시간 안에 못 풀면 None
# {'result': 'EXACT_WIN', 'score': 29967, 'distance': 27, 'distance_exact': True,
#  'pv': ['d4', 'd3', 'c4', 'b3', 'a3', 'b2', 'c1', 'c2', ...], 'nodes': 6849643, ...}

# 4) 모든 후보수 평가 (LLM 수 비교용), 점수 높은 순
for row in eng.analyze(st, time=20):
    print(row)
# {'move': 'd4', 'score': 29967, 'result': 'EXACT_WIN', 'distance': 27, 'distance_exact': True,  'depth': None, 'exact': True, ...}
# {'move': 'c4', 'score': 29967, 'result': 'EXACT_WIN', 'distance': 27, 'distance_exact': False, 'depth': 25,   'exact': True, ...}
# {'move': 'd3', 'score': 261,   'result': 'HEURISTIC', 'distance': None, 'depth': 25, 'exact': False, ...}
# {'move': 'b2', 'score': 155,   'result': 'HEURISTIC', 'distance': None, 'depth': 25, 'exact': False, ...}

# 5) 한 수 채점 (예: LLM이 고른 수). analyze 결과(rows)를 넘기면 여러 수를 한 번에 채점
rows = eng.analyze(st, time=20)
eng.grade_move(st, "d3", rows=rows)
# {'move': 'd3', 'verdict': 'UNCERTAIN', 'best_move': 'd4', 'best_result': 'EXACT_WIN', ...}
# verdict: BEST / SLOWER_WIN(+plies_lost) / FASTER_LOSS / WIN_TO_DRAW / WIN_TO_LOSS / DRAW_TO_LOSS / UNCERTAIN / ILLEGAL
```

### 결과 해석

| 필드 | 의미 |
|---|---|
| `result` | `EXACT_WIN` / `EXACT_DRAW` / `EXACT_LOSS` = 게임 끝까지 증명됨. `HEURISTIC` = 깊이 제한 탐색 값 |
| `score` | 둘 차례 기준. `±(30000 - k)`는 판에 큐브가 k개가 되는 수에서 게임이 끝나는 증명된 승/패. 그 밖의 값은 평가함수 점수이며 **승률이 아님** |
| `distance` | 최선의 응수를 가정할 때 게임이 끝날 때까지 남은 ply 수(이기는 쪽은 가장 빠르게, 지는 쪽은 가장 오래 버틴다고 가정) |
| `distance_exact` | 거리가 최소/최대임을 검증했는지 여부 (False면 상한) |
| `depth` | 휴리스틱 결과의 탐색 깊이 (exact면 None 또는 남은 ply 수) |
| `rule_sensitive` | 규칙서에 없는 상황(위 표 마지막 행)이 탐색 트리에 등장했는지 여부 |
| `source` (play) | `book` / `solve`(exact solver) / `search`(iterative deepening) |

`analyze()`의 `exact=True`는 승/무/패가 증명됐다는 뜻입니다. 거리까지 검증됐는지는 `distance_exact`로 따로 봅니다.

### 해결된 국면 book

4Mation은 선공 필승입니다(REPORT.md 8절). `fourmation/data/x_strategy_book.json`은 1.d4부터 ply 16까지의 선공 필승 전략입니다(8,454국면). X 차례에는 증명된 승리수, O 차례에는 모든 응수를 담았습니다. `Engine(book="default")`로 쓰면 초기 국면부터 X가 완벽하게 둡니다(book 구간은 탐색 없이, 그 뒤는 exact solver로). 검증: 초기 국면에서 random·greedy·ab8·ab10·새 엔진(1초) 상대로 X 25전 25승(0.1초/수).

```bash
# 선공(X) 필승 전략 book 만들기: X 차례엔 증명된 승리수 1개, O 차례엔 모든 응수 전개
python -m fourmation.book strategy --max-ply 16 --book book.json
# 임의 국면을 앞 몇 ply만 Python에서 전개하고 나머지를 solver로 병렬 증명
python -m fourmation.book prove --moves d4 --expand 1 --book book.json
```

```python
from fourmation.book import Book
eng = Engine(book=Book("book.json"))   # play()가 book을 먼저 조회
```

### 벤치마크와 대국

```bash
python -m bench.bench_legacy --depths 2,4,6,8,10,12          # 기존 엔진 baseline
python -m bench.bench_search --depth 14 --time 0.3            # 탐색 기법 ablation
python -m bench.time_depth --times 1,5,30                     # 사고시간별 도달 깊이
python -m bench.match --a new:t=0.1 --b old:ab8 --games 100   # 대국 (선후공 교대)
python -m bench.puzzles eval --players "old:ab8;new:t=0.1"    # exact 라벨 전술 문제 (bench/puzzles.json)
python -m bench.review_losses --games bench/results/match_losses.jsonl   # 이기지 못한 대국 exact 복기(실수 탐지)
python -m bench.verify_solver --n 150                         # solver 자기 일관성·교차 검증
python -m bench.first_moves d2,b2 3600                        # 첫 수별 게임 값
python -m bench.solvebench --set bench/solve_set_b.json --ply 12   # exact solve 비용
python -m bench.verify_book fourmation/data/x_strategy_book.json   # 전략 book 전수 검증
python -m bench.solve_line d4,d5 --time 3600                  # 한 수순을 끝까지 풀기
python -m bench.solvability                                   # 상태 공간 통계
```

`bench/puzzles.json`(exact 라벨 165문제: 국면, 정답 수 목록, 모든 수의 exact 값과 거리)은 LLM 평가용 문제 세트로 그대로 쓸 수 있습니다.

좌표는 열 a~g(왼쪽→오른쪽), 행 1~7(아래→위)입니다. compact 표기는 `a1..g7` 49칸 + 둘 차례(X/O) + 직전 수입니다.
