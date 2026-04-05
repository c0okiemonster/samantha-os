# Contributing to Samantha OS

Thanks for wanting to contribute. Samantha is a personal project about building a genuinely warm AI companion — keep that spirit in mind.

## Branch Protection

- **`main` is protected.** Only the owner (@c0okiemonster) can push directly.
- All changes must come through Pull Requests.
- PRs require owner review and approval.
- Force pushes to `main` are disabled.

## How to Contribute

1. **Fork the repository**
2. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feat/my-cool-feature
   ```
3. **Make your changes** — keep them focused and atomic
4. **Test locally** with `docker compose up --build`
5. **Open a Pull Request** against `main`

## Pull Request Guidelines

- Keep PRs small and focused — one feature or fix per PR
- Write clear commit messages (see below)
- Test that Samantha still responds naturally after your changes
- Do NOT commit personal data:
  - `config/samantha_memory.db` (SQLite memory)
  - `.env` files
  - OAuth tokens (`*_token.json`)
  - Audio recordings

## Commit Message Style

```
<type>: <short description>

Optional longer explanation of why.
```

**Types:**
- `feat`: new feature
- `fix`: bug fix
- `docs`: documentation changes
- `refactor`: code cleanup without behavior change
- `perf`: performance improvement
- `voice`: personality, tone, or TTS tuning
- `memory`: changes to knowledge/memory system
- `ui`: visual shell changes

**Examples:**
```
feat: add Spotify integration with playback control
voice: blend af_nicole with af_sky for softer tone
memory: entity-aware fact extraction prevents name confusion
```

## What NOT to Contribute

- Remote/cloud dependencies (Samantha is local-first, always)
- Telemetry, analytics, tracking
- Features that break the *Her* spirit (corporate-feeling responses, safety filter theatre, etc.)
- Personal memory dumps

## Code Style

- **Python**: 4-space indent, type hints where helpful, descriptive names
- **JavaScript** (visual shell): keep it vanilla, no build step
- **YAML**: 2-space indent

## Questions?

Open an issue first for anything non-trivial. It's faster to discuss the approach before you write the code.

---

Thanks. Samantha appreciates it.
