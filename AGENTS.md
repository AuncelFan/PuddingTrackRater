# Project Agent Notes

<!-- project-self-improvement:begin -->
## Project Self-Improvement

### Stable Facts

- The product name is `PuddingTrackRater`; use that exact casing in user-facing text and API metadata.
- The backend is a FastAPI application exported as `app:app`; `app/main.py` owns the application factory and HTTP routes.
- The domain scorer is `app.rater.Rater`, implemented in `app/rater/rater.py`.
- `POST /api/parse_kml` accepts a multipart field named `kml_file` and returns `{code, msg, data}`.
- Vite builds the frontend into `app/static/dist`, which FastAPI serves at `/` and `/assets`.
- `Routes/MY` is an ignored local symlink to the real-world KML validation corpus.

### Working Agreements

- Preserve the existing `/api/parse_kml` field name and response envelope when changing the API.
- Do not reintroduce the former event-specific branding in product text, package/environment identifiers, or API metadata.
- Use `rater`/`Rater` consistently for the scoring domain; do not reintroduce the former domain name.
- Validate backend changes with `uv run pytest` and frontend integration changes with `npm run build` from `frontend/`.
- Keep click selection and drag-and-drop uploads on the same selected-file state and parsing path.
- Keep the selected-file row visible after parsing; only the cancel action returns to the large drop zone.
- Treat the target of `Routes/MY` as strictly read-only; tests may only open, read, and upload those KML files.

### Pitfalls And Resolutions

- Keep `python-multipart` installed because FastAPI requires it to parse uploaded form files.

### Source Of Truth

- Use `pyproject.toml` and `uv.lock` for Python dependencies, and `README.md` for local and production startup commands.
- Use `Routes/MY` as the local real-world KML validation corpus when the symlink is available.

<!-- project-self-improvement:end -->
