"""Layer-1 live link monitor: watch records flow, intercept one, change it, forward it.

Run it:
    .venv\\Scripts\\python tools\\l1_gui.py
or:
    mingw32-make l1-gui

A station sends one signed record per "day" on a timer (you set the speed).
With "Intercept" off, every record flows straight to the verifier and is
ACCEPTED (green) -- you watch the stream go by. Turn "Intercept" on and the
next record is HELD on the link: its fields appear, you edit anything you like,
then Forward it (as-is, or after re-signing with the station or an impostor
key) or Drop it. This is the attacker sitting on the telemetry link (position
P2). Everything runs through the REAL trust module.

Tool for testing by hand (tools/), not part of the product.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk

from sensorguard.trust import record as rec
from sensorguard.trust import verify as vfy
from sensorguard.trust.enrolment import Registry, issue_certificate
from sensorguard.trust.keys import FileSecureElement, generate_root, verify_signature

from prep_view import PreparationView

DAY = 86_400
T0 = int(datetime(2023, 7, 1, tzinfo=timezone.utc).timestamp())
POS = (35.68, 10.10)
SENSOR_ID = 1

GREEN, RED, ORANGE, GREY, BG = "#1b7f4b", "#b4231f", "#b5720a", "#5b5b5b", "#f4f5f7"
MONO = ("Consolas", 9)


def to_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def to_ts(s: str) -> int:
    return int(datetime.strptime(s.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


class World:
    """Operator, station, impostor and verifier -- the real objects. The station
    advances its counter every time it PRODUCES a record, whether or not that
    record is ever delivered -- so a dropped or altered record leaves a gap."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.root = generate_root()
        self.registry = Registry(self.root.public_key())
        self.se = FileSecureElement.generate()
        self.impostor = FileSecureElement.generate()
        self.cert = issue_certificate(
            self.root, sensor_id=SENSOR_ID, public_key=self.se.public_key(),
            position=POS, valid_from=T0 - 365 * DAY, valid_to=T0 + 365 * DAY, key_id=0)
        self.registry.enrol(self.cert)
        self.verifier = vfy.Verifier(self.registry)
        self.seq = 0
        self.t = T0
        self.prev = rec.ZERO_HASH
        self.revoked = False

    def produce(self) -> rec.Record:
        """The station emits the next signed reading onto the link."""
        day = self.seq
        values = [28 + day % 5 + 0.4, 40 + day % 7, 22 + day % 3 + 0.6]
        r = rec.Record(sensor_id=SENSOR_ID, key_id=0, seq=self.seq, t_obs=self.t,
                       prev_hash=self.prev, payload=rec.encode_payload(values))
        r = rec.Record(**{**r.__dict__, "signature": self.se.sign(r.signed_region())})
        self.seq += 1
        self.t += DAY
        self.prev = r.digest()
        return r

    def sign_region(self, region: bytes, who: str) -> bytes:
        return (self.impostor if who == "impostor" else self.se).sign(region)


class App:
    def __init__(self, world: World):
        self.w = world
        self.n = 0
        self.running = False
        self.held = False
        self.after_id = None
        self.root = tk.Tk()
        self.root.title("SensorGuard — Layer 1 live link")
        self.root.configure(bg=BG)
        self.root.geometry("1000x680")
        self.vars = {}
        self.intercept = tk.BooleanVar(value=False)
        self.interval = tk.StringVar(value="1.5")
        self._build()
        self._refresh_status()
        self._set_mode("paused")

    # --- layout ------------------------------------------------------------

    def _build(self):
        tk.Label(self.root, bg=BG, justify="left", anchor="w", font=("Segoe UI", 10),
                 text=("A station sends one signed record per day. Press Start to watch them flow and "
                       "get ACCEPTED.\nTick 'Intercept' to hold the next record on the link — then edit "
                       "it and Forward, or Drop it.")
                 ).pack(fill="x", padx=12, pady=(10, 4))

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=4)
        left = tk.Frame(main, bg=BG)
        left.pack(side="left", fill="y")
        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        self._stream_box(left)
        self._cert_box(left)
        self._record_box(left)
        self._action_box(left)

        self.banner = tk.Label(right, bg="#e9ebef", fg=GREY, font=("Segoe UI", 12, "bold"),
                               anchor="w", pady=8, text="press Start")
        self.banner.pack(fill="x")
        cols = ("n", "event", "seq", "decision", "reason")
        widths = (34, 150, 44, 84, 320)
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=20)
        for c, wd in zip(cols, widths):
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=wd, anchor="w")
        for tag, col in (("accept", GREEN), ("reject", RED), ("flag", ORANGE), ("info", GREY)):
            self.tree.tag_configure(tag, foreground=col)
        self.tree.pack(fill="both", expand=True, pady=(8, 0))

        self.status = tk.Label(self.root, bg="#e9ebef", anchor="w", font=MONO)
        self.status.pack(fill="x", side="bottom")

    def _stream_box(self, parent):
        box = tk.LabelFrame(parent, text=" the link ", bg=BG, font=("Segoe UI", 9, "bold"),
                            padx=8, pady=6)
        box.pack(fill="x")
        row = tk.Frame(box, bg=BG); row.pack(fill="x")
        self.start_btn = tk.Button(row, text="▶ Start", command=self.start, bg=GREEN, fg="white",
                                   relief="flat", font=("Segoe UI", 9, "bold"), width=8)
        self.start_btn.pack(side="left", padx=2)
        self.pause_btn = tk.Button(row, text="⏸ Pause", command=self.pause, bg=GREY, fg="white",
                                   relief="flat", font=("Segoe UI", 9, "bold"), width=8)
        self.pause_btn.pack(side="left", padx=2)
        self.prep_btn = tk.Button(row, text="Preparation", command=self._open_preparation,
                                  relief="flat", font=("Segoe UI", 9, "bold"), width=14)
        self.prep_btn.pack(side="left", padx=2)
        tk.Label(row, text="  day every", bg=BG, font=MONO).pack(side="left")
        tk.Entry(row, textvariable=self.interval, width=4, font=MONO).pack(side="left")
        tk.Label(row, text="s", bg=BG, font=MONO).pack(side="left")
        tk.Checkbutton(box, text="Intercept the next record (hold it on the link)",
                       variable=self.intercept, bg=BG, font=("Segoe UI", 9),
                       activebackground=BG).pack(anchor="w", pady=(4, 0))
        self.mode = tk.Label(box, bg=BG, anchor="w", font=("Segoe UI", 9, "bold"), fg=GREY,
                             text="paused")
        self.mode.pack(fill="x")

    def _cert_box(self, parent):
        box = tk.LabelFrame(parent, text=" enrolled certificate (signed by the root) ",
                            bg=BG, font=("Segoe UI", 9, "bold"), padx=8, pady=6)
        box.pack(fill="x", pady=(8, 0))
        c = self.w.cert
        ok = verify_signature(self.w.root.public_key(), c.signature, c.body())
        txt = (f"sensor_id {c.sensor_id}   key_id {c.key_id}   pos {c.latitude},{c.longitude}\n"
               f"valid {to_date(c.valid_from)} -> {to_date(c.valid_to)}\n"
               f"pub {c.public_key.hex()[:20]}…   root sig verifies: {'YES' if ok else 'NO'}")
        self.cert_label = tk.Label(box, bg=BG, justify="left", anchor="w", font=MONO, text=txt)
        self.cert_label.pack(fill="x")

    def _record_box(self, parent):
        box = tk.LabelFrame(parent, text=" record on the link (editable while held) ",
                            bg=BG, font=("Segoe UI", 9, "bold"), padx=8, pady=6)
        box.pack(fill="x", pady=(8, 0))
        self.entries = {}

        def row(label, key, width=56):
            fr = tk.Frame(box, bg=BG); fr.pack(fill="x", pady=1)
            tk.Label(fr, text=label, width=10, anchor="w", bg=BG, font=MONO).pack(side="left")
            var = tk.StringVar()
            e = tk.Entry(fr, textvariable=var, width=width, font=MONO)
            e.pack(side="left", fill="x", expand=True)
            self.vars[key] = var
            self.entries[key] = e

        for lab, key, w in [("sensor_id", "sensor_id", 10), ("key_id", "key_id", 10),
                            ("seq", "seq", 10), ("t_obs", "t_obs", 14),
                            ("prev_hash", "prev_hash", 56), ("payload", "payload", 28),
                            ("signature", "signature", 56)]:
            row(lab, key, w)

    def _action_box(self, parent):
        box = tk.Frame(parent, bg=BG); box.pack(fill="x", pady=(8, 0))

        def btn(text, cmd, bg, r, c):
            b = tk.Button(box, text=text, command=cmd, bg=bg, fg="white", relief="flat",
                          font=("Segoe UI", 9, "bold"), pady=5, width=16)
            b.grid(row=r, column=c, padx=3, pady=3, sticky="ew")
            return b

        self.b_sign_s = btn("Re-sign (station)", lambda: self.sign("station"), "#2f6fdd", 0, 0)
        self.b_sign_i = btn("Re-sign (impostor)", lambda: self.sign("impostor"), RED, 0, 1)
        self.b_forward = btn("Forward →", self.forward, "#111827", 1, 0)
        self.b_drop = btn("Drop ✖", self.drop, ORANGE, 1, 1)
        btn("Revoke station", self.revoke, "#7a2fae", 2, 0)
        btn("Reset", self.reset, GREY, 2, 1)

    # --- stream control ----------------------------------------------------

    def _ms(self) -> int:
        try:
            return max(100, int(float(self.interval.get()) * 1000))
        except ValueError:
            return 1500

    def _set_mode(self, mode):
        held = mode == "held"
        state = "normal" if held else "disabled"
        for b in (self.b_sign_s, self.b_sign_i, self.b_forward, self.b_drop):
            b.config(state=state)
        for e in self.entries.values():
            e.config(state="normal" if held else "readonly")
        colors = {"flowing": GREEN, "held": ORANGE, "paused": GREY}
        texts = {"flowing": "● flowing — records auto-delivered",
                 "held": "■ HELD on the link — edit, then Forward or Drop",
                 "paused": "paused"}
        self.mode.config(text=texts[mode], fg=colors[mode])

    def start(self):
        if self.running:
            return
        self.running = True
        self._set_mode("held" if self.held else "flowing")
        self._schedule()

    def pause(self):
        self.running = False
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        if not self.held:
            self._set_mode("paused")

    def _schedule(self):
        if self.running and not self.held:
            self.after_id = self.root.after(self._ms(), self._tick)

    def _tick(self):
        r = self.w.produce()                       # the station emits onto the link
        self._load(r)
        if self.intercept.get():
            self.held = True
            self._set_mode("held")
            self._banner(f"intercepted record seq {r.seq} — edit it, then Forward or Drop", ORANGE)
        else:
            self._deliver(r.signed_region(), bytes.fromhex(self.vars["signature"].get()), r.seq)
            self._schedule()

    # --- delivering / verifying -------------------------------------------

    def _deliver(self, region: bytes, sig: bytes, seq):
        v = self.w.verifier.verify(region + sig, arrival_time=self._arrival())
        self._log("received", seq, v)
        self._verdict_banner(v)
        self._refresh_status()

    def _arrival(self) -> int:
        # arrival ~ the record's own day; keeps timing honest without a real clock
        return self.w.t - DAY

    def forward(self):
        if not self.held:
            return
        try:
            region = self._region_from_fields()
        except ValueError as e:
            self._log("forward", self.vars["seq"].get(), None, info=f"malformed: {e}", tag="reject")
            return self._banner(f"REJECT — malformed: {e}", RED)
        try:
            sig = bytes.fromhex(self.vars["signature"].get().strip())
        except ValueError:
            sig = b""
        v = self.w.verifier.verify(region + sig, arrival_time=self._arrival())
        self._log("forwarded", self.vars["seq"].get(), v)
        self._verdict_banner(v)
        self._release()

    def drop(self):
        if not self.held:
            return
        self._log("dropped", self.vars["seq"].get(), None,
                  info="attacker dropped it — the station moved on, so a GAP will show next", tag="flag")
        self._banner("record dropped on the link — watch the next one raise a GAP", ORANGE)
        self._release()

    def _release(self):
        self.held = False
        self._refresh_status()
        if self.running:
            self._set_mode("flowing")
            self._schedule()
        else:
            self._set_mode("paused")

    def sign(self, who):
        if not self.held:
            return
        try:
            region = self._region_from_fields()
        except ValueError as e:
            return self._banner(f"cannot sign: {e}", ORANGE)
        self.vars["signature"].set(self.w.sign_region(region, who).hex())
        who_txt = "the station's key" if who == "station" else "the IMPOSTOR's key"
        self._banner(f"re-signed with {who_txt} — signature now covers the current fields", GREY)

    def revoke(self):
        self.w.registry.revoke(SENSOR_ID)
        self.w.revoked = True
        self._log("revoke", "", None, info="operator revoked station — records now REJECT", tag="flag")
        self._banner("station REVOKED — even correctly signed records now REJECT", ORANGE)
        self._refresh_status()

    def reset(self):
        self.pause()
        self.w.reset()
        self.held = False
        self.n = 0
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.intercept.set(False)
        self._set_mode("paused")
        self._load(None)
        self._refresh_status()
        self._banner("reset — fresh keys and chain", GREY)

    # --- fields ------------------------------------------------------------

    def _load(self, r):
        if r is None:
            for k in self.vars:
                self.vars[k].set("")
            return
        vals, _ = rec.decode_payload(r.payload)
        self.vars["sensor_id"].set(str(r.sensor_id))
        self.vars["key_id"].set(str(r.key_id))
        self.vars["seq"].set(str(r.seq))
        self.vars["t_obs"].set(to_date(r.t_obs))
        self.vars["prev_hash"].set(r.prev_hash.hex())
        self.vars["payload"].set(", ".join(f"{v:g}" for v in vals))
        self.vars["signature"].set(r.signature.hex())

    def _region_from_fields(self) -> bytes:
        try:
            sid = int(self.vars["sensor_id"].get()); kid = int(self.vars["key_id"].get())
            seq = int(self.vars["seq"].get()); t = to_ts(self.vars["t_obs"].get())
        except Exception as e:
            raise ValueError(f"bad number/date ({e})")
        try:
            prev = bytes.fromhex(self.vars["prev_hash"].get().strip())
        except ValueError:
            raise ValueError("prev_hash is not valid hex")
        try:
            vals = [float(x) for x in self.vars["payload"].get().split(",") if x.strip()]
        except ValueError:
            raise ValueError("payload must be comma-separated numbers")
        r = rec.Record(sensor_id=sid, key_id=kid, seq=seq, t_obs=t,
                       prev_hash=prev, payload=rec.encode_payload(vals))
        return r.signed_region()

    # --- output ------------------------------------------------------------

    def _banner(self, text, color):
        self.banner.config(text=text, fg=color)

    def _verdict_banner(self, v):
        color = {vfy.ACCEPT: GREEN, vfy.REJECT: RED, vfy.FLAG: ORANGE}[v.decision]
        extra = "  (+ GAP: a record is missing)" if v.gap else ""
        self._banner(f"{v.decision.upper()} — {v.reason}{extra}", color)

    def _log(self, event, seq, verdict, info=None, tag="info"):
        self.n += 1
        if verdict is not None:
            tag = {"accept": "accept", "reject": "reject", "flag": "flag"}[verdict.decision]
            decision = verdict.decision.upper()
            reason = verdict.reason + ("  + GAP" if verdict.gap else "")
        else:
            decision, reason = "", (info or "")
        self.tree.insert("", "end", tags=(tag,), values=(self.n, event, seq, decision, reason))
        self.tree.see(self.tree.get_children()[-1])

    def _refresh_status(self):
        st = self.w.verifier.state.get(SENSOR_ID)
        last_seq = st.last_seq if st else -1
        head = st.last_hash.hex()[:12] if st else "-"
        flag = "  REVOKED" if self.w.revoked else ""
        self.status.config(
            text=f"  last accepted seq: {last_seq}   chain head: {head}…   "
                 f"station next: seq {self.w.seq} / {to_date(self.w.t)}{flag}")

    def _open_preparation(self) -> None:
        """Open the read-only Preparation view in a new window."""
        top = tk.Toplevel(self.root)
        PreparationView(top)

    def run(self):
        self.root.mainloop()


def main():
    App(World()).run()


if __name__ == "__main__":
    main()
