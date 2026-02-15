# Portfolio Publishing Checklist

Use this checklist to maximize portfolio impact on GitHub and your profile.

## Repository Presentation

- [ ] Keep `README.MD` as the primary project narrative and technical summary.
- [ ] Pin this repository on your GitHub profile.
- [ ] Add repository topics (example: `python`, `asyncio`, `telegram-bot`, `mongodb`, `redis`, `distributed-systems`).
- [ ] Keep architecture and portfolio docs linked near the top of README.

## Technical Storytelling

- [ ] Keep `docs/architecture/diagrams.md` updated when architecture changes.
- [ ] Keep `docs/portfolio/engineering-issues-solved.md` evidence-based and code-linked.
- [ ] Add one short release note whenever major engineering changes ship.

## Visual Proof

- [ ] Add 3-5 screenshots (search flow, admin commands, metrics output).
- [ ] Add one short GIF/video clip of the core demo flow.
- [ ] Add a diagram screenshot to social posts for quick technical credibility.

## Professional Packaging

- [ ] Use `docs/portfolio/resume-and-interview-kit.md` to copy final resume bullets.
- [ ] Practice the 30/60/120 second pitch from the same document.
- [ ] Prepare one STAR story from the engineering issues document.

## Code Quality Signals

- [ ] Keep `requirements.txt` and `pyproject.toml` aligned.
- [ ] Run lint/type/test checks before major portfolio updates.
- [ ] Keep `.env.example` current to reduce setup friction for reviewers.

## Operations and Reliability Signals

- [ ] Verify `/health` and `/metrics` endpoints before demos.
- [ ] Validate broadcast stop/recovery paths after restart scenarios.
- [ ] Validate database stats and failover views when multi-db mode is enabled.

## Suggested Next Upgrades

- [ ] Add CI workflow for lint + type check + tests.
- [ ] Add synthetic load test script for search/indexing paths.
- [ ] Add architecture decision records (ADR) for major design choices.
- [ ] Add test suite for critical correctness flows (quota, failover, broadcast recovery).
