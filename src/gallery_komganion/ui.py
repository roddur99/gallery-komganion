from __future__ import annotations

import argparse
import queue
import secrets
import threading
import tkinter as tk
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import UUID, uuid4

from pydantic import SecretStr, ValidationError

from gallery_komganion.config import (
    AppConfig,
    GalleryRootConfig,
    SecurityConfig,
    ServerConfig,
    load_or_create_config,
    save_config,
)
from gallery_komganion.control import (
    ScanSummary,
    ServerController,
    default_config_path,
    scan_config,
)


class RootDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        root_config: GalleryRootConfig | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Gallery root")
        self.resizable(True, False)
        self.transient(parent)
        self.result: GalleryRootConfig | None = None
        self._root_id = root_config.id if root_config is not None else uuid4()

        self.name_variable = tk.StringVar(
            value=root_config.name if root_config is not None else ""
        )
        self.path_variable = tk.StringVar(
            value=str(root_config.path) if root_config is not None else ""
        )
        self.trash_variable = tk.StringVar(
            value=str(root_config.trash_path) if root_config is not None else ""
        )
        self.enabled_variable = tk.BooleanVar(
            value=root_config.enabled if root_config is not None else True
        )

        frame = ttk.Frame(self, padding=12)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Name").grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        name_entry = ttk.Entry(frame, textvariable=self.name_variable, width=55)
        name_entry.grid(row=0, column=1, columnspan=2, pady=4, sticky="ew")

        ttk.Label(frame, text="Gallery folder").grid(
            row=1,
            column=0,
            padx=(0, 8),
            pady=4,
            sticky="w",
        )
        ttk.Entry(frame, textvariable=self.path_variable).grid(
            row=1,
            column=1,
            pady=4,
            sticky="ew",
        )
        ttk.Button(
            frame,
            text="Browse…",
            command=lambda: self._choose_directory(self.path_variable),
        ).grid(row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(frame, text="Trash folder").grid(
            row=2,
            column=0,
            padx=(0, 8),
            pady=4,
            sticky="w",
        )
        ttk.Entry(frame, textvariable=self.trash_variable).grid(
            row=2,
            column=1,
            pady=4,
            sticky="ew",
        )
        ttk.Button(
            frame,
            text="Browse…",
            command=lambda: self._choose_directory(self.trash_variable),
        ).grid(row=2, column=2, padx=(8, 0), pady=4)

        ttk.Checkbutton(
            frame,
            text="Enabled",
            variable=self.enabled_variable,
        ).grid(row=3, column=1, pady=(6, 10), sticky="w")

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=self._save).pack(
            side="right",
            padx=(0, 8),
        )

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        name_entry.focus_set()
        self.grab_set()

    def _choose_directory(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(
            parent=self,
            initialdir=variable.get() or None,
        )

        if selected:
            variable.set(selected)

    def _save(self) -> None:
        try:
            gallery_value = self.path_variable.get().strip()
            trash_value = self.trash_variable.get().strip()

            if not gallery_value or not trash_value:
                raise ValueError("Gallery and trash folders are required")

            gallery_path = Path(gallery_value).expanduser().resolve(strict=False)
            trash_path = Path(trash_value).expanduser().resolve(strict=False)
            resolved = GalleryRootConfig(
                id=self._root_id,
                name=self.name_variable.get().strip(),
                path=gallery_path,
                trash_path=trash_path,
                enabled=self.enabled_variable.get(),
            )

            if gallery_path == trash_path:
                raise ValueError("The gallery and trash folders must be different")

            if trash_path.is_relative_to(gallery_path):
                raise ValueError("The trash folder cannot be inside the gallery folder")

            if gallery_path.is_relative_to(trash_path):
                raise ValueError("The gallery folder cannot be inside the trash folder")

            if (
                gallery_path.drive
                and trash_path.drive
                and gallery_path.drive.casefold() != trash_path.drive.casefold()
            ):
                raise ValueError("The gallery and trash folders must be on the same drive")
        except (OSError, ValueError, ValidationError) as exc:
            messagebox.showerror("Invalid gallery root", str(exc), parent=self)
            return

        self.result = resolved
        self.destroy()


class ControlPanel:
    def __init__(self, window: tk.Tk, config_path: Path) -> None:
        self.window = window
        self.config_path = config_path.resolve(strict=False)
        self.config = load_or_create_config(self.config_path)
        self.roots = list(self.config.gallery_roots)
        self.server = ServerController()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False

        self.host_variable = tk.StringVar(value=self.config.server.host)
        self.port_variable = tk.StringVar(value=str(self.config.server.port))
        configured_token = self.config.security.api_token
        self.token_variable = tk.StringVar(
            value=configured_token.get_secret_value() if configured_token else ""
        )
        self.show_token_variable = tk.BooleanVar(value=False)
        self.status_variable = tk.StringVar(value="Stopped")
        self.summary_variable = tk.StringVar(value="Ready")

        self.window.title("Gallery Komganion")
        self.window.geometry("980x650")
        self.window.minsize(760, 520)
        self.window.protocol("WM_DELETE_WINDOW", self._close)

        self._build()
        self._refresh_roots()
        self._set_controls()
        self.window.after(150, self._poll_events)

    def _build(self) -> None:
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        outer.rowconfigure(5, weight=1)

        server_frame = ttk.LabelFrame(outer, text="Server", padding=10)
        server_frame.grid(row=0, column=0, sticky="ew")
        server_frame.columnconfigure(5, weight=1)

        ttk.Label(server_frame, text="Status:").grid(row=0, column=0, sticky="w")
        self.status_label = ttk.Label(
            server_frame,
            textvariable=self.status_variable,
            width=12,
        )
        self.status_label.grid(row=0, column=1, padx=(4, 16), sticky="w")

        ttk.Label(server_frame, text="Host").grid(row=0, column=2, sticky="e")
        self.host_entry = ttk.Entry(
            server_frame,
            textvariable=self.host_variable,
            width=16,
        )
        self.host_entry.grid(row=0, column=3, padx=(4, 12))

        ttk.Label(server_frame, text="Port").grid(row=0, column=4, sticky="e")
        self.port_entry = ttk.Entry(
            server_frame,
            textvariable=self.port_variable,
            width=8,
        )
        self.port_entry.grid(row=0, column=5, padx=(4, 12), sticky="w")

        self.server_button = ttk.Button(
            server_frame,
            text="Start server",
            command=self._toggle_server,
        )
        self.server_button.grid(row=0, column=6, padx=(0, 8))

        self.docs_button = ttk.Button(
            server_frame,
            text="Open API docs",
            command=self._open_docs,
        )
        self.docs_button.grid(row=0, column=7)

        ttk.Label(server_frame, text="API token").grid(
            row=1,
            column=0,
            pady=(10, 0),
            sticky="w",
        )
        self.token_entry = ttk.Entry(
            server_frame,
            textvariable=self.token_variable,
            show="•",
        )
        self.token_entry.grid(
            row=1,
            column=1,
            columnspan=4,
            padx=(4, 12),
            pady=(10, 0),
            sticky="ew",
        )
        ttk.Checkbutton(
            server_frame,
            text="Show",
            variable=self.show_token_variable,
            command=self._toggle_token_visibility,
        ).grid(row=1, column=5, pady=(10, 0), sticky="w")
        self.generate_token_button = ttk.Button(
            server_frame,
            text="Generate",
            command=self._generate_token,
        )
        self.generate_token_button.grid(row=1, column=6, pady=(10, 0), sticky="ew")
        ttk.Button(
            server_frame,
            text="Copy",
            command=self._copy_token,
        ).grid(row=1, column=7, padx=(8, 0), pady=(10, 0), sticky="ew")

        roots_header = ttk.Frame(outer)
        roots_header.grid(row=1, column=0, pady=(12, 6), sticky="ew")
        ttk.Label(roots_header, text="Gallery roots").pack(side="left")
        self.remove_button = ttk.Button(
            roots_header,
            text="Remove",
            command=self._remove_root,
        )
        self.remove_button.pack(side="right")
        self.edit_button = ttk.Button(
            roots_header,
            text="Edit",
            command=self._edit_root,
        )
        self.edit_button.pack(side="right", padx=6)
        self.add_button = ttk.Button(
            roots_header,
            text="Add",
            command=self._add_root,
        )
        self.add_button.pack(side="right")

        columns = ("enabled", "name", "path", "trash")
        self.root_tree = ttk.Treeview(
            outer,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.root_tree.heading("enabled", text="Enabled")
        self.root_tree.heading("name", text="Name")
        self.root_tree.heading("path", text="Gallery folder")
        self.root_tree.heading("trash", text="Trash folder")
        self.root_tree.column("enabled", width=70, stretch=False, anchor="center")
        self.root_tree.column("name", width=170)
        self.root_tree.column("path", width=300)
        self.root_tree.column("trash", width=300)
        self.root_tree.grid(row=2, column=0, sticky="nsew")
        self.root_tree.bind("<Double-1>", lambda _event: self._edit_root())

        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, pady=12, sticky="ew")
        self.save_button = ttk.Button(
            actions,
            text="Save configuration",
            command=self._save,
        )
        self.save_button.pack(side="left")
        self.scan_button = ttk.Button(
            actions,
            text="Scan now",
            command=self._scan,
        )
        self.scan_button.pack(side="left", padx=8)
        ttk.Label(actions, textvariable=self.summary_variable).pack(
            side="left",
            padx=8,
        )

        ttk.Label(outer, text=f"Configuration: {self.config_path}").grid(
            row=4,
            column=0,
            pady=(0, 6),
            sticky="w",
        )

        log_frame = ttk.LabelFrame(outer, text="Activity", padding=6)
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

    def _selected_index(self) -> int | None:
        selection = self.root_tree.selection()

        if not selection:
            return None

        return int(selection[0])

    def _refresh_roots(self) -> None:
        self.root_tree.delete(*self.root_tree.get_children())

        for index, root in enumerate(self.roots):
            self.root_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "Yes" if root.enabled else "No",
                    root.name,
                    root.path,
                    root.trash_path,
                ),
            )

    def _add_root(self) -> None:
        dialog = RootDialog(self.window)
        self.window.wait_window(dialog)

        if dialog.result is not None:
            self.roots.append(dialog.result)
            self._refresh_roots()

    def _edit_root(self) -> None:
        index = self._selected_index()

        if index is None:
            return

        dialog = RootDialog(self.window, self.roots[index])
        self.window.wait_window(dialog)

        if dialog.result is not None:
            self.roots[index] = dialog.result
            self._refresh_roots()
            self.root_tree.selection_set(str(index))

    def _remove_root(self) -> None:
        index = self._selected_index()

        if index is None:
            return

        root = self.roots[index]
        confirmed = messagebox.askyesno(
            "Remove gallery root",
            f"Remove {root.name!r} from the configuration?\n\n"
            "No image files will be deleted.",
            parent=self.window,
        )

        if confirmed:
            self.roots.pop(index)
            self._refresh_roots()

    def _build_config(self) -> AppConfig:
        token = self.token_variable.get().strip()
        host = self.host_variable.get().strip()

        if not host:
            raise ValueError("The server host is required")

        return AppConfig(
            server=ServerConfig(
                host=host,
                port=int(self.port_variable.get()),
            ),
            security=SecurityConfig(
                api_token=SecretStr(token),
            ),
            storage=self.config.storage,
            gallery_roots=self.roots,
        )

    def _save(self, *, notify: bool = True) -> AppConfig | None:
        try:
            candidate = self._build_config()

            if len(self.token_variable.get().strip()) < 32:
                raise ValueError("The API token must contain at least 32 characters")

            self.config = save_config(candidate, self.config_path)
            self.roots = list(self.config.gallery_roots)
            self._refresh_roots()
        except (OSError, ValueError, ValidationError) as exc:
            messagebox.showerror("Unable to save configuration", str(exc))
            return None

        if notify:
            self._append_log("Configuration saved.")

        return self.config

    def _toggle_server(self) -> None:
        if self.server.running:
            self.status_variable.set("Stopping…")
            self.server_button.configure(state="disabled")
            threading.Thread(
                target=self._stop_server_worker,
                name="gallery-komganion-stop",
                daemon=True,
            ).start()
            return

        config = self._save(notify=False)

        if config is None:
            return

        try:
            self.server.start(config, self.config_path)
        except Exception as exc:
            messagebox.showerror("Unable to start server", str(exc))
            return

        self.status_variable.set("Running")
        self._append_log(
            f"Server started at http://{config.server.host}:{config.server.port}"
        )
        self._set_controls()

    def _stop_server_worker(self) -> None:
        self.server.stop()
        self.events.put(("server_stopped", None))

    def _scan(self) -> None:
        config = self._save(notify=False)

        if config is None:
            return

        self.busy = True
        self.summary_variable.set("Scanning…")
        self._set_controls()
        threading.Thread(
            target=self._scan_worker,
            args=(config,),
            name="gallery-komganion-scan",
            daemon=True,
        ).start()

    def _scan_worker(self, config: AppConfig) -> None:
        try:
            summary = scan_config(
                config,
                progress=lambda message: self.events.put(("log", message)),
            )
            self.events.put(("scan_complete", summary))
        except Exception as exc:
            self.events.put(("error", exc))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()

                if event == "log":
                    self._append_log(str(payload))
                elif event == "scan_complete":
                    self._scan_finished(payload)
                elif event == "server_stopped":
                    self.status_variable.set("Stopped")
                    self._append_log("Server stopped.")
                    self._set_controls()
                elif event == "error":
                    self.busy = False
                    self.summary_variable.set("Scan failed")
                    self._set_controls()
                    messagebox.showerror("Operation failed", str(payload))
        except queue.Empty:
            pass

        self.window.after(150, self._poll_events)

    def _scan_finished(self, payload: object) -> None:
        if not isinstance(payload, ScanSummary):
            return

        self.busy = False
        self.summary_variable.set(
            f"Roots {payload.roots_scanned} · Created {payload.created} · "
            f"Updated {payload.updated} · Missing {payload.marked_missing} · "
            f"Pages {payload.indexed_pages}"
        )

        for error in payload.errors:
            self._append_log(f"ERROR: {error}")

        if not payload.errors:
            self._append_log("Scan completed successfully.")

        self._set_controls()

    def _set_controls(self) -> None:
        editing_state = "disabled" if self.server.running or self.busy else "normal"
        scan_state = "disabled" if self.busy else "normal"

        for widget in (
            self.host_entry,
            self.port_entry,
            self.token_entry,
            self.generate_token_button,
            self.add_button,
            self.edit_button,
            self.remove_button,
            self.save_button,
        ):
            widget.configure(state=editing_state)

        self.scan_button.configure(state=scan_state)
        self.server_button.configure(
            state="normal",
            text="Stop server" if self.server.running else "Start server",
        )
        self.docs_button.configure(
            state="normal" if self.server.running else "disabled"
        )

    def _toggle_token_visibility(self) -> None:
        self.token_entry.configure(
            show="" if self.show_token_variable.get() else "•"
        )

    def _generate_token(self) -> None:
        self.token_variable.set(secrets.token_urlsafe(32))
        self.summary_variable.set("New API token generated; save configuration")

    def _copy_token(self) -> None:
        self.window.clipboard_clear()
        self.window.clipboard_append(self.token_variable.get())
        self.summary_variable.set("API token copied")

    def _open_docs(self) -> None:
        host = self.host_variable.get().strip()

        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"

        webbrowser.open(f"http://{host}:{self.port_variable.get()}/docs")

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _close(self) -> None:
        if self.server.running:
            self.server.stop(timeout=5)

        self.window.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the Gallery Komganion control panel.")
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="Configuration TOML path.",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = build_parser().parse_args(arguments)
    window = tk.Tk()

    try:
        ControlPanel(window, parsed.config)
    except Exception as exc:
        window.withdraw()
        messagebox.showerror("Gallery Komganion", str(exc))
        window.destroy()
        return 1

    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
