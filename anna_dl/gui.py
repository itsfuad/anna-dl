"""anna-dl desktop GUI — download a single book, or a whole list from feeder.txt."""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from anna_dl import config
from anna_dl.download import download_book
from anna_dl.feeder import ensure_feeder_file, run_feeder
from anna_dl.search import get_working_mirror
from anna_dl.utils import load_json

APP_DIR = Path.cwd()
DEFAULT_OUTPUT_DIR = APP_DIR / "downloads"
DEFAULT_FEEDER_FILE = APP_DIR / "feeder.txt"
LOG_FILE = APP_DIR / "download_log.json"
LEDGER_NAME = "feeder_ledger.json"


class QueueWriter:
    """File-like object that forwards print() output from the worker thread to the GUI log."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str) -> None:
        if text:
            self.q.put(text)

    def flush(self) -> None:
        pass


def open_path(path: Path) -> None:
    """Opens a folder in the file manager, or a text file in a text editor."""
    if sys.platform == "win32":
        if path.is_dir():
            os.startfile(path)
        else:
            subprocess.Popen(["notepad.exe", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("anna-dl")
        self.minsize(660, 540)

        self.log_queue: queue.Queue = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()

        self.title_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.query_var = tk.StringVar()
        self.feeder_var = tk.StringVar(value=str(DEFAULT_FEEDER_FILE))
        self.format_var = tk.StringVar(value="pdf")
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.status_var = tk.StringVar(value="Ready")

        self._build()
        self.after(100, self._drain_log)

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        tabs = ttk.Notebook(self)
        tabs.pack(fill="x", padx=12, pady=(12, 0))
        tabs.add(self._build_single_tab(tabs), text="Single book")
        tabs.add(self._build_feeder_tab(tabs), text="Feeder list")

        settings = ttk.Frame(self, padding=(12, 8, 12, 0))
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="Format").grid(row=0, column=0, sticky="w", pady=3)
        formats = ttk.Frame(settings)
        formats.grid(row=0, column=1, columnspan=3, sticky="w", pady=3)
        ttk.Radiobutton(formats, text="PDF", value="pdf", variable=self.format_var).pack(side="left")
        ttk.Radiobutton(formats, text="EPUB", value="epub", variable=self.format_var).pack(side="left", padx=(12, 0))
        ttk.Label(formats, text="(feeder lines can override this with format=...)", foreground="gray").pack(
            side="left", padx=(12, 0))

        ttk.Label(settings, text="Save to").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(settings, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Button(settings, text="Browse…", command=self.choose_output).grid(row=1, column=2, padx=(6, 0), pady=3)
        ttk.Button(settings, text="Open folder", command=self.open_output).grid(row=1, column=3, padx=(6, 0), pady=3)

        status = ttk.Frame(self, padding=(12, 8, 12, 0))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        ttk.Button(status, text="Clear log", command=self.clear_log).pack(side="right")

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=(6, 0))

        self.log = ScrolledText(self, height=14, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=12)

    def _build_single_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        tab.columnconfigure(1, weight=1)

        entries = []
        for row, (label, var) in enumerate((
            ("Title *", self.title_var),
            ("Author", self.author_var),
            ("Custom query", self.query_var),
        )):
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(tab, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            entry.bind("<Return>", lambda _e: self.start_single())
            entries.append(entry)
        entries[0].focus_set()

        self.download_btn = ttk.Button(tab, text="Download", command=self.start_single)
        self.download_btn.grid(row=3, column=1, sticky="w", pady=(6, 0))
        return tab

    def _build_feeder_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Feeder file").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(tab, textvariable=self.feeder_var).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(tab, text="Browse…", command=self.choose_feeder).grid(row=0, column=2, padx=(6, 0), pady=3)

        ttk.Label(
            tab,
            text="One book per line:  Title | Author | format=epub | isbn=… | query=… | folder=…\n"
                 "Unavailable books are skipped, logged in the ledger, and retried at the very end. "
                 "Click “Edit list” for all options and examples.",
            foreground="gray", justify="left", wraplength=560,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 6))

        buttons = ttk.Frame(tab)
        buttons.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="Edit list", command=self.edit_feeder).pack(side="left")
        self.feeder_btn = ttk.Button(buttons, text="Run feeder", command=self.start_feeder)
        self.feeder_btn.pack(side="left", padx=(6, 0))
        self.stop_btn = ttk.Button(buttons, text="Stop after current book", command=self.stop)
        self.stop_btn.pack(side="left", padx=(6, 0))
        self.stop_btn.state(["disabled"])
        ttk.Button(buttons, text="Open ledger", command=self.open_ledger).pack(side="left", padx=(6, 0))
        return tab

    # --------------------------------------------------------------- helpers

    def _output_dir(self) -> Path:
        return Path(self.output_var.get().strip() or DEFAULT_OUTPUT_DIR)

    def _feeder_file(self) -> Path:
        return Path(self.feeder_var.get().strip() or DEFAULT_FEEDER_FILE)

    def _ledger_file(self) -> Path:
        # The ledger lives next to the feeder file it tracks
        return self._feeder_file().with_name(LEDGER_NAME)

    def choose_output(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_var.get() or str(APP_DIR))
        if folder:
            self.output_var.set(folder)

    def choose_feeder(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=str(self._feeder_file().parent),
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.feeder_var.set(path)

    def open_output(self) -> None:
        path = self._output_dir()
        path.mkdir(parents=True, exist_ok=True)
        open_path(path)

    def edit_feeder(self) -> None:
        path = self._feeder_file()
        if ensure_feeder_file(path):
            self.status_var.set("Created feeder.txt: add your books, save, then click Run feeder")
        open_path(path)

    def open_ledger(self) -> None:
        path = self._ledger_file()
        if path.exists():
            open_path(path)
        else:
            self.status_var.set("No ledger yet: it is created the first time the feeder runs")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def stop(self) -> None:
        self.stop_event.set()
        self.stop_btn.state(["disabled"])
        self.status_var.set("Stopping after the current book…")

    # ------------------------------------------------------------------ jobs

    def start_single(self) -> None:
        title = self.title_var.get().strip()
        if not title:
            self.status_var.set("Enter a title first")
            return

        book = {
            "title": title,
            "author": self.author_var.get().strip(),
            "search_query": self.query_var.get().strip(),
            "prefer_format": self.format_var.get(),
        }
        output_dir = self._output_dir()

        def job() -> str:
            output_dir.mkdir(parents=True, exist_ok=True)
            print("Finding a responsive Anna's Archive mirror…")
            mirror = get_working_mirror(config.ANNA_MIRRORS, config.HEADERS)
            print(f"Using mirror: {mirror}")
            log_data = load_json(LOG_FILE, default={})
            path = download_book(book, mirror, output_dir, log_data, LOG_FILE)
            return "Done ✔" if path else "Not found: try a custom query or the other format"

        self._start_job(job, "Searching… (this can take a minute)")

    def start_feeder(self) -> None:
        feeder_file = self._feeder_file()
        if ensure_feeder_file(feeder_file):
            self.status_var.set("Created feeder.txt: add your books, save, then click Run feeder")
            open_path(feeder_file)
            return

        output_dir, ledger_file, fmt = self._output_dir(), self._ledger_file(), self.format_var.get()

        def job() -> str:
            stats = run_feeder(feeder_file, output_dir, ledger_file, fmt, self.stop_event)
            if not stats["listed"]:
                return "The feeder list is empty: click Edit list to add books"
            summary = f"{stats['downloaded']} downloaded, {stats['not_available']} not available"
            return f"Stopped: {summary}" if stats["stopped"] else f"Feeder finished: {summary}"

        self._start_job(job, "Running feeder…", stoppable=True)

    def _start_job(self, job, busy_text: str, stoppable: bool = False) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.download_btn.state(["disabled"])
        self.feeder_btn.state(["disabled"])
        if stoppable:
            self.stop_btn.state(["!disabled"])
        self.status_var.set(busy_text)
        self.progress.start(12)
        self.worker = threading.Thread(target=self._run, args=(job,), daemon=True)
        self.worker.start()

    def _run(self, job) -> None:
        # Only one job runs at a time, so swapping the global stdout is safe
        old_stdout = sys.stdout
        sys.stdout = QueueWriter(self.log_queue)
        message = "Failed: see the log"
        try:
            message = job()
        except Exception as e:
            print(f"\n[!] Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.log_queue.put(("done", message))

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain_log(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple):
                    self.progress.stop()
                    self.download_btn.state(["!disabled"])
                    self.feeder_btn.state(["!disabled"])
                    self.stop_btn.state(["disabled"])
                    self.status_var.set(item[1])
                    self._append("\n")
                else:
                    self._append(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_log)
