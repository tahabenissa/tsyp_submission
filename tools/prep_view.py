"""Preparation view: read-only display of explain figures and check counts.

A new window (Toplevel) next to tools/l1_gui.py. It never recomputes
anything: it only reads PNG figures, their French caption .txt files, and
validation_checks.csv from the directory named in config/preparation.yaml.

Pillow is NOT in project requirements.txt, so figures are shown with
tkinter.PhotoImage (PNG works on Tk builds that include imgpng; otherwise a
fallback message is shown).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "preparation.yaml"

_STATUS_ORDER = ("PASS", "WARN", "FAIL", "NA")


def load_config() -> dict[str, Any]:
    """Read config/preparation.yaml (path taken from this file's location,
    never hard-coded)."""
    with _CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def explain_dir(config: dict[str, Any]) -> Path:
    """Full path to the explain figures directory, from config only."""
    output = Path(config.get("output_directory", "results/models_fixed"))
    sub = config.get("plot", {}).get("explain_directory", "figures/explain")
    return _REPO_ROOT / output / sub


def gui_dir(config: dict[str, Any]) -> Path:
    """Full path to the GUI (smaller) copies directory, from config only."""
    output = Path(config.get("output_directory", "results/models_fixed"))
    sub = config.get("plot", {}).get("gui_subfolder", "gui")
    return _REPO_ROOT / output / "figures" / sub


def checks_path(config: dict[str, Any]) -> Path:
    """Full path to validation_checks.csv, from config only."""
    output = Path(config.get("output_directory", "results/models_fixed"))
    return _REPO_ROOT / output / "validation_checks.csv"


def discover_sites(config: dict[str, Any]) -> list[str]:
    """Site names declared in config (fawn, azmet, kansas ...)."""
    return sorted(config.get("sites", {}).keys())


def discover_figure_types(folder: Path) -> list[str]:
    """Figure types discovered from ``{site}_{type}.png`` files, not hard-coded."""
    found: set[str] = set()
    if folder.is_dir():
        for path in folder.glob("*.png"):
            stem = path.stem
            if "_" in stem:
                found.add(stem.split("_", 1)[1])
    return sorted(found)


def _site_counts(config: dict[str, Any], site: str) -> dict[str, int]:
    """PASS/WARN/FAIL/NA row counts for one site (read-only, from CSV)."""
    counts = {status: 0 for status in _STATUS_ORDER}
    path = checks_path(config)
    if not path.is_file():
        return counts
    frame = pd.read_csv(path, keep_default_na=False)
    if "site" not in frame.columns or "status" not in frame.columns:
        return counts
    sub = frame[frame["site"].astype(str) == str(site)]
    observed = sub["status"].astype(str).value_counts()
    for status in _STATUS_ORDER:
        counts[status] = int(observed.get(status, 0))
    return counts


class PreparationView:
    """Read-only window: pick a site and a figure type, show PNG + caption
    + per-site PASS/WARN/FAIL/NA table."""

    def __init__(self, master: tk.Misc):
        self.master = master
        self.top = tk.Toplevel(master)
        self.top.title("SensorGuard — Preparation (lecture seule)")
        self.top.geometry("940x820")

        self.config: dict[str, Any] = {}
        self.sites: list[str] = []
        self.figure_types: list[str] = []
        self._photo: tk.PhotoImage | None = None

        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.top, padding=10)
        container.pack(fill="both", expand=True)

        bar = ttk.Frame(container)
        bar.pack(fill="x", pady=(0, 8))

        ttk.Label(bar, text="Site:").pack(side="left")
        self.site_var = tk.StringVar()
        self.site_box = ttk.Combobox(
            bar, textvariable=self.site_var, state="readonly", width=14
        )
        self.site_box.pack(side="left", padx=(4, 18))

        ttk.Label(bar, text="Figure:").pack(side="left")
        self.figure_var = tk.StringVar()
        self.figure_box = ttk.Combobox(
            bar, textvariable=self.figure_var, state="readonly", width=34
        )
        self.figure_box.pack(side="left", padx=(4, 0))

        self.site_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh())
        self.figure_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh())

        self.zoom_mode = tk.StringVar(value="fit")

        image_frame = ttk.Frame(container, relief="solid", borderwidth=1)
        image_frame.pack(fill="both", expand=True, pady=(0, 8))
        image_frame.rowconfigure(0, weight=1)
        image_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(image_frame, bg="white", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb = ttk.Scrollbar(image_frame, orient="vertical", command=self.canvas.yview)
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb = ttk.Scrollbar(image_frame, orient="horizontal", command=self.canvas.xview)
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)

        self.canvas_image_id = None
        self._base_photo: tk.PhotoImage | None = None
        self._photo: tk.PhotoImage | None = None

        zoom_bar = ttk.Frame(container)
        zoom_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(zoom_bar, text="Affichage :").pack(side="left")
        ttk.Radiobutton(
            zoom_bar, text="Adapter (Fit)", variable=self.zoom_mode, value="fit",
            command=self._apply_zoom,
        ).pack(side="left", padx=(4, 8))
        ttk.Radiobutton(
            zoom_bar, text="Taille reelle (100%)", variable=self.zoom_mode, value="native",
            command=self._apply_zoom,
        ).pack(side="left", padx=(4, 8))

        self.canvas.bind("<Configure>", lambda _e: self._on_canvas_configure())

        self.caption_var = tk.StringVar(value="")
        self.caption_label = tk.Label(
            container,
            textvariable=self.caption_var,
            justify="left",
            anchor="w",
            wraplength=900,
            font=("Segoe UI", 10),
            fg="#333333",
        )
        self.caption_label.pack(fill="x", pady=(0, 10))

        ttk.Label(container, text="site — PASS / WARN / FAIL / NA").pack(
            anchor="w"
        )
        self.tree = ttk.Treeview(
            container,
            columns=("status", "count"),
            show="headings",
            height=len(_STATUS_ORDER) + 1,
        )
        self.tree.heading("status", text="Statut")
        self.tree.heading("count", text="Nombre de vérifications")
        self.tree.column("status", width=120, anchor="w")
        self.tree.column("count", width=260, anchor="center")
        self.tree.pack(fill="x", pady=(0, 8))

        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            container, textvariable=self.status_var, anchor="w", font=("Segoe UI", 9),
            fg="#666666",
        )
        self.status_label.pack(fill="x")

    def _config_error(self, exc: Exception) -> None:
        self.site_box["values"] = []
        self.figure_box["values"] = []
        self.caption_var.set(f"Impossible de lire config/preparation.yaml : {exc}")
        self.status_var.set("")

    def _reload(self) -> None:
        try:
            self.config = load_config()
        except Exception as exc:  # pragma: no cover - config missing at runtime
            self._config_error(exc)
            return
        self.sites = discover_sites(self.config)
        folder = explain_dir(self.config)
        self.figure_types = discover_figure_types(folder)

        self.site_box["values"] = self.sites
        self.figure_box["values"] = self.figure_types

        if self.sites:
            self.site_var.set(self.sites[0])
        if self.figure_types:
            self.figure_var.set(self.figure_types[0])
        self._refresh()

    def _refresh(self) -> None:
        site = self.site_var.get()
        ftype = self.figure_var.get()
        if not site or not ftype:
            return
        self._show_figure(site, ftype)
        self._show_caption(site, ftype)
        self._show_counts(site)

    def _figure_path(self, site: str, ftype: str) -> Path | None:
        """Prefer the smaller GUI copy when available, then the explain figure."""
        for folder in (gui_dir(self.config), explain_dir(self.config)):
            path = folder / f"{site}_{ftype}.png"
            if path.is_file():
                return path
        return None

    def _on_canvas_configure(self) -> None:
        if self.zoom_mode.get() == "fit" and self._base_photo is not None:
            self._apply_zoom()

    def _apply_zoom(self) -> None:
        base = self._base_photo
        if base is None:
            return
        self.canvas.delete("all")
        self.canvas_image_id = None
        self._photo = None
        canvas = self.canvas
        canvas.update_idletasks()
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        iw = base.width()
        ih = base.height()
        if self.zoom_mode.get() == "fit" and (iw > cw or ih > ch):
            factor = max((iw + cw - 1) // cw, (ih + ch - 1) // ch, 1)
            photo = base.subsample(factor, factor)
        else:
            photo = base
        self._photo = photo
        self.canvas_image_id = canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, photo.width(), photo.height()))

    def _show_figure(self, site: str, ftype: str) -> None:
        self.canvas.delete("all")
        self.canvas_image_id = None
        self._base_photo = None
        self._photo = None
        path = self._figure_path(site, ftype)
        if path is None:
            self.canvas.create_text(
                10, 10, anchor="nw", text=f"(aucune figure pour {site} / {ftype})",
                fill="#999999",
            )
            self.status_var.set(f"figure introuvable : {site}_{ftype}.png")
            return
        try:
            base = tk.PhotoImage(file=str(path))
        except tk.TclError as exc:  # PNG not supported by this Tk build
            self.canvas.create_text(
                10, 10, anchor="nw",
                text=f"(figure PNG non affichable directement par ce Tk : {exc})",
                fill="#999999",
            )
            self.status_var.set("PNG non pris en charge par ce build Tk")
            return
        self._base_photo = base
        self._apply_zoom()
        self.status_var.set(f"figure : {path.name}")

    def _show_caption(self, site: str, ftype: str) -> None:
        path = explain_dir(self.config) / f"{site}_{ftype}.txt"
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
        else:
            text = "(aucune légende disponible)"
        self.caption_var.set(text)

    def _show_counts(self, site: str) -> None:
        for child in self.tree.get_children():
            self.tree.delete(child)
        counts = _site_counts(self.config, site)
        total = 0
        for status in _STATUS_ORDER:
            value = counts[status]
            total += value
            self.tree.insert(
                "", "end", values=(status, value),
                tags=(status.lower(),),
            )
        self.tree.insert("", "end", values=("Total", total), tags=("total",))
        for tag, color in (("fail", "#b4231f"), ("warn", "#b5720a"),
                           ("pass", "#1b7f4b"), ("na", "#5b5b5b"),
                           ("total", "#1f3b5c")):
            self.tree.tag_configure(tag, foreground=color)


def main() -> None:
    root = tk.Tk()
    PreparationView(root)
    root.mainloop()


if __name__ == "__main__":
    main()