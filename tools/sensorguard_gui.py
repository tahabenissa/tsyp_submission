"""SensorGuard control room: run and inspect the whole defence, on our sites or on any new data.

    .\\.venv\\Scripts\\python tools\\sensorguard_gui.py        (or: mingw32-make gui)

Tabs
  Assess data       load ANY station file (CSV or Excel), map its columns, give the
                    coordinates, and run the whole defence on it: calibration against
                    NASA POWER, detectors, probability, trust, responses, decision.
                    This is file mode, what the jury's hidden-site test looks like.
  Simulate attack   pick a development site and an attack (step, drift, replay, its
                    size and date) and an attacker position (P1 station, P2 link,
                    P3 pipeline); see layer 1 and the detectors catch it or not.
  Experiments       run the tests and the full evaluations, read their result tables.
  Configs & docs    read every setting and every document.

Every result view has the same pages: Summary, Data, Residuals, Detectors, Trust,
Decision, Table.  Plots can be zoomed and panned with the toolbar under them.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sensorguard import assess as A  # noqa: E402
from sensorguard import pipeline as pl  # noqa: E402
from sensorguard.detect.trust_score import DEWEIGHTED, QUARANTINED  # noqa: E402
from sensorguard.trust import verify as vfy  # noqa: E402

PY = sys.executable
NONE = "(none)"
BAND_COLOURS = {"trusted": "#e8f5e9", "de-weighted": "#fff3cd", "quarantined": "#f8d7da"}
LEVEL_NAMES = {0: "normal", 1: "dry", 2: "severe drought"}
NAMES = {"temp_c": "temperature (°C)", "rh_pct": "humidity (%)", "wind_ms": "wind (m/s)",
         "precip_mm": "rain (mm)", "solar_mj_m2": "solar (MJ/m²)"}


# =========================================================================== helpers


def worker(root: tk.Tk, job, done, fail, status=None):
    """Run ``job(progress)`` in a thread; call ``done(result)`` or ``fail(text)`` back in the UI thread."""
    q: queue.Queue = queue.Queue()

    def run():
        try:
            q.put(("ok", job(lambda msg: q.put(("msg", msg)))))
        except Exception as exc:  # shown to the user, never swallowed
            q.put(("err", f"{exc}\n\n{traceback.format_exc()}"))

    def poll():
        try:
            while True:
                kind, value = q.get_nowait()
                if kind == "msg":
                    if status:
                        status(value)
                    continue
                (done if kind == "ok" else fail)(value)
                return
        except queue.Empty:
            root.after(150, poll)

    threading.Thread(target=run, daemon=True).start()
    root.after(150, poll)


def table(parent, columns, height=12) -> ttk.Treeview:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
    for c in columns:
        tree.heading(c, text=c)
        tree.column(c, width=110, anchor="w", stretch=True)
    ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    xs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    tree.grid(row=0, column=0, sticky="nsew"); ys.grid(row=0, column=1, sticky="ns"); xs.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
    return tree


def fill(tree: ttk.Treeview, df: pd.DataFrame, limit: int = 5000):
    tree.delete(*tree.get_children())
    cols = list(df.columns)
    tree.configure(columns=cols)
    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, width=max(80, min(260, 9 * len(c))), anchor="w")
    for _, row in df.head(limit).iterrows():
        tree.insert("", "end", values=[_fmt(v) for v in row])


def _fmt(v):
    if isinstance(v, pd.Timestamp):
        return str(v.date())
    if isinstance(v, float):
        return "" if np.isnan(v) else f"{v:.3f}"
    return v


def text_box(parent, height=20) -> tk.Text:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    t = tk.Text(frame, wrap="none", height=height, font=("Consolas", 10))
    ys = ttk.Scrollbar(frame, orient="vertical", command=t.yview)
    xs = ttk.Scrollbar(frame, orient="horizontal", command=t.xview)
    t.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    t.grid(row=0, column=0, sticky="nsew"); ys.grid(row=0, column=1, sticky="ns"); xs.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
    return t


def set_text(t: tk.Text, s: str):
    t.configure(state="normal"); t.delete("1.0", "end"); t.insert("1.0", s); t.configure(state="disabled")


# =========================================================================== result viewer


class ResultView(ttk.Notebook):
    """The pages that show one assessment: the same for new data and for simulations."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result: A.Assessment | None = None
        self.extra = ""                      # text added by the simulation (layer 1, verdict)
        self.summary = text_box(self._page("Summary"))
        self.var = tk.StringVar(value="temp_c")
        self.figs = {}
        for name in ("Data", "Residuals", "Detectors", "Trust", "Decision"):
            self.figs[name] = self._figure_page(name, with_variable=name in ("Data", "Residuals"))
        page = self._page("Table")
        bar = ttk.Frame(page); bar.pack(fill="x")
        self.table_choice = tk.StringVar(value="daily")
        for key in ("daily", "actions", "episodes", "residuals", "series used"):
            ttk.Radiobutton(bar, text=key, value=key, variable=self.table_choice, command=self._fill_table).pack(side="left", padx=4)
        self.tree = table(page, ["-"], 20)

    def _page(self, title):
        f = ttk.Frame(self, padding=4)
        self.add(f, text=title)
        return f

    def _figure_page(self, title, with_variable=False):
        page = self._page(title)
        if with_variable:
            bar = ttk.Frame(page); bar.pack(fill="x")
            ttk.Label(bar, text="variable").pack(side="left")
            cb = ttk.Combobox(bar, textvariable=self.var, values=A.VARIABLES, width=14, state="readonly")
            cb.pack(side="left", padx=4)
            cb.bind("<<ComboboxSelected>>", lambda _e: self.redraw())
        fig = Figure(figsize=(9, 6), dpi=90)
        canvas = FigureCanvasTkAgg(fig, master=page)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(canvas, page).update()
        return fig, canvas

    # ------------------------------------------------------------------ show

    def show(self, result: A.Assessment, extra: str = ""):
        self.result, self.extra = result, extra
        if self.var.get() not in result.variables:
            self.var.set(result.variables[0])
        self._fill_summary()
        self._fill_table()
        self.redraw()

    def redraw(self):
        if self.result is None:
            return
        for name, draw in (("Data", self._draw_data), ("Residuals", self._draw_residuals),
                           ("Detectors", self._draw_detectors), ("Trust", self._draw_trust),
                           ("Decision", self._draw_decision)):
            fig, canvas = self.figs[name]
            fig.clear()
            try:
                draw(fig)
            except Exception as exc:
                fig.text(0.5, 0.5, f"cannot draw: {exc}", ha="center")
            fig.tight_layout()
            canvas.draw_idle()

    # ------------------------------------------------------------------ pages

    def _fill_summary(self):
        r = self.result
        lines = ["RESULT", "======"]
        lines += [f"{k:>42} : {v}" for k, v in r.summary().items()]
        lines += [f"{'band limits':>42} : de-weight below {r.bands.deweight:.3f}, quarantine below {r.bands.quarantine:.3f}"]
        lines += [f"{'detector thresholds':>42} : " + ", ".join(f"{k} {v:.3g}" for k, v in r.thresholds.items())]
        lines += [f"{'time':>42} : " + ", ".join(f"{k} {v:.1f}s" for k, v in r.seconds.items())]
        if r.warnings:
            lines += ["", "WARNINGS"] + [f"  - {w}" for w in r.warnings]
        if self.extra:
            lines += ["", self.extra]
        lines += ["", "ACTIONS (what the operator receives)", "-" * 36]
        lines += [r.actions.to_string(index=False)] if len(r.actions) else ["  none: the station stayed trusted"]
        lines += ["", "CUSUM EPISODES (estimated onset, type, variable)", "-" * 48]
        lines += [pd.DataFrame(r.episodes).to_string(index=False)] if r.episodes else ["  none"]
        if len(r.decisions.columns):
            d = r.decisions
            changed = (d["decision_as_received"] != d["decision_with_defence"]) & d["decision_as_received"].notna()
            lines += ["", "DECISION", "--------",
                      f"  days at each level as received:  {d['decision_as_received'].map(LEVEL_NAMES).value_counts().to_dict()}",
                      f"  days at each level with defence: {d['decision_with_defence'].map(LEVEL_NAMES).value_counts().to_dict()}",
                      f"  days the defence changed the decision: {int(changed.sum())}",
                      f"  days issued DEGRADED (pending verification): {int((d['confidence'] == 'DEGRADED').sum())}"]
        set_text(self.summary, "\n".join(lines))

    def _fill_table(self):
        r = self.result
        if r is None:
            return
        choice = self.table_choice.get()
        if choice == "daily":
            df = pd.concat([r.probability.rename("probability"), r.trust, r.band, r.weight, r.decisions, r.detectors], axis=1)
        elif choice == "actions":
            df = r.actions
        elif choice == "episodes":
            df = pd.DataFrame(r.episodes)
        elif choice == "residuals":
            df = r.residuals.loc[r.periods["validation_start"]:r.periods["validation_end"]]
        else:
            df = r.used.loc[r.periods["validation_start"]:r.periods["validation_end"]]
        df = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
        fill(self.tree, df if len(df) else pd.DataFrame({"-": ["nothing"]}))

    # ------------------------------------------------------------------ plots

    def _context(self, ax, score_only=False):
        """Shade the fit period grey and the true attack (simulations) red."""
        r = self.result
        if not score_only:
            ax.axvspan(pd.Timestamp(r.periods["train_start"]), pd.Timestamp(r.periods["train_end"]), color="#eeeeee", zorder=0)
        if r.labels is not None and "attacked" in r.labels:
            att = r.labels["attacked"].astype(bool)
            for start, end in _runs(att):
                ax.axvspan(start, end, color="#f5b7b1", alpha=0.6, zorder=0)

    def _score_index(self):
        r = self.result
        return slice(r.periods["validation_start"], r.periods["validation_end"])

    def _draw_data(self, fig):
        r, v = self.result, self.var.get()
        ax = fig.add_subplot(2, 1, 1)
        self._context(ax)
        ax.plot(r.station.index, r.station[v], lw=0.8, label="station")
        ax.plot(r.reference.index, r.reference[v], lw=0.8, alpha=0.8, label="NASA POWER")
        if v in r.reference_calibrated:
            ax.plot(r.reference_calibrated.index, r.reference_calibrated[v], lw=0.8, alpha=0.8, label="POWER, calibrated to the station")
        ax.set_title(f"{NAMES[v]}: station against the independent witness (grey = fit period, red = true attack)")
        ax.legend(loc="upper left", fontsize=8)
        ax2 = fig.add_subplot(2, 1, 2, sharex=ax)
        self._context(ax2)
        ax2.plot(r.used.index, r.used[v], lw=0.8, color="tab:green", label="value used downstream (after the defence)")
        ax2.plot(r.station.index, r.station[v], lw=0.5, color="tab:blue", alpha=0.5, label="station as received")
        ax2.legend(loc="upper left", fontsize=8)

    def _draw_residuals(self, fig):
        r, v = self.result, self.var.get()
        ax = fig.add_subplot(1, 1, 1)
        self._context(ax)
        if v in r.residuals:
            s = r.residuals[v]
            ax.plot(s.index, s, lw=0.5, color="0.5", label="daily residual")
            ax.plot(s.index, s.rolling(14, min_periods=7).mean(), lw=1.5, color="tab:red", label="14-day mean")
            ax.axhline(1, ls="--", lw=0.8, color="k"); ax.axhline(-1, ls="--", lw=0.8, color="k"); ax.axhline(0, lw=0.5, color="k")
        ax.set_title(f"standardized residual, station minus calibrated NASA POWER, {NAMES[v]} (in σ; ±1σ dashed)")
        ax.legend(loc="upper left", fontsize=8)

    def _draw_detectors(self, fig):
        r = self.result
        d = r.detectors
        panels = [("cusum", "CUSUM statistic (lasting offset)", False), ("mahalanobis", "Mahalanobis d² (one unusual day)", True),
                  ("replay", "replay: distance to the closest earlier week (low = copy)", True), ("trend", "trend |z| (not in the combined flag)", False)]
        ax0 = None
        for i, (name, title, log) in enumerate(panels, 1):
            ax = fig.add_subplot(len(panels), 1, i, sharex=ax0)
            ax0 = ax0 or ax
            self._context(ax, score_only=True)
            if f"{name}_score" in d:
                ax.plot(d.index, d[f"{name}_score"], lw=0.8)
                thr = r.thresholds.get(name)
                if thr:
                    ax.axhline(thr, ls="--", color="tab:red", lw=0.8)
                flags = d.index[d[f"{name}_flag"] == 1]
                ax.plot(flags, d.loc[flags, f"{name}_score"], "o", ms=3, color="tab:red")
                if log:
                    ax.set_yscale("log")
            ax.set_title(title + "  (red dashed = threshold, dots = alarms)", fontsize=9)

    def _draw_trust(self, fig):
        r = self.result
        ax = fig.add_subplot(2, 1, 1)
        self._context(ax, score_only=True)
        ax.plot(r.probability.index, r.probability, lw=0.8, color="tab:purple")
        ax.set_ylim(0, 1); ax.set_title("compromise probability, per day")
        ax2 = fig.add_subplot(2, 1, 2, sharex=ax)
        for start, end, band in _band_runs(r.band):
            ax2.axvspan(start, end, color=BAND_COLOURS[band], zorder=0)
        ax2.plot(r.trust.index, r.trust, lw=1.2, color="k", label="trust")
        ax2.axhline(r.bands.deweight, ls="--", color="#c69500", lw=0.8, label="de-weight below")
        ax2.axhline(r.bands.quarantine, ls="--", color="#c0392b", lw=0.8, label="quarantine below")
        for _, a in r.actions.iterrows():
            marker = {"quarantine": "v", "alert": None, "verification request": "^", "release": "o"}.get(a["action"])
            if marker:
                ax2.plot(a["date"], a["trust"], marker, ms=8, color={"v": "#c0392b", "^": "#c69500", "o": "tab:green"}[marker])
        ax2.set_ylim(0, 1.02)
        ax2.set_title("trust (background: green trusted, yellow de-weighted, red quarantined; ▼ quarantine + alert, ▲ verification request, ● release)", fontsize=9)
        ax2.legend(loc="lower left", fontsize=8)

    def _draw_decision(self, fig):
        r = self.result
        if not len(r.decisions.columns):
            fig.text(0.5, 0.5, "no decision product (it needs all five variables)", ha="center")
            return
        ax = fig.add_subplot(2, 1, 1)
        self._context(ax)
        ax.plot(r.balance.index, r.balance["as received"], lw=0.9, label="as received")
        ax.plot(r.balance.index, r.balance["with defence"], lw=0.9, label="with the defence")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title("30-day water balance = rain − FAO-56 evapotranspiration (mm)"); ax.legend(fontsize=8)
        ax2 = fig.add_subplot(2, 1, 2)
        d = r.decisions
        self._context(ax2, score_only=True)
        ax2.step(d.index, d["decision_as_received"], where="post", label="as received")
        ax2.step(d.index, d["decision_with_defence"] + 0.05, where="post", label="with the defence")
        deg = d.index[d["confidence"] == "DEGRADED"]
        ax2.plot(deg, np.full(len(deg), 2.3), "|", color="#c0392b", label="issued DEGRADED (pending verification)")
        ax2.set_yticks([0, 1, 2]); ax2.set_yticklabels(["normal", "dry", "severe drought"]); ax2.set_ylim(-0.3, 2.5)
        ax2.set_title("decision level"); ax2.legend(fontsize=8, loc="upper left")


def _after(day, onset) -> str:
    n = (day - onset).days
    return "on the first attacked day" if n == 0 else f"after {n} days"


def _runs(mask: pd.Series):
    m = mask.astype(bool).to_numpy()
    idx = mask.index
    i = 0
    while i < len(m):
        if m[i]:
            j = i
            while j + 1 < len(m) and m[j + 1]:
                j += 1
            yield idx[i], idx[j] + pd.Timedelta(days=1)
            i = j + 1
        else:
            i += 1


def _band_runs(band: pd.Series):
    if not len(band):
        return
    start, cur = band.index[0], band.iloc[0]
    for day, b in band.items():
        if b != cur:
            yield start, day, cur
            start, cur = day, b
    yield start, band.index[-1] + pd.Timedelta(days=1), cur


# =========================================================================== tabs


class AssessTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.raw: pd.DataFrame | None = None
        self.preset: tuple | None = None        # (site, station, reference) for a development site
        left = ttk.Frame(self, padding=6); left.pack(side="left", fill="y")
        self.view = ResultView(self); self.view.pack(side="left", fill="both", expand=True)

        box = ttk.LabelFrame(left, text="1. Station data", padding=6); box.pack(fill="x")
        ttk.Button(box, text="Open a CSV / Excel file…", command=self.open_file).pack(fill="x")
        row = ttk.Frame(box); row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="or a development site:").pack(side="left")
        self.site = tk.StringVar()
        cb = ttk.Combobox(row, textvariable=self.site, values=pl.sites(), width=9, state="readonly")
        cb.pack(side="left", padx=4); cb.bind("<<ComboboxSelected>>", lambda _e: self.use_site())
        self.file_label = ttk.Label(box, text="no data loaded", wraplength=260, foreground="#555")
        self.file_label.pack(fill="x", pady=4)

        box = ttk.LabelFrame(left, text="2. Columns (recognised automatically)", padding=6); box.pack(fill="x", pady=6)
        self.date_col = tk.StringVar()
        self.map = {v: tk.StringVar(value=NONE) for v in A.VARIABLES}
        self.combos = {}
        r = 0
        for label, var in [("date", self.date_col)] + [(NAMES[v], self.map[v]) for v in A.VARIABLES]:
            ttk.Label(box, text=label).grid(row=r, column=0, sticky="w")
            c = ttk.Combobox(box, textvariable=var, width=18, state="readonly"); c.grid(row=r, column=1, pady=1)
            self.combos[label] = c
            r += 1

        box = ttk.LabelFrame(left, text="3. Place and reference", padding=6); box.pack(fill="x")
        self.lat, self.lon = tk.StringVar(), tk.StringVar()
        for i, (label, var) in enumerate((("latitude", self.lat), ("longitude (west < 0)", self.lon))):
            ttk.Label(box, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(box, textvariable=var, width=12).grid(row=i, column=1)
        self.power_file = tk.StringVar()
        ttk.Label(box, text="NASA POWER: downloaded and cached,").grid(row=2, column=0, columnspan=2, sticky="w")
        row = ttk.Frame(box); row.grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(row, text="or from a file:").pack(side="left")
        ttk.Button(row, text="choose…", command=self.choose_power).pack(side="left", padx=4)
        self.power_label = ttk.Label(box, text="(download)", foreground="#555"); self.power_label.grid(row=4, column=0, columnspan=2, sticky="w")

        box = ttk.LabelFrame(left, text="4. Periods (fit on clean days, score the rest)", padding=6); box.pack(fill="x", pady=6)
        self.periods = {k: tk.StringVar() for k in ("train_start", "train_end", "validation_start", "validation_end")}
        for i, (k, label) in enumerate((("train_start", "fit from"), ("train_end", "fit to"),
                                        ("validation_start", "score from"), ("validation_end", "score to"))):
            ttk.Label(box, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(box, textvariable=self.periods[k], width=12).grid(row=i, column=1)

        ttk.Button(left, text="▶  Run the whole defence", command=self.run).pack(fill="x", pady=(4, 2))
        ttk.Button(left, text="Export the results…", command=self.export).pack(fill="x")
        self.status = ttk.Label(left, text="", wraplength=260, foreground="#1a5276"); self.status.pack(fill="x", pady=6)

    # ------------------------------------------------------------------ inputs

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("Data", "*.csv *.xlsx *.xls"), ("All", "*.*")])
        if not path:
            return
        try:
            self.raw = A.read_table(path)
        except Exception as exc:
            messagebox.showerror("Cannot read the file", str(exc)); return
        self.preset = None
        cols = list(self.raw.columns)
        for c in self.combos.values():
            c.configure(values=[NONE] + cols)
        self.date_col.set(A.guess_date_column(cols) or cols[0])
        for v, col in A.guess_columns(cols).items():
            self.map[v].set(col or NONE)
        self.file_label.configure(text=f"{Path(path).name}: {len(self.raw)} rows, {len(cols)} columns")
        try:
            station = self._station()
            for k, v in A.default_periods(station.dropna(how="all").index).items():
                self.periods[k].set(v)
        except Exception as exc:
            self.status.configure(text=f"check the date column: {exc}")

    def use_site(self):
        site = self.site.get()
        cfg = pl.load_config()
        station, power, (lat, lon) = pl.load_site(site, cfg)
        self.preset = (site, station, power)
        self.raw = None
        for c in self.combos.values():
            c.configure(values=[NONE] + A.VARIABLES)
        self.date_col.set("date")
        for v in A.VARIABLES:
            self.map[v].set(v)
        self.lat.set(str(lat)); self.lon.set(str(lon))
        for k, v in cfg["split"].items():
            self.periods[k].set(v)
        self.power_label.configure(text="(the site's NASA POWER file)")
        self.file_label.configure(text=f"development site {site}: {station.index.min().date()} to {station.index.max().date()} (detector M available)")

    def choose_power(self):
        path = filedialog.askopenfilename(filetypes=[("Data", "*.csv *.xlsx *.xls"), ("All", "*.*")])
        if path:
            self.power_file.set(path); self.power_label.configure(text=Path(path).name)

    def _station(self) -> pd.DataFrame:
        mapping = {v: (var.get() if var.get() != NONE else None) for v, var in self.map.items()}
        return A.to_daily(self.raw, mapping, self.date_col.get())

    # ------------------------------------------------------------------ run

    def run(self):
        try:
            lat, lon = float(self.lat.get()), float(self.lon.get())
        except ValueError:
            messagebox.showerror("Coordinates", "Give the latitude and longitude as numbers."); return
        if self.raw is None and self.preset is None:
            messagebox.showerror("No data", "Open a file or choose a development site first."); return
        periods = {k: v.get().strip() for k, v in self.periods.items()}
        preset, power_file = self.preset, self.power_file.get() or None
        station = self._station() if self.raw is not None else None

        def job(progress):
            if preset is not None:
                site, st, ref = preset
                return A.assess(st, ref, lat, lon, periods, site=site, progress=progress)
            progress("NASA POWER for this place (downloaded once, then cached)")
            ref = A.reference_for(lat, lon, station.index.min(), station.index.max(), power_file)
            return A.assess(station, ref, lat, lon, periods, progress=progress)

        self.status.configure(text="running…")
        worker(self.app.root, job, self._done, self._fail, lambda m: self.status.configure(text=f"running: {m}"))

    def _done(self, result):
        self.result = result
        self.view.show(result)
        bad = int((result.band == QUARANTINED).sum())
        self.status.configure(text=f"done. Lowest trust {result.trust.min():.2f}; {bad} quarantined days; {len(result.actions)} actions.")

    def _fail(self, text):
        self.status.configure(text="failed, see the message")
        messagebox.showerror("Assessment failed", text[:3000])

    def export(self):
        if self.view.result is None:
            return
        folder = filedialog.askdirectory(initialdir=str(ROOT / "results"))
        if folder:
            self.view.result.save(folder)
            self.status.configure(text=f"saved to {folder}")


class SimulateTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        left = ttk.Frame(self, padding=6); left.pack(side="left", fill="y")
        self.view = ResultView(self); self.view.pack(side="left", fill="both", expand=True)
        self.v = {}
        box = ttk.LabelFrame(left, text="Attack", padding=6); box.pack(fill="x")
        rows = [("site", pl.sites(), "fawn"), ("attack", ["none", "step", "drift", "replay"], "step"),
                ("12 % of", ["value", "range", "std"], "value"), ("sign", ["up", "down"], "up"),
                ("position", list(pl.POSITIONS), "P1")]
        for i, (key, values, default) in enumerate(rows):
            ttk.Label(box, text=key).grid(row=i, column=0, sticky="w")
            self.v[key] = tk.StringVar(value=default)
            ttk.Combobox(box, textvariable=self.v[key], values=values, width=12, state="readonly").grid(row=i, column=1, pady=1)
        i = len(rows)
        for key, default in (("size (fraction)", "0.12"), ("onset", "2024-04-15"), ("step length, days", "60"),
                             ("ramp days (drift)", "60"), ("hold days (drift)", "30"),
                             ("replay length, days", "7"), ("replay source, days back", "7")):
            ttk.Label(box, text=key).grid(row=i, column=0, sticky="w")
            self.v[key] = tk.StringVar(value=default)
            ttk.Entry(box, textvariable=self.v[key], width=12).grid(row=i, column=1, pady=1)
            i += 1
        ttk.Label(box, text="variables (step, drift)").grid(row=i, column=0, sticky="nw")
        vf = ttk.Frame(box); vf.grid(row=i, column=1, sticky="w")
        self.vars = {v: tk.BooleanVar(value=(v == "temp_c")) for v in A.MONITORED + ["precip_mm"]}
        for v, b in self.vars.items():
            ttk.Checkbutton(vf, text=v, variable=b).pack(anchor="w")
        ttk.Label(left, text="P1 at the station: it signs the false values (only the detectors can see it).\n"
                             "P2 on the link: no station key, layer 1 rejects.\n"
                             "P3 in the pipeline: the ledger chain breaks.", wraplength=260, foreground="#555").pack(fill="x", pady=6)
        ttk.Button(left, text="▶  Inject and run", command=self.run).pack(fill="x")
        ttk.Button(left, text="Export the results…", command=self.export).pack(fill="x", pady=2)
        self.status = ttk.Label(left, text="", wraplength=260, foreground="#1a5276"); self.status.pack(fill="x", pady=6)

    def _spec(self) -> pl.AttackSpec:
        g = lambda k: self.v[k].get()  # noqa: E731
        attack = g("attack")
        length = int(g("replay length, days") if attack == "replay" else g("step length, days"))
        offset = int(g("replay source, days back"))
        if attack == "replay" and offset < length:
            # copying from fewer days back than the replay lasts would copy days the attacker already replaced
            raise ValueError(f"A replay of {length} days must copy from at least {length} days back "
                             f"(you set {offset}), so that the copied days are genuine readings.")
        return pl.AttackSpec(attack=attack, variables=tuple(v for v, b in self.vars.items() if b.get()) or ("temp_c",),
                             onset=g("onset"), magnitude=float(g("size (fraction)")), sign=1 if g("sign") == "up" else -1,
                             relative_to=g("12 % of"), length_days=length,
                             ramp_days=int(g("ramp days (drift)")), hold_days=int(g("hold days (drift)")),
                             source_offset_days=offset, position=g("position"))

    def run(self):
        try:
            spec = self._spec()
        except ValueError as exc:
            messagebox.showerror("Attack settings", str(exc)); return
        site = self.v["site"].get()

        def job(progress):
            progress("injecting the attack and sending every day through layer 1 (signatures, ledger)")
            r = pl.run(site, spec)
            res = A.assess(r.trust.received, r.power, *r.coords, periods=r.config["split"], site=site,
                           labels=r.labels, progress=progress)
            return r, res

        self.status.configure(text="running…")
        worker(self.app.root, job, self._done, self._fail, lambda m: self.status.configure(text=f"running: {m}"))

    def _done(self, out):
        r, res = out
        lines = ["LAYER 1 (provenance)", "--------------------",
                 f"  records: {r.trust.counts}", f"  ledger intact: {r.trust.ledger_ok}"
                 + (f" (first broken entry {r.trust.ledger_first_broken.date()})" if r.trust.ledger_first_broken is not None else "")]
        lines += [f"  warning: {w}" for w in r.warnings]
        verdict = "no attack injected"
        if r.attack.episodes:
            ep = r.attack.episodes[0]
            win = slice(ep.onset, ep.end)
            q = res.band.loc[win].isin([QUARANTINED])
            dw = res.band.loc[win].isin([DEWEIGHTED, QUARANTINED])
            rejected = int((r.trust.log.loc[win, "decision"] == vfy.REJECT).sum()) if "decision" in r.trust.log else 0
            first_q = q[q].index.min() if q.any() else None
            first_dw = dw[dw].index.min() if dw.any() else None
            verdict = (f"attack {ep.attack} on {', '.join(ep.variables)} from {ep.onset.date()} to {ep.end.date()}: "
                       f"{rejected} days rejected by layer 1; "
                       + (f"de-weighted {_after(first_dw, ep.onset)}; " if first_dw is not None else "never de-weighted; ")
                       + (f"QUARANTINED {_after(first_q, ep.onset)}." if first_q is not None else "never quarantined."))
            if (res.band.loc[:ep.onset - pd.Timedelta(days=1)].tail(1) == QUARANTINED).any():
                verdict += " (the station was already quarantined before the attack began)"
        lines += ["", "VERDICT", "-------", "  " + verdict]
        self.view.show(res, "\n".join(lines))
        self.status.configure(text=verdict)

    def _fail(self, text):
        self.status.configure(text="failed, see the message")
        messagebox.showerror("Simulation failed", text[:3000])

    def export(self):
        if self.view.result is None:
            return
        folder = filedialog.askdirectory(initialdir=str(ROOT / "results"))
        if folder:
            self.view.result.save(folder)
            self.status.configure(text=f"saved to {folder}")


class ExperimentsTab(ttk.Frame):
    COMMANDS = [
        ("Run the tests (about 1 min)", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
        ("Standard scenario, quick check", [PY, "scripts/run_all.py", "--quick"]),
        ("Standard scenario, full (about 10 min)", [PY, "scripts/run_all.py"]),
        ("Trust and decisions, quick check", [PY, "scripts/run_trust.py", "--quick"]),
        ("Trust and decisions, full (about 12 min)", [PY, "scripts/run_trust.py"]),
        ("Re-train the fusion model (about 10 min)", [PY, "scripts/train_fusion.py"]),
    ]
    SUMMARIES = {"standard scenario": "results/eval/standard/summary.md", "trust and decisions": "results/eval/trust/summary.md",
                 "fusion model": "results/models_fusion/fusion.json"}

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.proc: subprocess.Popen | None = None
        left = ttk.Frame(self, padding=6); left.pack(side="left", fill="y")
        right = ttk.Notebook(self); right.pack(side="left", fill="both", expand=True)
        box = ttk.LabelFrame(left, text="Run", padding=6); box.pack(fill="x")
        for label, cmd in self.COMMANDS:
            ttk.Button(box, text=label, command=lambda c=cmd: self.start(c)).pack(fill="x", pady=1)
        ttk.Button(box, text="■ Stop", command=self.stop).pack(fill="x", pady=(6, 0))
        box = ttk.LabelFrame(left, text="Read the results", padding=6); box.pack(fill="x", pady=8)
        for label, path in self.SUMMARIES.items():
            ttk.Button(box, text=label, command=lambda p=path: self.read(p)).pack(fill="x", pady=1)
        ttk.Button(box, text="Open the results folder", command=lambda: os.startfile(ROOT / "results")).pack(fill="x", pady=(6, 0))
        f = ttk.Frame(right); right.add(f, text="Output")
        self.log = text_box(f)
        f = ttk.Frame(right); right.add(f, text="Results")
        self.results = text_box(f)
        self.tabs = right

    def start(self, cmd):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("Busy", "A run is already going. Stop it first."); return
        set_text(self.log, "$ " + " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd)) + "\n")
        self.tabs.select(0)
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", env=env,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        q: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: [q.put(line) for line in self.proc.stdout] + [q.put(None)], daemon=True).start()

        def poll():
            try:
                while True:
                    line = q.get_nowait()
                    if line is None:
                        self._append(f"\n[finished, exit code {self.proc.wait()}]\n"); return
                    self._append(line)
            except queue.Empty:
                self.app.root.after(200, poll)
        poll()

    def _append(self, s):
        self.log.configure(state="normal"); self.log.insert("end", s); self.log.see("end"); self.log.configure(state="disabled")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate(); self._append("\n[stopped]\n")

    def read(self, rel):
        path = ROOT / rel
        set_text(self.results, path.read_text(encoding="utf-8") if path.is_file() else f"{rel} does not exist yet: run it first.")
        self.tabs.select(1)


class FilesTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        left = ttk.Frame(self, padding=6); left.pack(side="left", fill="y")
        self.files = sorted([*ROOT.glob("config/*.yaml"), ROOT / "README.md", *ROOT.glob("docs/*.md"), ROOT / "tools/README.md"])
        lb = tk.Listbox(left, width=38, height=40)
        for p in self.files:
            lb.insert("end", str(p.relative_to(ROOT)))
        lb.pack(fill="y", expand=True)
        lb.bind("<<ListboxSelect>>", lambda _e: self.show(lb.curselection()))
        ttk.Button(left, text="Open in the default editor", command=self.open_external).pack(fill="x", pady=4)
        self.text = text_box(self)
        self.current: Path | None = None

    def show(self, sel):
        if sel:
            self.current = self.files[sel[0]]
            set_text(self.text, self.current.read_text(encoding="utf-8", errors="replace"))

    def open_external(self):
        if self.current:
            os.startfile(self.current)


# =========================================================================== app


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SensorGuard: trusted in-situ weather data")
        self.root.geometry("1450x900")
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)
        for title, cls in (("Assess data", AssessTab), ("Simulate attack", SimulateTab),
                           ("Experiments", ExperimentsTab), ("Configs & docs", FilesTab)):
            nb.add(cls(nb, self), text=f"  {title}  ")
        if not A.FUSION_FILE.is_file():
            self.root.after(500, lambda: messagebox.showwarning(
                "Fusion model missing", "results/models_fusion/fusion.joblib is missing.\n"
                "Open Experiments and run 'Re-train the fusion model' once (about 10 min)."))

    def run(self):
        self.root.mainloop()


def main():
    App().run()


if __name__ == "__main__":
    main()
