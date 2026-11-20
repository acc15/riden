#!/usr/bin/env python3
"""Minimal Tk UI for a Riden power supply.

Run with a serial path or a Bluetooth URL::

    uv run scripts/tk_ui.py bt://E1:F9:C6:24:71:C8
"""

import asyncio
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Any

import config

from riden import Field, Mode, Riden

FIELDS = (Field.V, Field.I, Field.P, Field.EN, Field.MODE)
INITIAL_FIELDS = (Field.V_SET, Field.I_SET)

GAP = 24

# DSEG7's "!" glyph is blank but exactly as wide as a digit, which keeps the
# decimal points aligned. Fall back to monospace with plain spaces otherwise.
DSEG = "DSEG7 Classic"

# Global UI scale. Tk's `tk scaling` has no effect on Xft fonts here, so the
# default fonts used by labels, buttons and entries are scaled explicitly,
# together with the DSEG digits.
SCALE = 2

# Output button colours.
EN_ON = "#1e7d1e"
EN_ON_ACTIVE = "#2a9c2a"
EN_OFF_ACTIVE = "#333333"

# Background tint of the I reading while the output is in CC.
MODE_CC = "#3d2b00"


class App:
    def __init__(self, root: tk.Tk, url: str) -> None:
        self.root = root
        self.url = url
        self.dseg = DSEG in tkfont.families(root)
        family = DSEG if self.dseg else "monospace"
        self.digits = tkfont.Font(family=family, size=round(20 * SCALE))
        self.requests: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self.loop = asyncio.new_event_loop()
        self.ready = False
        self.pending = False
        self.en: bool | None = None
        self.mode: Mode | None = None
        self.error: Exception | None = None
        self.closing = False
        self.invalid: set[tk.Entry] = set()

        self.v = tk.StringVar(value=self._number(0))
        self.i = tk.StringVar(value=self._number(0))
        self.p = tk.StringVar(value=self._number(0))

        root.configure(background="black")
        self.body = tk.Frame(root, padx=GAP, pady=GAP, background="black")
        self.body.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.v_set = self._entry()
        self.i_set = self._entry()
        self.en_button = tk.Button(
            self.body,
            text="?",
            command=self.toggle_en,
            state="disabled",
            background="black",
            foreground="white",
            activebackground=EN_OFF_ACTIVE,
            activeforeground="white",
        )

        self.value_labels: dict[str, tk.Label] = {}
        for row, (label, value) in enumerate((("V", self.v), ("I", self.i), ("P", self.p))):
            pady = (0, GAP) if row < 2 else 0
            tk.Label(
                self.body, text=label, anchor="w", background="black", foreground="white"
            ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=pady)
            value_label = tk.Label(
                self.body,
                textvariable=value,
                anchor="w",
                background="black",
                foreground="red",
                font=self.digits,
            )
            value_label.grid(row=row, column=1, sticky="w", pady=pady)
            self.value_labels[label] = value_label

        self.v_set.grid(row=0, column=2, sticky="we", padx=(GAP, 0), pady=(0, GAP))
        self.i_set.grid(row=1, column=2, sticky="we", padx=(GAP, 0), pady=(0, GAP))
        self.en_button.grid(row=2, column=2, sticky="we", padx=(GAP, 0))
        self.body.columnconfigure(2, weight=1)

        self.v_set.bind("<FocusIn>", self._clear_error)
        self.v_set.bind("<FocusOut>", lambda _: self._write_entry("v_set", self.v_set))
        self.v_set.bind("<Return>", lambda _: self._write_entry("v_set", self.v_set))
        self.i_set.bind("<FocusIn>", self._clear_error)
        self.i_set.bind("<FocusOut>", lambda _: self._write_entry("i_set", self.i_set))
        self.i_set.bind("<Return>", lambda _: self._write_entry("i_set", self.i_set))
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.thread = threading.Thread(target=self._run_worker, daemon=True)
        root.after(0, self.thread.start)
        root.after(500, self._poll)

    def _entry(self) -> tk.Entry:
        entry = tk.Entry(
            self.body,
            background="black",
            foreground="white",
            insertbackground="white",
            highlightthickness=0,
        )
        # X11: Tk pastes the PRIMARY selection on a bare Insert. Keep it off,
        # but leave Shift+Insert (the real clipboard paste) working.
        entry.bind("<Insert>", lambda e: None if int(e.state) & 0x1 else "break")
        return entry

    def _run_worker(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._worker())
        finally:
            self.loop.close()

    async def _worker(self) -> None:
        try:
            async with Riden.connect(self.url) as rd:
                self._emit("ready", None)
                while True:
                    op, payload = await self.requests.get()
                    if op == "stop":
                        return
                    if op == "read":
                        self._emit("values", await rd.read(*payload))
                    elif op == "write":
                        await rd.write(payload)
        except Exception as exc:  # noqa: BLE001 - re-raised in the main thread
            if not self.closing:
                self._emit("fatal", exc)

    def _emit(self, kind: str, payload: Any) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, self._handle, kind, payload)
        except (RuntimeError, tk.TclError) as exc:
            print(f"after failed: {exc}", file=sys.stderr)

    def _send(self, op: str, payload: Any) -> None:
        if not self.closing and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.requests.put_nowait, (op, payload))

    def _poll(self) -> None:
        if self.closing:
            return
        if self.ready and not self.pending:
            self.pending = True
            self._send("read", FIELDS)
        self.root.after(500, self._poll)

    def _handle(self, kind: str, payload: Any) -> None:
        if kind == "ready":
            self.ready = True
            self.root.deiconify()
            self.pending = True
            self._send("read", INITIAL_FIELDS)
        elif kind == "values" and isinstance(payload, dict):
            self._show(payload)
        elif kind == "fatal":
            self.error = payload
            self.root.destroy()

    def _show(self, values: dict[Any, Any]) -> None:
        self.pending = False
        for key, var in (("v", self.v), ("i", self.i), ("p", self.p)):
            if key in values:
                var.set(self._number(values[key]))
        if "en" in values:
            en = bool(values["en"])
            if en != self.en:
                self.en = en
                self._set_en()
        if "mode" in values:
            self.mode = Mode(values["mode"])
        if "mode" in values or "en" in values:
            self._paint_mode()
        if "v_set" in values:
            self._set_entry(self.v_set, float(values["v_set"]))
        if "i_set" in values:
            self._set_entry(self.i_set, float(values["i_set"]))

    def _number(self, value: Any) -> str:
        text = f"{float(value):9.4f}"
        return text.replace(" ", "!") if self.dseg else text

    def _set_en(self) -> None:
        on = bool(self.en)
        self.en_button.configure(
            text=f"{'ON' if on else 'OFF'}",
            background=EN_ON if on else "black",
            activebackground=EN_ON_ACTIVE if on else EN_OFF_ACTIVE,
            state="normal",
        )

    def _paint_mode(self) -> None:
        label = self.value_labels["I"]
        on_cc = self.en is True and self.mode is Mode.CC
        background = MODE_CC if on_cc else label.master.cget("background")
        if label.cget("background") != background:
            label.configure(background=background)

    def _set_entry(self, entry: tk.Entry, value: float) -> None:
        if entry in self.invalid or entry is self.root.focus_get():
            return
        entry.delete(0, tk.END)
        entry.insert(0, f"{value:.4f}")

    def _clear_error(self, event: tk.Event) -> None:
        self.invalid.discard(event.widget)
        event.widget["background"] = "black"

    def _write_entry(self, key: str, entry: tk.Entry) -> None:
        try:
            value = float(entry.get())
        except ValueError:
            self.invalid.add(entry)
            entry["background"] = "#7a1f1f"
            return
        self.invalid.discard(entry)
        entry["background"] = "black"
        self._send("write", {key: value})

    def toggle_en(self) -> None:
        if self.en is not None:
            self._send("write", {"en": not self.en})

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        if self.thread.is_alive() and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.requests.put_nowait, ("stop", None))
            except RuntimeError:
                pass
        self.root.destroy()


def wait_close(app: App) -> None:
    while app.thread.is_alive():
        try:
            app.thread.join()
        except KeyboardInterrupt:
            pass


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else config.DEFAULT_URL
    root = tk.Tk()
    for name in ("TkDefaultFont", "TkTextFont"):
        font = tkfont.nametofont(name)
        font.configure(size=round(float(font.cget("size")) * SCALE))
    root.title("Riden")
    root.withdraw()
    app = App(root, url)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.close()
    finally:
        wait_close(app)
    if app.error is not None:
        raise app.error


if __name__ == "__main__":
    main()
