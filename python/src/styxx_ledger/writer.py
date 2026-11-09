"""writer.py: the Ledger class, protocol v1 section 3b.

an append, under one lock:

    1. take <log>.lock beside the log, create-exclusive, holding this process's pid. a lock older than
       stale_after_s (30 s) whose pid is not a live process is broken, once, under a breaker file; the
       append then writes a lock_recovered entry before its own only if header.kinds lists lock_recovered.
    2. re-read the whole file and re-derive it (verify_bytes). a file that does not re-derive, or whose last
       byte is not LF (a torn write), is refused: LedgerBroken, nothing appended. a file whose header is not one a
       v1 writer may write (check_header) is refused too: LedgerValueError(header_form), nothing appended.
    3. take seq and prev from the tail.
    4. compose the entry with chain.build_entry, write its canonical line and one LF, flush, fsync, and check
       the file grew by exactly those bytes.
    5. release the lock.

the writer records what it is handed. it does not read content and makes no judgement of what a field says;
its refusals are the protocol's (LedgerValueError with a .code) plus the state errors below.
nothing is signed, and nothing here touches the network.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ._version import __version__
from .chain import REQUIRED_KINDS, anchor_text, build_entry, check_header, make_header
from .day import day_of, late_of, now_utc
from .jcs import dump
from .verify import verify_bytes

LOCK_STALE_S = 30.0
LOCK_TIMEOUT_S = 10.0
DEFAULT_WRITER = {"name": "styxx-ledger", "version": __version__, "language": "python"}


class LedgerError(Exception):
    """a writer-side refusal that is not a value refusal (those are LedgerValueError)."""


class LedgerLocked(LedgerError):
    """the lock file was held, by a live writer or a fresh one, for longer than lock_timeout_s."""


class LedgerBroken(LedgerError):
    """the existing file does not re-derive; nothing was appended. .problems holds the verifier's records."""

    def __init__(self, problems: List[dict]):
        self.problems = problems
        first = problems[0] if problems else {}
        codes = first.get("codes") or [first.get("code")]
        super().__init__("the log does not re-derive (%d problem record(s); first: seq %s %s); nothing appended"
                         % (len(problems), first.get("seq"), ",".join(str(c) for c in codes)))


class LedgerStateError(LedgerError):
    """the request does not fit the log's state: no log yet, a log already there, nothing to anchor, a day
    not yet closed, a day already anchored."""


def pid_alive(pid: int) -> bool:
    """whether a process with this pid runs now. windows: open it for a query and read its exit code (os.kill
    there would terminate it, so it is never called); elsewhere signal 0. a pid this user may not open reads
    alive; a reused pid reads alive. both err toward waiting."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5           # ERROR_ACCESS_DENIED: it exists
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == 259                       # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _fsync_dir(d: Path) -> None:
    """make a newly created file's directory entry durable (posix); windows has no directory fsync."""
    if os.name == "nt":
        return
    try:
        fd = os.open(str(d), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _previous_day(day: str) -> str:
    return (_dt.date.fromisoformat(day) - _dt.timedelta(days=1)).isoformat()


Builder = Callable[[dict, List[dict], int, str, str], Tuple[str, Dict[str, Any]]]


class Ledger:
    """the one writer for a v1 log at `path`.

        Ledger.create(path, agent=, anchor_tz=, certifies=, kinds=)   header line only
        led.start()                                                    a started entry (writer name/version)
        led.append(kind, fields)                                       one entry
        led.compose_anchor(date)                                       the anchor text, nothing written
        led.append_anchor(date)                                        the anchor entry; returns {text, entry}
        led.verify(withheld) / led.head()                              read-only

    `timestamp=` on the writing calls is for reproducible logs (tests, vectors); without it the box's utc clock
    is used, which is the writer's statement, not evidence of order."""

    def __init__(self, path, lock_timeout_s: float = LOCK_TIMEOUT_S, stale_after_s: float = LOCK_STALE_S):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.lock_timeout_s = float(lock_timeout_s)
        self.stale_after_s = float(stale_after_s)

    # ------------------------------------------------------------------------------------------- create
    @classmethod
    def create(cls, path, agent: str, anchor_tz: str, certifies: str, kinds: List[str],
               created: Optional[str] = None, **kw) -> "Ledger":
        """write the header (line 1) of a new log. `kinds` gains anchor and started when absent. refuses when
        a non-empty file is already there."""
        led = cls(path, **kw)
        header = make_header(created or now_utc(), anchor_tz, agent, certifies,
                             sorted(set(list(kinds) + list(REQUIRED_KINDS))))
        led.path.parent.mkdir(parents=True, exist_ok=True)
        led._acquire()  # a lock broken here is not recorded: a log with no header has no line for it
        try:
            existed = led.path.exists()
            if existed and led.path.stat().st_size > 0:
                raise LedgerStateError("a log is already at %s; create writes only a new one" % led.path)
            data = (dump(header) + "\n").encode("utf-8")
            led._write(data, 0)
            if not existed:
                _fsync_dir(led.path.parent)
        finally:
            led._release()
        return led

    # --------------------------------------------------------------------------------------------- lock
    def _acquire(self) -> Optional[dict]:
        deadline = time.monotonic() + self.lock_timeout_s
        recovered = None
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode("ascii"))
                finally:
                    os.close(fd)
                return recovered
            except PermissionError:
                # windows: a lock file another writer is deleting while a third holds it open sits in
                # "delete pending" and refuses creation with access denied; that is contention, not a fault
                if os.name != "nt":
                    raise
                if time.monotonic() >= deadline:
                    raise LedgerLocked("%s busy for over %.1f s" % (self.lock_path.name, self.lock_timeout_s)) from None
                time.sleep(0.02)
            except FileExistsError:
                stale = self._stale_lock()
                if stale is not None and recovered is None:
                    got = self._break_lock(stale)
                    if got is not None:
                        recovered = got
                        continue
                if time.monotonic() >= deadline:
                    raise LedgerLocked("%s held for over %.1f s by a writer that is alive or fresh"
                                       % (self.lock_path.name, self.lock_timeout_s)) from None
                time.sleep(0.02)

    def _stale_lock(self) -> Optional[dict]:
        """a lock is stale when it is older than stale_after_s AND its pid is not a live process (a body with
        no pid, a writer that died between create and write, counts as no live process)."""
        try:
            st = os.stat(self.lock_path)
        except OSError:
            return None
        age = max(0.0, time.time() - st.st_mtime)
        if age <= self.stale_after_s:
            return None  # decided on the stat alone: opening a fresh lock would block its owner's unlink on windows
        try:
            body = self.lock_path.read_bytes()[:64]
        except OSError:
            return None
        text = body.decode("ascii", "replace").strip()
        pid = int(text) if text.isdigit() else None
        if pid is not None and (pid == os.getpid() or pid_alive(pid)):
            return None
        return {"stale_pid": pid, "stale_age_s": int(age), "body": body}

    def _break_lock(self, stale: dict) -> Optional[dict]:
        """remove the stale lock only if it still holds the bytes judged stale, under a breaker file
        (create-exclusive) so two writers never both break it; a breaker older than stale_after_s is a dead
        breaker's and is removed."""
        breaker = self.lock_path.with_name(self.lock_path.name + ".break")
        try:
            os.close(os.open(str(breaker), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            try:
                if time.time() - os.stat(breaker).st_mtime > self.stale_after_s:
                    os.unlink(breaker)
            except OSError:
                pass
            return None
        try:
            try:
                if self.lock_path.read_bytes()[:64] != stale["body"]:
                    return None
                os.unlink(self.lock_path)
            except OSError:
                return None
            return {k: v for k, v in stale.items() if k != "body"}
        finally:
            try:
                os.unlink(breaker)
            except OSError:
                pass

    def _release(self) -> None:
        """remove the lock. on windows an unlink fails with a sharing violation while another process has the
        file open for a moment (a reader judging staleness); retry for up to 5 s, then say so."""
        deadline = time.monotonic() + 5.0
        while True:
            try:
                os.unlink(self.lock_path)
                return
            except FileNotFoundError:
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise LedgerError("could not remove %s (held open by another process); it will read stale "
                                      "%.0f s after this process exits" % (self.lock_path, self.stale_after_s)) from None
                time.sleep(0.01)

    # -------------------------------------------------------------------------------------------- write
    def _write(self, data: bytes, size_before: int) -> None:
        with open(self.path, "ab") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            end = f.tell()
        if end != size_before + len(data):
            raise LedgerError("write did not land: %s is %d bytes, expected %d" % (self.path, end, size_before + len(data)))

    def _read_rederived(self) -> Tuple[bytes, dict]:
        if not self.path.exists():
            raise LedgerStateError("no log at %s; create it first (styxx-ledger init)" % self.path)
        raw = self.path.read_bytes()
        if not raw:
            raise LedgerStateError("%s is empty: no header; create it first" % self.path)
        if not raw.endswith(b"\n"):
            raise LedgerBroken([{"line": None, "seq": None, "code": "tail_no_lf",
                                 "problem": "the last byte is not LF: a torn write, or an edit; nothing appended"}])
        r = verify_bytes(raw)
        if not r["ok"]:
            raise LedgerBroken(r["problems"])
        check_header(r["header"])  # the verifier does not report header form beyond kinds; the writer refuses it
        return raw, r

    def _append_with(self, build: Builder, timestamp: Optional[str]) -> dict:
        """the append of section 3b. `build(header, entries, seq, prev, ts)` returns (kind, fields), computed
        under the lock from the re-derived file."""
        recovered = self._acquire()
        try:
            raw, r = self._read_rederived()
            header, entries = r["header"], r["entries"]
            seq = entries[-1]["entry"]["seq"] + 1 if entries else 1
            prev = r["head"]
            ts = timestamp or now_utc()
            lines: List[str] = []
            if recovered is not None and "lock_recovered" in header["kinds"]:
                lr = build_entry(header, seq, prev, "lock_recovered", ts, recovered)
                lines.append(dump(lr))
                entries = entries + [{"line": None, "entry": lr}]
                seq, prev = seq + 1, lr["entry_id"]
            kind, fields = build(header, entries, seq, prev, ts)
            self._refuse_anchored_day(header, entries, kind, ts)
            entry = build_entry(header, seq, prev, kind, ts, fields)
            lines.append(dump(entry))
            self._write(("\n".join(lines) + "\n").encode("utf-8"), len(raw))
            return entry
        finally:
            self._release()

    @staticmethod
    def _refuse_anchored_day(header: dict, entries: List[dict], kind: str, ts: str) -> None:
        """an entry whose day is a day already anchored would sit after that day's posted head and break it
        (section 5); with a backdated timestamp or a clock that stepped back, the writer refuses it."""
        anchored = [it["entry"].get("anchor_date") for it in entries if it["entry"].get("kind") == "anchor"]
        anchored = [d for d in anchored if isinstance(d, str)]
        if not anchored:
            return
        try:
            day = day_of(ts, header["anchor_tz"])
        except Exception:  # noqa: BLE001 - build_entry reports the coded refusal
            return
        if day <= max(anchored):
            raise LedgerStateError("an entry of day %s would follow the anchor of %s; the writer refuses it"
                                   % (day, max(anchored)))

    def append(self, kind: str, fields: Optional[Dict[str, Any]] = None, timestamp: Optional[str] = None) -> dict:
        """append one entry of `kind` (in header.kinds) carrying `fields`; returns the entry written."""
        f = {} if fields is None else fields
        return self._append_with(lambda h, es, s, p, ts: (kind, f), timestamp)

    def start(self, writer: Optional[Dict[str, Any]] = None, fields: Optional[Dict[str, Any]] = None,
              timestamp: Optional[str] = None) -> dict:
        """the started entry a writer process writes when it opens the log: {"writer": {name, version, ...}}
        plus any further fields (framework, lockfile integrity: the writer's own statement)."""
        f = dict(fields or {})
        f["writer"] = dict(writer) if writer is not None else dict(DEFAULT_WRITER)
        return self.append("started", f, timestamp)

    # ------------------------------------------------------------------------------------------- anchor
    @staticmethod
    def _anchor_of(header: dict, entries: List[dict], date: str) -> Dict[str, Any]:
        day_entries = [it["entry"] for it in entries if it["entry"].get("day") == date]
        if not day_entries:
            raise LedgerStateError("no entry has day %s; there is nothing to anchor" % date)
        last = day_entries[-1]
        text = anchor_text(header["agent"], date, last["entry_id"], last["seq"])
        return {"agent": header["agent"], "date": date, "head": last["entry_id"], "seq": last["seq"], "text": text}

    def compose_anchor(self, date: Optional[str] = None, now: Optional[str] = None) -> Dict[str, Any]:
        """{agent, date, head, seq, text} for `date` (default: the day before `now` in anchor_tz). read-only:
        the caller posts the text; append_anchor records it."""
        _raw, r = self._read_rederived()
        header = r["header"]
        date = date or _previous_day(day_of(now or now_utc(), header["anchor_tz"]))
        return self._anchor_of(header, r["entries"], date)

    def append_anchor(self, date: Optional[str] = None, timestamp: Optional[str] = None) -> Dict[str, Any]:
        """compose the anchor text for `date` (default: the day before the entry's own day) and write the anchor
        entry (anchor_date, anchor_head, anchor_head_seq, anchor_text_sha256, late). `late` is section 5's rule
        (late_of: written after 00:10:00 local on the following day, or on a later day), never the caller's.
        refuses a day not yet closed in anchor_tz and a day already anchored. returns {"text", "entry"}."""
        out: Dict[str, Any] = {}

        def build(header, entries, seq, prev, ts):
            today = day_of(ts, header["anchor_tz"])
            d = date or _previous_day(today)
            if d >= today:
                raise LedgerStateError("%s is not closed in %s (the anchor entry's own day is %s)"
                                       % (d, header["anchor_tz"], today))
            if any(it["entry"].get("kind") == "anchor" and it["entry"].get("anchor_date") == d for it in entries):
                raise LedgerStateError("%s is already anchored" % d)
            a = self._anchor_of(header, entries, d)
            out["text"] = a["text"]
            return "anchor", {"anchor_date": d, "anchor_head": a["head"], "anchor_head_seq": a["seq"],
                              "anchor_text_sha256": hashlib.sha256(a["text"].encode("utf-8")).hexdigest(),
                              "late": late_of(d, ts, header["anchor_tz"])}

        entry = self._append_with(build, timestamp)
        return {"text": out["text"], "entry": entry}

    # --------------------------------------------------------------------------------------------- read
    def verify(self, withheld: Optional[List[dict]] = None) -> Dict[str, Any]:
        """verify_bytes over the file as it is now (no lock: a reader never blocks a writer)."""
        return verify_bytes(self.path.read_bytes(), withheld=withheld)

    def head(self) -> Optional[str]:
        return self.verify()["head"]

    @property
    def header(self) -> Optional[dict]:
        return self.verify()["header"]
