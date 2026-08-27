# Gallery Komganion

Gallery Komganion is a lightweight, self-hosted image-gallery server for the
[Yokai Komganion Android reader](https://github.com/roddur99/yokai-komganion).

It indexes ordinary folders containing images and exposes them through an authenticated API
without requiring those folders to be converted into CBZ archives.

> And yeah, “Komganion” is a dumb play on “companion.” (Komga's)

## Download

Download the latest Windows release from the
[GitHub Releases page](https://github.com/roddur99/gallery-komganion/releases/latest).

1. Download `Gallery-Komganion-v0.1.0-windows-x64.zip`.
2. Extract the entire ZIP.
3. Run `Gallery Komganion\Gallery Komganion.exe`.

Keep all extracted files together. Windows SmartScreen may warn about the
unsigned personal application; choose **More info** and **Run anyway** if you
built or downloaded it from this repository.

## Features

- Scan one or more configurable gallery roots.
- Treat folders containing supported images as galleries.
- Preserve stable gallery identities across folder renames.
- Index JPEG, PNG, GIF, and WebP pages in natural filename order.
- Store roots, galleries, pages, scan state, and metadata in SQLite.
- Search, paginate, and sort galleries through FastAPI.
- Stream original images and cached thumbnails.
- Expose page filename, dimensions, file size, and modified date.
- Authenticate protected endpoints with a bearer token.
- Move individual images to a configured trash directory instead of permanently deleting them.
- Reindex page order after deletion.
- Avoid marking galleries missing when a root is offline or a scan is incomplete.
- Connect privately over a LAN or VPN such as NordVPN Meshnet.
- Run from the command line or a minimal Windows control panel.

## Windows control panel

The desktop control panel provides:

- Server start and stop.
- Host and port configuration.
- API-token generation, display, and copy.
- Add, edit, enable, disable, or remove gallery roots.
- Gallery and trash folder pickers.
- Background “Scan now” with totals and errors.
- Swagger/API documentation launch.
- Activity log and clean server shutdown.

On first launch it creates:

```text
%LOCALAPPDATA%\GalleryKomganion\
├── config.toml
└── data\
    ├── gallery-komganion.sqlite3
    └── thumbnails\
```

Adding or removing a configured root does not delete gallery images. Image deletion from the
Android reader moves the selected file to that root’s configured trash folder.

## Run the control panel from source

Requirements:

- Windows
- Python 3.12 or newer

```powershell
git clone https://github.com/roddur99/gallery-komganion.git
cd gallery-komganion

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

gallery-komganion-ui
```

Use a custom configuration path when needed:

```powershell
gallery-komganion-ui --config D:\GalleryKomganion\config.toml
```

## Build the Windows executable

Build the directory-based PyInstaller distribution:

```powershell
.\scripts\build_windows.ps1 -Clean
```

The result is:

```text
dist\Gallery Komganion\Gallery Komganion.exe
```

Distribute the entire `Gallery Komganion` folder, not only the `.exe`. The directory build is
more reliable than a single-file executable for Uvicorn, Pillow, SQLite, and Tcl/Tk.

The executable does not contain gallery images, the database, the API token, or configuration.
Those remain in `%LOCALAPPDATA%\GalleryKomganion`.

## Configuration

The control panel creates and edits the configuration automatically. A manual example is also
available in [`config.example.toml`](config.example.toml):

```toml
[server]
host = "127.0.0.1"
port = 8000

[security]
api_token = "replace-with-a-random-token-at-least-32-characters"

[storage]
database_path = "./data/gallery-komganion.sqlite3"
thumbnail_directory = "./data/thumbnails"

[[gallery_roots]]
id = "7372564f-3905-413e-a152-be90e8499f8f"
name = "Example Galleries"
path = "D:/Galleries"
trash_path = "D:/GalleryKomganionTrash"
enabled = true
```

Rules for each root:

- Gallery and trash paths must be different.
- The trash directory cannot be inside the gallery root.
- The gallery root cannot be inside the trash directory.
- On Windows, gallery and trash directories must be on the same drive so moves remain atomic.
- Keep the generated UUID stable when editing a root.

The environment variable `GALLERY_KOMGANION_API_TOKEN` overrides the configured token.
`GALLERY_KOMGANION_CONFIG_PATH` selects a non-default configuration file.

## Command-line development workflow

Install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .\config.example.toml .\config.toml
```

Set a strong token in `config.toml`, then initialize an existing development database with
Alembic:

```powershell
alembic upgrade head
```

Scan configured roots:

```powershell
gallery-komganion scan
```

Run the API using the host and port selected for your environment:

```powershell
uvicorn gallery_komganion.main:app --host 127.0.0.1 --port 8000
```

Open:

- Health: `http://127.0.0.1:8000/api/v1/health`
- Swagger: `http://127.0.0.1:8000/docs`

The health endpoint is public. Gallery, page, thumbnail, streaming, and deletion endpoints
require:

```http
Authorization: Bearer YOUR_API_TOKEN
```

## Connect Yokai Komganion

In the Android app’s Gallery connection screen, enter:

- Server URL, including `http://` or `https://`.
- The same API token shown in the control panel.

For a local network, use the Windows computer’s reachable LAN address rather than
`127.0.0.1`. For an Android emulator on the same computer, `10.0.2.2` usually reaches the
Windows host.

### NordVPN Meshnet

For private remote access:

1. Enable Meshnet on the Windows server and Android device.
2. Set the server host to `0.0.0.0` in the control panel.
3. Allow Gallery Komganion through Windows Firewall on trusted/private networks.
4. Use the Windows machine’s Meshnet hostname or Meshnet IP in Yokai Komganion.
5. Keep bearer-token authentication enabled.

Do not expose the development server directly to the public internet.

## Tests and formatting

```powershell
ruff format .
ruff check .
pytest
```

## Architecture

```text
Configured folders
       │
       ▼
Filesystem discovery ──► SQLite index
                              │
                              ▼
Windows control panel ──► FastAPI/Uvicorn
                              │
                              ▼
                    Yokai Komganion reader
```

The control panel wraps the same scanner, database models, and FastAPI app used by the
command-line workflow.

## Status

The filesystem-to-database pipeline, authenticated browsing API, thumbnails, metadata,
image streaming, trash deletion, Android integration, and Windows control panel are
implemented. The Windows executable still requires a smoke test on a clean Windows machine
before publishing a binary release.

## Security

- `config.toml` contains the API token and is ignored by Git.
- Never commit real tokens, databases, thumbnails, or gallery paths.
- Use a long random token.
- Prefer LAN or private-VPN access.
- Back up configuration and the SQLite database before major upgrades.

## Related repository

- Android client: [roddur99/yokai-komganion](https://github.com/roddur99/yokai-komganion)

## License

See [LICENSE](LICENSE).
