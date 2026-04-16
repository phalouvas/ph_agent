# Project Guidelines

## Code Style
- **Indentation**: Use tabs for Python, JavaScript, Vue, CSS, SCSS, HTML files (configured in `.editorconfig`). Use spaces only for JSON files (indent size 1).
- **Line length**: Maximum 110 characters for Python (configured in `pyproject.toml`), 99 for other languages (`.editorconfig`). Ruff will enforce this.
- **Formatting**: Use Ruff for Python formatting and linting. Use Prettier for JavaScript/Vue/SCSS. Use ESLint for JavaScript linting.
- **Imports**: Use Ruff's import sorter (I rule). Unused imports are allowed (`F401` ignored) but should be cleaned up.
- **Quotes**: Double quotes for Python strings (Ruff format `quote-style = "double"`).
- **Naming**: Avoid ambiguous variable names (`E741` ignored) but aim for clarity.

Refer to `.editorconfig`, `.pre-commit-config.yaml`, and `pyproject.toml` for detailed configurations.

## Architecture
- This is a **Frappe v16 app** that integrates agentic AI chatbots into ERPNext.
- **Key integration points** are defined in `ph_agent/hooks.py` (document events, scheduled tasks, permission queries, method overrides, installation hooks). Most hooks are commented; enable only when needed.
- **Directory structure**:
  - `ph_agent/config/` – UI configuration (empty)
  - `ph_agent/patches/` – Database migrations (empty)
  - `public/` – Front‑end assets (empty)
  - `templates/pages/` – Website pages (empty)
- **Dependencies** are managed via `pyproject.toml`. **Never** add `frappe` as a dependency (it’s installed and managed by bench). Add only app‑specific packages (e.g., `agent‑framework`).
- **Frappe conventions**: Use `@frappe.whitelist()` for API methods; follow Frappe’s document lifecycle.

## Build and Test
- **Installation** (see [README.md](../README.md)):
  ```bash
  bench get‑app <url> --branch version‑16
  bench install‑app ph_agent
  ```
- **Development setup**:
  ```bash
  cd apps/ph_agent
  pre‑commit install   # enables pre‑commit hooks
  ```
- **Testing** (no tests yet):
  ```bash
  bench test‑site --app ph_agent
  ```
- **Build system**: Flit (PEP 517/518). Python ≥3.14 required.
- **Code quality**: Pre‑commit hooks run Ruff, ESLint, Prettier, pyupgrade, etc. Always run `pre‑commit install` after cloning.

## Conventions
- **Dependency management**: Add Python packages only to `[project.dependencies]` in `pyproject.toml`. Development dependencies go under `[tool.bench.dev‑dependencies]`. APT dependencies for Frappe Cloud go under `[deploy.dependencies.apt]`.
- **Hooks**: Enable hooks in `hooks.py` only when you have implemented the corresponding methods. Empty hooks will crash the app boot.
- **Database transactions**: Frappe auto‑commits; use explicit rollback where needed.
- **Code quality**: Pre‑commit is mandatory; ensure all hooks pass before committing.
- **Avoid pitfalls**:
  - Do **not** add `frappe` to dependencies.
  - Always decorate API methods with `@frappe.whitelist()`.
  - Do not mix spaces and tabs (Ruff will reject).
  - Do not enable empty hooks.

## Reference Files
| File | Purpose |
|------|---------|
| `pyproject.toml` | Dependencies, build config, Ruff settings |
| `ph_agent/hooks.py` | Frappe integration points (examples) |
| `.pre‑commit‑config.yaml` | Quality gate automation |
| `.editorconfig` | Indentation rules |
| `README.md` | Installation and contribution guide |

**Link, don’t embed**: Consult the existing documentation (README, license) and Frappe framework documentation for broader context.