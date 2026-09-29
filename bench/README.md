# bench/ — 측정 스크립트와 원자료

모든 스크립트는 저장소 루트에서 `python -m bench.<이름>`으로 실행합니다. 수치 해석은 `REPORT.md`에 있습니다.

## 국면 세트

| 파일 | 내용 |
|---|---|
| `positions.py` | 대표 국면 5개(initial, early ply 6, mid ply 16, tactical ply 21, late ply 30). ab4 자체 대국(무작위 2 ply 오프닝)에서 골랐고, tactical은 ab3가 못 보는 7 ply 강제승 |
| `solve_set.json` | 새 엔진 자체 대국(depth 10)의 ply 8~18 국면, ply마다 16개 |
| `solve_set_b.json` | 같은 방식으로 만든 ply 10/12/14 국면, 각 48개 |
| `puzzles.json` | exact 라벨 전술 문제 165개(ply 8~44). 국면, 정답 수, 모든 수의 exact 값과 거리 |
| `puzzles_early.json` | 같은 형식의 초반 문제 51개(ply 6~10) |

## 스크립트

| 스크립트 | 용도 | 결과 파일 (`results/`) |
|---|---|---|
| `bench_legacy.py`, `legacy_instrumented.py` | 기존 엔진 baseline (카운터만 추가, 알고리즘 동일) | `legacy_d2_12.jsonl`, `legacy_d14plus.jsonl`, `legacy_memory.jsonl` |
| `bench_new.py` | 새 엔진, 같은 지표 | `new_engine.jsonl` |
| `make_tables.py` | 위 결과를 마크다운 표로 | – |
| `bench_search.py` | 휴리스틱 탐색 ablation | `search_ablation.md` |
| `solvebench.py` | exact solve 비용과 solver ablation | `solver_ablation_*.txt`, `solve_by_ply_final.txt` |
| `tune_eval.py` | exact 라벨 로지스틱 회귀로 평가함수 튜닝 | `tune_*.json`, `eval_matches.jsonl` |
| `match.py`, `run_matches.sh` | 대국 (선후공 교대, 같은 오프닝 두 번) | `matches.jsonl`, `matches.md`, `match_losses.jsonl` |
| `review.py`, `review_losses.py` | 이기지 못한 대국의 수별 exact 복기 | `loss_review.jsonl`, `loss_review.log` |
| `puzzles.py` | 전술 문제 생성과 채점 | `puzzles_eval*.md`, `puzzles_early_eval*.md` |
| `swindle.py` | 진 국면에서의 탈출률 ("resist" 모드 실험) | `swindle.md` |
| `time_depth.py` | 1/5/30초에서 도달하는 깊이와 exact 여부 | `time_depth.md`, `time_depth.json` |
| `solvability.py` | perft, 서로 다른 국면 수, 분기 수, 상태 공간 상한 | `solvability.md` |
| `verify_solver.py` | Bellman 일관성, 옵션 불변성, Python 구현 교차 검증 | `verify_solver*.json` |
| `verify_book.py` | 전략 book 전수 검증 | `verify_book_*.log` |
| `solve_line.py`, `first_moves.py`, `check_initial_distance.py` | 특정 수순, 첫 수별 값, 초기 국면 거리 증명 | `../solve_runs/*.json*`, `initial_distance.*` |

`results/v1_pre_fix/`는 TT 버그 수정 전 엔진(v1)의 대국·복기 결과입니다(REPORT.md 0절 5번).
