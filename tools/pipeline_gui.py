"""Pipeline lab: run the whole chain on real data and see what each stage does.

Run it:
    .venv\\Scripts\\python tools\\pipeline_gui.py
or:
    mingw32-make pipeline-gui

Pick a site, an attack and where the attacker sits, then press Run. The real
code runs, stage by stage (src/sensorguard/pipeline.py):

    1 Data         clean station series + NASA POWER witness
    2 Attack       step / drift / replay, with exact labels
    3 Layer 1      every day signed, sent, verified, stored in the ledger
    4 Preparation  calibration + reference and temporal residuals
    5 Screen       |rolling mean of a residual| > threshold  (placeholder, not detector S/M)

The strip at the top shows what each stage saw, and the line under it says who
caught the attack: layer 1 (P2), the ledger (P3) or only the residuals (P1).
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import matplotlib

matplotlib.use("TkAgg")
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from sensorguard import pipeline as p  # noqa: E402

HERE = Path(__file__).resolve().parent

GREEN, RED, ORANGE, GREY, BLUE, PURPLE, BG = (
    "#1b7f4b", "#b4231f", "#b5720a", "#5b5b5b", "#2f6fdd", "#7a2fae", "#f4f5f7")
IDLE = "#e3e5ea"
MONO = ("Consolas", 9)
UI = ("Segoe UI", 9)
UI_B = ("Segoe UI", 9, "bold")

STAGES = ["1  Data", "2  Attack", "3  Layer 1", "4  Preparation", "5  Screen"]
DECISION_COLOR = {"accept": GREEN, "flag": ORANGE, "reject": RED}


class PipelineLab:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SensorGuard — pipeline lab")
        self.root.configure(bg=BG)
        self.root.geometry("1440x900")
        self.cfg = p.load_config()
        self.result: p.PipelineResult | None = None
        self.scr: pd.DataFrame | None = None
        self.jobs: queue.Queue = queue.Queue()
        self.v = {
            "site": tk.StringVar(value=p.sites(self.cfg)[0]),
            "attack": tk.StringVar(value="step"),
            "variable": tk.StringVar(value="temp_c"),
            "onset": tk.StringVar(value="2024-04-01"),
            "magnitude": tk.StringVar(value="12"),
            "sign": tk.StringVar(value="up"),
            "relative_to": tk.StringVar(value="value"),
            "length": tk.StringVar(value="60"),
            "ramp": tk.StringVar(value="30"),
            "hold": tk.StringVar(value="30"),
            "back": tk.StringVar(value="7"),
            "position": tk.StringVar(value="P1"),
            "family": tk.StringVar(value="reference"),
            "window": tk.StringVar(value="7"),
            "threshold": tk.StringVar(value="1.5"),
            "show": tk.StringVar(value="temp_c"),
            "zoom": tk.BooleanVar(value=True),
        }
        self._build()
        self._on_attack_change()

    # ------------------------------------------------------------------ layout

    def _build(self):
        left = tk.Frame(self.root, bg=BG, width=300)
        left.pack(side="left", fill="y", padx=(10, 4), pady=8)
        right = tk.Frame(self.root, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=8)
        self._controls(left)
        self._stage_strip(right)
        self._tabs(right)

    def _box(self, parent, title):
        box = tk.LabelFrame(parent, text=f" {title} ", bg=BG, font=UI_B, padx=8, pady=4)
        box.pack(fill="x", pady=(0, 6))
        box.columnconfigure(1, weight=1)
        return box

    def _row(self, box, r, label, widget):
        tk.Label(box, text=label, bg=BG, font=UI, anchor="w").grid(row=r, column=0, sticky="w", pady=1)
        widget.grid(row=r, column=1, sticky="ew", pady=1, padx=(6, 0))
        return widget

    def _combo(self, box, key, values, width=14):
        return ttk.Combobox(box, textvariable=self.v[key], values=values, state="readonly",
                            width=width, font=UI)

    def _entry(self, box, key, width=14):
        return tk.Entry(box, textvariable=self.v[key], width=width, font=MONO)

    def _controls(self, parent):
        b = self._box(parent, "1 · data")
        self._row(b, 0, "site", self._combo(b, "site", p.sites(self.cfg)))
        split = self.cfg["split"]
        tk.Label(b, bg=BG, fg=GREY, font=("Segoe UI", 8), justify="left", anchor="w",
                 text=f"fit on {split['train_start'][:4]}–{split['train_end'][:4]}, "
                      f"check on {split['validation_start'][:4]}").grid(row=1, column=0, columnspan=2,
                                                                          sticky="w")

        b = self._box(parent, "2 · attack")
        cb = self._row(b, 0, "attack", self._combo(b, "attack", list(p.ATTACKS)))
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_attack_change())
        self.w_attack = {
            "variable": self._row(b, 1, "variable", self._combo(b, "variable", p.VARIABLES)),
            "onset": self._row(b, 2, "onset (YYYY-MM-DD)", self._entry(b, "onset")),
            "magnitude": self._row(b, 3, "size (%)", self._entry(b, "magnitude")),
            "sign": self._row(b, 4, "direction", self._combo(b, "sign", ["up", "down"])),
            "relative_to": self._row(b, 5, "% of", self._combo(b, "relative_to", ["value", "range", "std"])),
            "length": self._row(b, 6, "attacked days", self._entry(b, "length")),
            "ramp": self._row(b, 7, "ramp days", self._entry(b, "ramp")),
            "hold": self._row(b, 8, "hold days", self._entry(b, "hold")),
            "back": self._row(b, 9, "copy from (days back)", self._combo(b, "back", ["7", "28", "364"])),
        }

        b = self._box(parent, "3 · where the attacker sits")
        for i, (key, text) in enumerate(p.POSITIONS.items()):
            tk.Radiobutton(b, text=f"{key}  {text}", variable=self.v["position"], value=key, bg=BG,
                           font=UI, anchor="w", justify="left", wraplength=260,
                           activebackground=BG).grid(row=i, column=0, columnspan=2, sticky="w")

        self.run_btn = tk.Button(parent, text="▶  Run the pipeline", command=self.run, bg=GREEN,
                                 fg="white", relief="flat", font=("Segoe UI", 10, "bold"), pady=6)
        self.run_btn.pack(fill="x", pady=(2, 4))
        self.save_btn = tk.Button(parent, text="💾  Save this run (attacked data, labels, …)",
                                  command=self.save, bg=GREY, fg="white", relief="flat", font=UI_B,
                                  pady=4, state="disabled")
        self.save_btn.pack(fill="x", pady=(0, 8))

        b = self._box(parent, "5 · screen (placeholder threshold)")
        self._row(b, 0, "residual", self._combo(b, "family", ["reference", "temporal"]))
        self._row(b, 1, "rolling window (days)", self._entry(b, "window"))
        self._row(b, 2, "threshold |mean z| >", self._entry(b, "threshold"))
        tk.Button(b, text="Apply", command=self.rescreen, bg=BLUE, fg="white", relief="flat",
                  font=UI_B).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 2))

        b = self._box(parent, "other views")
        tk.Button(b, text="Layer-1 live link (intercept records)", command=self._open_l1, relief="flat",
                  font=UI).grid(row=0, column=0, columnspan=2, sticky="ew", pady=1)
        tk.Button(b, text="Preparation figures and checks", command=self._open_prep, relief="flat",
                  font=UI).grid(row=1, column=0, columnspan=2, sticky="ew", pady=1)

    def _stage_strip(self, parent):
        strip = tk.Frame(parent, bg=BG)
        strip.pack(fill="x")
        self.stage_lbl = []
        for i, name in enumerate(STAGES):
            if i:
                tk.Label(strip, text="→", bg=BG, fg=GREY, font=("Segoe UI", 14)).pack(side="left")
            cell = tk.Frame(strip, bg=IDLE, padx=8, pady=4)
            cell.pack(side="left", fill="both", expand=True)
            tk.Label(cell, text=name, bg=IDLE, fg="#111827", font=UI_B, anchor="w").pack(fill="x")
            body = tk.Label(cell, text="—", bg=IDLE, fg=GREY, font=("Segoe UI", 8), anchor="w",
                            justify="left", wraplength=220, height=3)
            body.pack(fill="x")
            self.stage_lbl.append((cell, body))
        self.verdict = tk.Label(parent, bg="#e9ebef", fg=GREY, font=("Segoe UI", 11, "bold"), anchor="w",
                                justify="left", padx=10, pady=8, wraplength=1050,
                                text="Choose an attack and a position, then press Run.")
        self.verdict.pack(fill="x", pady=(6, 4))

        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x")
        tk.Label(bar, text="show variable", bg=BG, font=UI).pack(side="left")
        cb = ttk.Combobox(bar, textvariable=self.v["show"], values=p.VARIABLES, state="readonly",
                          width=14, font=UI)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._redraw())
        tk.Checkbutton(bar, text="validation year only", variable=self.v["zoom"], command=self._redraw,
                       bg=BG, font=UI, activebackground=BG).pack(side="left", padx=10)

    def _tabs(self, parent):
        self.nb = ttk.Notebook(parent)
        self.nb.pack(fill="both", expand=True, pady=(4, 0))
        self.fig_series, self.cv_series = self._figure_tab("Series")
        self._l1_tab()
        self.fig_res, self.cv_res = self._figure_tab("Residuals")
        self._screen_tab()
        self._report_tab()

    def _figure_tab(self, title):
        frame = tk.Frame(self.nb, bg="white")
        self.nb.add(frame, text=f"  {title}  ")
        fig = Figure(figsize=(10, 6), dpi=96)
        canvas = FigureCanvasTkAgg(fig, master=frame)
        bar = NavigationToolbar2Tk(canvas, frame, pack_toolbar=False)
        bar.pack(side="bottom", fill="x")
        canvas.get_tk_widget().pack(fill="both", expand=True)
        return fig, canvas

    def _tree(self, parent, cols, widths, height=18):
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=height)
        for c, w in zip(cols, widths):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="w")
        for tag, col in (("accept", GREEN), ("reject", RED), ("flag", ORANGE), ("info", GREY),
                         ("store", PURPLE), ("hit", RED)):
            tree.tag_configure(tag, foreground=col)
        return tree

    def _l1_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="  Layer 1  ")
        self.l1_summary = tk.Label(frame, bg=BG, font=MONO, anchor="w", justify="left", text="")
        self.l1_summary.pack(fill="x", padx=8, pady=6)
        tk.Label(frame, bg=BG, font=UI_B, anchor="w",
                 text="records that did not go through cleanly (all others: ACCEPT, ok)").pack(fill="x", padx=8)
        self.l1_tree = self._tree(frame, ("date", "seq", "what was sent", "decision", "reason", "gap"),
                                  (100, 60, 150, 90, 120, 60))
        self.l1_tree.pack(fill="both", expand=True, padx=8, pady=6)

    def _screen_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="  Screen table  ")
        tk.Label(frame, bg=BG, font=UI, anchor="w", justify="left",
                 text=("Validation year only. 'reached' = attacked days that layer 1 let through. "
                       "'flagged' = share of those days the screen flagged. "
                       "'false alarms' = share of clean days flagged.\n"
                       "This is a plain threshold to test the chain, not the team's detector.")
                 ).pack(fill="x", padx=8, pady=6)
        self.scr_tree = self._tree(frame, ("variable", "attacked", "reached", "flagged", "first flag after",
                                           "false alarms", "days with a score"),
                                   (120, 80, 80, 80, 120, 100, 120), height=8)
        self.scr_tree.pack(fill="x", padx=8)

    def _report_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="  Report  ")
        self.report = tk.Text(frame, font=MONO, wrap="word", bg="white", relief="flat")
        self.report.pack(fill="both", expand=True, padx=8, pady=8)

    # ------------------------------------------------------------------ controls logic

    def _on_attack_change(self):
        a = self.v["attack"].get()
        uses = {
            "variable": a in ("step", "drift"), "magnitude": a in ("step", "drift"),
            "sign": a in ("step", "drift"), "relative_to": a in ("step", "drift"),
            "onset": a != "none", "length": a in ("step", "replay"),
            "ramp": a == "drift", "hold": a == "drift", "back": a == "replay",
        }
        for key, widget in self.w_attack.items():
            on = uses[key]
            if isinstance(widget, ttk.Combobox):
                widget.config(state="readonly" if on else "disabled")
            else:
                widget.config(state="normal" if on else "disabled")
        defaults = {"step": ("12", "60"), "drift": ("15", None), "replay": (None, "7")}
        mag, length = defaults.get(a, (None, None))
        if mag:
            self.v["magnitude"].set(mag)
        if length:
            self.v["length"].set(length)

    def _spec(self) -> p.AttackSpec:
        v = self.v
        try:
            spec = p.AttackSpec(
                attack=v["attack"].get(), variables=(v["variable"].get(),),
                onset=v["onset"].get().strip(), magnitude=float(v["magnitude"].get()) / 100,
                sign=1 if v["sign"].get() == "up" else -1, relative_to=v["relative_to"].get(),
                length_days=int(v["length"].get()), ramp_days=int(v["ramp"].get()),
                hold_days=int(v["hold"].get()), source_offset_days=int(v["back"].get()),
                position=v["position"].get())
            pd.Timestamp(spec.onset)
        except ValueError as e:
            raise ValueError(f"check the attack settings: {e}") from e
        return spec

    def _screen_knobs(self) -> tuple[str, int, float]:
        try:
            return self.v["family"].get(), max(1, int(self.v["window"].get())), float(self.v["threshold"].get())
        except ValueError:
            raise ValueError("the screen window must be a whole number and the threshold a number")

    # ------------------------------------------------------------------ running

    def run(self):
        try:
            spec = self._spec()
            self._screen_knobs()
        except ValueError as e:
            return self._say(str(e), RED)
        site = self.v["site"].get()
        self.run_btn.config(state="disabled", text="running…")
        for i, (cell, body) in enumerate(self.stage_lbl):
            self._stage(i, "…", IDLE)
        self._say(f"Running {spec.attack} at {spec.position} on {site}…", GREY)

        def work():
            try:
                self.jobs.put(("ok", p.run(site, spec, self.cfg)))
            except Exception as e:  # shown in the window, not lost in a thread
                self.jobs.put(("error", e))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self._poll)

    def _poll(self):
        try:
            kind, value = self.jobs.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return
        self.run_btn.config(state="normal", text="▶  Run the pipeline")
        if kind == "error":
            return self._say(f"The run failed: {value}", RED)
        self.result = value
        self.save_btn.config(state="normal", bg=BLUE)
        if self.result.spec.attack in ("step", "drift"):
            self.v["show"].set(self.result.spec.variables[0])
        onset = self.result.attack.episodes[0].onset if self.result.attack.episodes else None
        if onset is not None and onset < pd.Timestamp(self.cfg["split"]["validation_start"]):
            self.v["zoom"].set(False)
        self.rescreen()

    def rescreen(self):
        if self.result is None:
            return self._say("Run the pipeline first.", GREY)
        try:
            family, window, threshold = self._screen_knobs()
        except ValueError as e:
            return self._say(str(e), RED)
        self.scr = p.screen(self.result, family, window, threshold)
        self._fill_stages()
        self._fill_l1()
        self._fill_screen()
        self._fill_report()
        self._redraw()

    def save(self):
        if self.result is None:
            return self._say("Run the pipeline first.", GREY)
        try:
            folder = p.save(self.result, screen_table=self.scr)
        except OSError as e:
            return self._say(f"Could not save: {e}", RED)
        self._say(f"Saved to {folder}  (attacked.csv, labels.csv, received.csv, residuals, layer-1 log)", BLUE)
        try:
            import os
            os.startfile(folder)  # open it in Explorer (Windows)
        except (AttributeError, OSError):
            pass

    # ------------------------------------------------------------------ stage strip and verdict

    def _stage(self, i, text, color):
        cell, body = self.stage_lbl[i]
        idle = color == IDLE
        cell.config(bg=color)
        for w in cell.winfo_children():
            w.config(bg=color, fg=("#111827" if w is not body else GREY) if idle else "white")
        body.config(text=text)

    def _fill_stages(self):
        r, scr = self.result, self.scr
        c = r.trust.counts
        n = len(r.station)
        miss = int(r.station[p.VARIABLES].isna().any(axis=1).sum())
        self._stage(0, f"{r.site} · {n} days\n{r.coords[0]}, {r.coords[1]}\n{miss} days with a gap", BLUE)

        if r.attack.episodes:
            ep = r.attack.episodes[0]
            what = (f"{ep.attack} {'+' if ep.sign >= 0 else '−'}{ep.magnitude:.0%} {', '.join(ep.variables)}"
                    if ep.attack != "replay" else f"replay, copied {ep.params['source_offset_days']} days back")
            self._stage(1, f"{what}\n{ep.onset.date()} → {ep.end.date()}\n"
                           f"{int(r.labels['attacked'].sum())} days · position {r.spec.position}", PURPLE)
        else:
            self._stage(1, "no attack\n(clean run: shows false alarms)", GREY)

        reasons = ", ".join(f"{k[7:]} {v}" for k, v in c.items() if k.startswith("reason:"))
        if not r.trust.ledger_ok:
            self._stage(2, f"{c['accepted']} accepted, 0 rejected\nLEDGER BROKEN at "
                           f"{r.trust.ledger_first_broken.date()}", RED)
        elif c["rejected"] or c["flagged"]:
            self._stage(2, f"{c['accepted']} accepted · {c['rejected']} REJECTED\n{reasons}\nledger intact", RED)
        else:
            self._stage(2, f"all {c['accepted']} records accepted\nledger intact", GREEN)

        cal = r.prep.calibration
        self._stage(3, f"fit {cal['fit_start']} → {cal['fit_end']}\nreference + temporal residuals\n"
                       f"{r.seconds['preparation']:.1f} s", BLUE)

        hit = scr[scr["attacked"]]
        if hit.empty:
            worst = scr["false_alarm_rate"].max()
            self._stage(4, f"no attack to find\nfalse alarms up to {worst:.0%}\n(worst variable)",
                        GREEN if worst < 0.05 else ORANGE)
        elif hit["attack_days_reached"].iloc[0] == 0:
            self._stage(4, "no attacked day reached\nthe analysis", GREY)
        else:
            best = hit.sort_values("flagged_in_attack", ascending=False).iloc[0]
            first = best["days_to_first_flag"]
            self._stage(4, f"{best.name}: {best['flagged_in_attack']:.0%} of attack flagged\n"
                           f"first after {'—' if pd.isna(first) else int(first)} days\n"
                           f"false alarms {best['false_alarm_rate']:.0%}",
                        GREEN if best["flagged_in_attack"] > 0 else RED)
        self._say(*self._verdict())

    def _verdict(self) -> tuple[str, str]:
        r, scr = self.result, self.scr
        c = r.trust.counts
        if not r.labels["attacked"].any():
            worst = scr["false_alarm_rate"].idxmax()
            return (f"No attack injected. This run measures false alarms on clean data: worst is "
                    f"{worst} at {scr.loc[worst, 'false_alarm_rate']:.1%} of clean days.", GREY)
        if c["rejected"]:
            reasons = ", ".join(f"{v} {k[7:]}" for k, v in c.items() if k.startswith("reason:") and k != "reason:gap")
            return (f"Layer 1 stopped it: {reasons} record(s) rejected, and the hash chain raised a GAP "
                    f"after them. No false value reached the analysis.", GREEN)
        if not r.trust.ledger_ok:
            return (f"The ledger caught it: stored records were rewritten after verification; the chain "
                    f"breaks at {r.trust.ledger_first_broken.date()}. Layer 1 had accepted them, because "
                    f"the change came later.", GREEN)
        hit = scr[scr["attacked"]].sort_values("flagged_in_attack", ascending=False)
        best = hit.iloc[0]
        if best["flagged_in_attack"] > 0:
            return (f"Layer 1 is blind here: the station signed the false values itself (P1). The residual "
                    f"screen flagged {best['flagged_in_attack']:.0%} of attacked days on {best.name}, first "
                    f"after {int(best['days_to_first_flag'])} days, with {best['false_alarm_rate']:.0%} false "
                    f"alarms on clean days.", ORANGE)
        return ("Nobody caught it: layer 1 accepted the signed false values (P1) and the screen flagged no "
                "attacked day. Try a longer window, a lower threshold, or the other residual.", RED)

    def _say(self, text, color):
        self.verdict.config(text=text, fg=color)

    # ------------------------------------------------------------------ tables and report

    def _fill_l1(self):
        r = self.result
        c = r.trust.counts
        ledger = ("intact" if r.trust.ledger_ok
                  else f"BROKEN — first rewritten entry: {r.trust.ledger_first_broken.date()}")
        self.l1_summary.config(text=(
            f"records sent {c['records']}   accepted {c['accepted']}   flagged {c['flagged']}   "
            f"rejected {c['rejected']}   gaps raised {c['gaps']}\n"
            f"stored in ledger {c['stored']}   ledger chain: {ledger}\n"
            f"each record: {p.rec.OVERHEAD} B overhead + {len(p.pack([0] * len(p.VARIABLES)))} B payload "
            f"(Ed25519 signature, sequence number, hash of the previous record)"))
        self.l1_tree.delete(*self.l1_tree.get_children())
        log = r.trust.log
        odd = log[(log["reason"] != "ok") | (log["sent"] != "genuine")]
        for day, row in odd.iterrows():
            tag = "store" if row["sent"] == "rewritten in store" else row["decision"]
            self.l1_tree.insert("", "end", tags=(tag,), values=(
                day.date(), row["seq"], row["sent"], row["decision"].upper(), row["reason"],
                "yes" if row["gap"] else ""))
        if odd.empty:
            self.l1_tree.insert("", "end", tags=("info",),
                                values=("", "", "every record genuine", "ACCEPT", "ok", ""))

    def _fill_screen(self):
        self.scr_tree.delete(*self.scr_tree.get_children())
        for var, row in self.scr.iterrows():
            def pct(x):
                return "—" if pd.isna(x) else f"{x:.0%}"
            first = row["days_to_first_flag"]
            self.scr_tree.insert("", "end", tags=("hit",) if row["attacked"] else (), values=(
                var, "yes" if row["attacked"] else "", row["attack_days_reached"],
                pct(row["flagged_in_attack"]), "—" if pd.isna(first) else f"{int(first)} days",
                pct(row["false_alarm_rate"]), row["valid_days"]))

    def _fill_report(self):
        r = self.result
        var = self.v["show"].get()
        family, window, threshold = self._screen_knobs()
        lines = [f"SITE {r.site}  ({r.coords[0]}, {r.coords[1]})", ""]
        lines.append("STAGE TIMES  " + "   ".join(f"{k} {v:.2f} s" for k, v in r.seconds.items()))
        lines.append("")
        lines.append("ATTACK")
        if r.attack.episodes:
            ep = r.attack.episodes[0]
            lines += [f"  {ep.attack} on {', '.join(ep.variables)}  {ep.onset.date()} -> {ep.end.date()}",
                      f"  magnitude {ep.magnitude:.0%}  sign {ep.sign:+d}  of {ep.relative_to or '-'}  "
                      f"params {ep.params}", f"  attacker position {r.spec.position}: {p.POSITIONS[r.spec.position]}"]
        else:
            lines.append("  none")
        lines += ["", "LAYER 1"] + [f"  {k:<18} {v}" for k, v in r.trust.counts.items()]
        lines.append(f"  ledger intact      {r.trust.ledger_ok}")
        lines += ["", f"CALIBRATION for {var} (station vs NASA POWER, fitted {r.prep.calibration['fit_start']} -> "
                      f"{r.prep.calibration['fit_end']})"]
        cal = r.prep.calibration["variables"][var]
        lines.append(f"  transform {cal['transform']}")
        for season, s in cal["seasons"].items():
            off = "—" if s["offset"] is None else f"{s['offset']:+.3f}"
            lines.append(f"  {season}  normal gap {off:>8}   spread {s['spread']:.3f}   fit days {s['fit_days']}")
        lines += ["", f"SCREEN  residual={family}  window={window} days  threshold={threshold}",
                  self.scr.to_string(float_format=lambda x: f"{x:.3f}")]
        if r.warnings:
            lines += ["", "WARNINGS"] + [f"  ! {w}" for w in r.warnings]
        lines += ["", "Not built yet, so not in this chain: QC tests, detectors S and M, fusion,",
                  "trust score, response policy, water-balance product, evaluation runner."]
        self.report.config(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", "\n".join(lines))
        self.report.config(state="disabled")

    # ------------------------------------------------------------------ plots

    def _view(self):
        return pd.Timestamp(self.cfg["split"]["validation_start"]) if self.v["zoom"].get() else None

    def _shade(self, ax):
        r = self.result
        for ep in r.attack.episodes:
            ax.axvspan(ep.onset, ep.end + pd.Timedelta(days=1), color=RED, alpha=0.12, lw=0)
            if ep.attack == "replay":
                back = pd.Timedelta(days=ep.params["source_offset_days"])
                lo = self._view()
                if lo is None or ep.onset - back >= lo:
                    ax.axvspan(ep.onset - back, ep.end - back + pd.Timedelta(days=1), color=PURPLE,
                               alpha=0.10, lw=0)

    def _redraw(self):
        if self.result is None:
            return
        self._draw_series()
        self._draw_residuals()

    def _draw_series(self):
        r, var, lo = self.result, self.v["show"].get(), self._view()
        fig = self.fig_series
        fig.clear()
        ax, strip = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [5, 1]})
        sl = slice(lo, None)
        ax.plot(r.power[var].loc[sl], color="#e08a1e", lw=0.9, alpha=0.9, label="NASA POWER (witness)")
        ax.plot(r.station[var].loc[sl], color="0.55", lw=1.0, label="station, true values")
        ax.plot(r.trust.received[var].loc[sl], color=BLUE, lw=1.1, label="what the pipeline received")
        self._shade(ax)
        ax.set_ylabel(self.cfg.get("variable_labels", {}).get(var, var))
        ax.set_title("red band = attack window" + ("   ·   purple band = days copied by the replay"
                                                   if r.spec.attack == "replay" else ""), fontsize=9, loc="left")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(alpha=0.25)

        log = r.trust.log.loc[sl]
        colors = [PURPLE if s == "rewritten in store" else DECISION_COLOR[d]
                  for d, s in zip(log["decision"], log["sent"])]
        strip.vlines(log.index, 0, 1, colors=colors, lw=1.2)
        strip.set_yticks([])
        strip.set_ylim(0, 1)
        strip.set_title("layer 1 per day:  green accept · orange flag · red reject · purple rewritten in store",
                        fontsize=8, loc="left")
        fig.tight_layout()
        self.cv_series.draw_idle()

    def _draw_residuals(self):
        r, var, lo = self.result, self.v["show"].get(), self._view()
        family, window, threshold = self._screen_knobs()
        fig = self.fig_res
        fig.clear()
        axes = fig.subplots(2, 1, sharex=True)
        sl = slice(lo, None)
        val_start = pd.Timestamp(self.cfg["split"]["validation_start"])
        for ax, name, frame in zip(axes, ("reference", "temporal"), (r.prep.reference, r.prep.temporal)):
            s = frame[var].loc[sl]
            ax.axhline(0, color="black", lw=0.6)
            if s.notna().any():
                ax.plot(s.clip(-6, 6), color="0.6", lw=0.7, label="daily residual (z)")
            else:
                ax.text(0.5, 0.5, f"no {name} residual for {var}", transform=ax.transAxes,
                        ha="center", color=GREY)
            if name == family:
                score = p.screen_score(frame[var], window).loc[sl]
                ax.plot(score.clip(-6, 6), color=BLUE, lw=1.5, label=f"{window}-day mean (screen)")
                for k in (threshold, -threshold):
                    ax.axhline(k, color=RED, lw=0.9, ls="--")
                flags = score[score.abs() > threshold]
                ax.plot(flags.index, [5.5] * len(flags), "v", color=RED, ms=3, label="flagged day")
            self._shade(ax)
            if lo is None:
                ax.axvline(val_start, color=GREY, lw=1, ls=":")
            ax.set_ylim(-6, 6)
            ax.set_ylabel("z")
            ax.set_title(f"{name} residual · {var}" + ("   (used by the screen)" if name == family else ""),
                         fontsize=9, loc="left")
            ax.grid(alpha=0.25)
            ax.legend(loc="lower left", fontsize=8, ncol=3)
        fig.tight_layout()
        self.cv_res.draw_idle()

    # ------------------------------------------------------------------ other views

    def _open_l1(self):
        subprocess.Popen([sys.executable, str(HERE / "l1_gui.py")], cwd=str(HERE))

    def _open_prep(self):
        try:
            from prep_view import PreparationView
            PreparationView(tk.Toplevel(self.root))
        except Exception as e:
            self._say(f"Could not open the preparation view: {e}", RED)

    def run_forever(self):
        self.root.mainloop()


def main():
    PipelineLab().run_forever()


if __name__ == "__main__":
    main()
