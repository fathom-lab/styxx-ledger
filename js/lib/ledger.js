"use strict";
/* ledger.js: the writer (protocol v1, section 3b). One append:

     1. take the lock: create <log>.lock beside the log, create-exclusive, holding this process's pid. A lock
        older than 30 s whose pid is not a live process may be broken (under a <log>.lock.break file, itself
        create-exclusive, so two writers never both break it); a writer that breaks one writes a lock_recovered
        entry before its own only if the header lists lock_recovered.
     2. re-read the file and re-derive it (verifyBytesSync); when it does not re-derive, or does not end with
        LF, or its header is not one a v1 writer may write, refuse: nothing is appended.
     3. take seq and prev from the tail.
     4. write the canonical line and one LF; fsync.
     5. release the lock.

   Every call here is synchronous (fs.*Sync), so an append has returned only after its fsync. Nothing is
   signed and nothing touches the network: anchor() composes the text and hands it back to post. */
const fs = require("node:fs");
const path = require("node:path");
const { LedgerValueError, dump, setOwn } = require("./jcs");
const { dayOf, nowUtc, lateOf } = require("./day");
const chain = require("./chain");
const { verifyBytesSync, checkAnchor } = require("./verify");
const VERSION = require("../package.json").version;

const LOCK_TIMEOUT_MS = 10000;
const LOCK_STALE_MS = 30000;

class LedgerError extends Error {
  constructor(code, message, extra) {
    super(message);
    this.name = "LedgerError";
    this.code = code;
    if (extra) Object.assign(this, extra);
  }
}
class LedgerLocked extends LedgerError {
  constructor(message) { super("locked", message); this.name = "LedgerLocked"; }
}
class LedgerTamper extends LedgerError {
  constructor(problems) {
    super("tamper", "ledger does not re-derive: " + problems.length + " problem(s); nothing appended", { problems });
    this.name = "LedgerTamper";
  }
}

const sleepCell = new Int32Array(new SharedArrayBuffer(4));
function sleepMs(ms) { Atomics.wait(sleepCell, 0, 0, ms); }

/* Whether a process with this pid runs now. process.kill(pid, 0) is a health check on every platform (libuv
   reads the exit code on windows; it does not signal). A pid this user may not query reads as alive. */
function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; }
  catch (e) { return e && e.code === "EPERM"; }
}

function fsyncDir(dir) {             // posix: make the new file's directory entry durable; windows cannot open a dir
  if (process.platform === "win32") return;
  let fd;
  try { fd = fs.openSync(dir, "r"); fs.fsyncSync(fd); } catch (e) { /* best effort */ } finally { if (fd !== undefined) fs.closeSync(fd); }
}

function writeAll(fd, buf) {
  let off = 0;
  while (off < buf.length) off += fs.writeSync(fd, buf, off, buf.length - off);
}

class Ledger {
  /* path: the log file. opts: lockTimeoutMs (10000), staleMs (30000), writer ({name, version, ...} for start()). */
  constructor(file, opts) {
    opts = opts || {};
    this.path = path.resolve(String(file));
    this.lockPath = this.path + ".lock";
    this.breakPath = this.lockPath + ".break";
    this.lockTimeoutMs = opts.lockTimeoutMs === undefined ? LOCK_TIMEOUT_MS : opts.lockTimeoutMs;
    this.staleMs = opts.staleMs === undefined ? LOCK_STALE_MS : opts.staleMs;
    this.writer = Object.assign({ language: "javascript", name: "styxx-ledger", version: VERSION }, opts.writer || {});
  }

  /* Create a new log holding only its header. `h` is a full header object (written as given, after
     checkHeader), or the short form {agent, certifies, anchorTz (default UTC), kinds (default ["note"]; anchor
     and started are always added), created (default now)}. Refuses (code exists) when the file is already
     there. Returns a Ledger. */
  static init(file, h, opts) {
    const L = new Ledger(file, opts);
    h = h || {};
    const header = h.schema !== undefined ? h : chain.makeHeader(
      h.created || nowUtc(), h.anchorTz || h.anchor_tz || "UTC", h.agent, h.certifies,
      ["anchor", "started"].concat(h.kinds || ["note"]));   // the short form always gains anchor and started
    chain.checkHeader(header);
    const line = Buffer.from(dump(header) + "\n", "utf8");
    L._withLock(() => {
      let fd;
      try { fd = fs.openSync(L.path, "wx"); }
      catch (e) {
        if (e.code === "EEXIST") throw new LedgerError("exists", "the log already exists: " + L.path);
        throw e;
      }
      try { writeAll(fd, line); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
      fsyncDir(path.dirname(L.path));
    });
    return L;
  }

  // ------------------------------------------------------------------------------------------------ lock
  _acquire() {
    const deadline = Date.now() + this.lockTimeoutMs;
    let recovered = null;
    for (;;) {
      try {
        const fd = fs.openSync(this.lockPath, "wx");
        try { fs.writeSync(fd, String(process.pid)); } finally { fs.closeSync(fd); }
        return recovered;
      } catch (e) {
        // EPERM / EACCES: windows reports these while another process deletes the lock; retry like EEXIST
        if (!e || !["EEXIST", "EPERM", "EACCES"].includes(e.code)) throw e;
        if (e.code === "EEXIST" && recovered === null) {
          const stale = this._staleLock();
          if (stale !== null) {
            const got = this._breakLock(stale);
            if (got !== null) { recovered = got; continue; }
          }
        }
        if (Date.now() >= deadline) throw new LedgerLocked("lock " + this.lockPath + " held over " + this.lockTimeoutMs + " ms");
        sleepMs(50);
      }
    }
  }

  /* A lock is stale when it is older than staleMs and its pid is not a live process (a lock naming no pid, a
     writer that died between create and write, counts as no live process). Age is decided on the stat alone,
     so a fresh lock is never opened (on windows an open reader can hold up its owner's unlink). */
  _staleLock() {
    let st, body;
    try { st = fs.statSync(this.lockPath); } catch (e) { return null; }
    const age = Math.max(0, Date.now() - st.mtimeMs);
    if (age <= this.staleMs) return null;
    try { body = fs.readFileSync(this.lockPath).subarray(0, 64); } catch (e) { return null; }
    const text = body.toString("latin1").trim();
    const pid = /^\d+$/.test(text) ? parseInt(text, 10) : null;
    if (pid !== null && (pid === process.pid || pidAlive(pid))) return null;
    return { stale_pid: pid, stale_age_s: Math.floor(age / 1000), body };
  }

  _breakLock(stale) {
    let fd;
    try { fd = fs.openSync(this.breakPath, "wx"); fs.closeSync(fd); }
    catch (e) {
      try { if (Date.now() - fs.statSync(this.breakPath).mtimeMs > this.staleMs) fs.unlinkSync(this.breakPath); } catch (e2) { /* gone */ }
      return null;
    }
    try {
      let now;
      try { now = fs.readFileSync(this.lockPath).subarray(0, 64); } catch (e) { return null; }
      if (!now.equals(stale.body)) return null;
      try { fs.unlinkSync(this.lockPath); } catch (e) { return null; }
      return { stale_pid: stale.stale_pid, stale_age_s: stale.stale_age_s };   // the python writer's fields
    } finally {
      try { fs.unlinkSync(this.breakPath); } catch (e) { /* gone */ }
    }
  }

  /* Remove our lock. On windows an unlink fails (EPERM / EBUSY) while another process has the file open for a
     moment (a python reader judging staleness); retry for up to 5 s, then say so. */
  _release() {
    const deadline = Date.now() + 5000;
    for (;;) {
      try {
        if (fs.readFileSync(this.lockPath, "latin1").trim() !== String(process.pid)) return;   // not ours (broken and retaken)
        fs.unlinkSync(this.lockPath);
        return;
      } catch (e) {
        if (!e || e.code === "ENOENT") return;
        if (!["EPERM", "EBUSY", "EACCES"].includes(e.code)) throw e;
        if (Date.now() >= deadline) {
          throw new LedgerError("lock_release", "could not remove " + this.lockPath + " (held open by another process); it reads stale " + (this.staleMs / 1000) + " s after this process exits");
        }
        sleepMs(10);
      }
    }
  }

  _withLock(fn) {
    const recovered = this._acquire();
    try { return fn(recovered); } finally { this._release(); }
  }

  // ----------------------------------------------------------------------------------------------- state
  /* verifyBytesSync of the file as it is now (no lock). */
  read() {
    return verifyBytesSync(fs.readFileSync(this.path));
  }

  /* {head, seq}: the head the file re-derives to and its seq (0 for a header-only log). Throws LedgerTamper. */
  head() {
    const r = this._state(false);
    return { head: r.head, seq: r.entries.length ? r.entries[r.entries.length - 1].entry.seq : 0 };
  }

  _state(strictTail) {
    let raw;
    try { raw = fs.readFileSync(this.path); }
    catch (e) {
      if (e.code === "ENOENT") throw new LedgerError("no_log", "no log at " + this.path + " (init it first)");
      throw e;
    }
    const r = verifyBytesSync(raw);
    const problems = r.problems.slice();
    if (r.header === null) problems.push({ line: 1, seq: null, code: "no_header", problem: "no v1 header" });
    if (strictTail !== false && raw.length && raw[raw.length - 1] !== 0x0a) {
      problems.push({ line: null, seq: null, code: "tail", problem: "the file does not end with LF" });
    }
    if (problems.length) throw new LedgerTamper(problems);
    chain.checkHeader(r.header);
    return r;
  }

  _appendLines(entries) {
    const buf = Buffer.from(entries.map(e => dump(e) + "\n").join(""), "utf8");
    const fd = fs.openSync(this.path, "a");
    try { writeAll(fd, buf); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  }

  /* Under the lock: re-derive, then compose(header, entries, seq, prev) -> [[kind, fields, timestamp], ...]. */
  _commit(compose, ts) {
    return this._withLock(recovered => {
      const r = this._state(true);
      let seq = r.entries.length ? r.entries[r.entries.length - 1].entry.seq + 1 : 1;
      let prev = r.head;
      const out = [];
      let lastAnchored = null;   // the latest anchor_date in the file: an entry of that day or earlier would break its post
      for (const it of r.entries) {
        const d = it.entry.anchor_date;
        if (it.entry.kind === "anchor" && typeof d === "string" && (lastAnchored === null || d > lastAnchored)) lastAnchored = d;
      }
      const push = (kind, fields, timestamp) => {
        const e = chain.buildEntry(r.header, seq, prev, kind, timestamp, fields);
        if (lastAnchored !== null && e.day <= lastAnchored) {
          throw new LedgerError("anchored_day", "an entry of day " + e.day + " would follow the anchor of " + lastAnchored + " and break it; refused");
        }
        if (kind === "anchor" && (lastAnchored === null || e.anchor_date > lastAnchored)) lastAnchored = e.anchor_date;
        out.push(e); prev = e.entry_id; seq++;
        return e;
      };
      if (recovered !== null && r.header.kinds.includes("lock_recovered")) push("lock_recovered", recovered, ts || nowUtc());
      for (const [kind, fields, timestamp] of compose(r, seq, prev)) push(kind, fields, timestamp || ts || nowUtc());
      this._appendLines(out);
      return out;
    });
  }

  /* Append one entry of `kind` with `fields`. opts.timestamp (YYYY-MM-DDTHH:MM:SSZ) for synthetic logs and
     tests; otherwise the clock. Returns the entry as written. Refuses (anchored_day) an entry whose day is a
     day already anchored: it would sit after that day's posted head and break it. */
  append(kind, fields, opts) {
    const ts = opts && opts.timestamp;
    const f = fields === undefined ? {} : fields;
    if (ts !== undefined) dayOf(ts, "UTC");   // refuse a bad timestamp before taking the lock
    const out = this._commit(() => [[kind, f, ts]], ts);
    return out[out.length - 1];
  }

  /* The started entry for this writer process: {writer: {language, name, version}, ...extra}. */
  start(extra, opts) {
    const fields = {};
    for (const k of Object.keys(extra || {})) setOwn(fields, k, extra[k]);
    fields.writer = Object.assign({}, this.writer, (extra && extra.writer) || {});
    return this.append("started", fields, opts);
  }

  // ---------------------------------------------------------------------------------------------- anchor
  /* The head at the close of `date`: the last entry whose day is that date (section 5). -> {seq, head} or null. */
  static closingHead(entries, date) {
    let pick = null;
    for (const it of entries) if (it.entry.day === date && (pick === null || it.entry.seq > pick.seq)) pick = it.entry;
    return pick === null ? null : { seq: pick.seq, head: pick.entry_id };
  }

  _composeAnchor(r, date, ts) {
    if (typeof date !== "string" || !chain.DATE_RX.test(date)) throw new LedgerValueError("anchor_form", "date is not YYYY-MM-DD");
    const tz = r.header.anchor_tz;
    const today = dayOf(ts, tz);
    if (today <= date) throw new LedgerError("day_open", date + " has not closed in " + tz + " (it is " + today + " there)");
    if (r.entries.some(it => it.entry.kind === "anchor" && it.entry.anchor_date === date)) {
      throw new LedgerError("already_anchored", "the ledger already holds an anchor entry for " + date);
    }
    const c = Ledger.closingHead(r.entries, date);
    if (c === null) throw new LedgerError("nothing_to_anchor", "no entry has day " + date + "; there is nothing to anchor");
    const text = chain.anchorText(r.header.agent, date, c.head, c.seq);
    // the text must check against the file as it stands (the anchor entry itself lands on a later day)
    const check = checkAnchor(r.entries, chain.parseAnchorText(text), [], r.header);
    if (!check.ok) throw new LedgerError("anchor_check", "the composed anchor does not check: " + JSON.stringify(check));
    const fields = {
      anchor_date: date, anchor_head: c.head, anchor_head_seq: c.seq,
      anchor_text_sha256: chain.sha256Hex(text), late: lateOf(date, ts, tz)   // section 5's rule, never the caller's
    };
    return { text, date, head: c.head, seq: c.seq, fields };
  }

  /* Compose the anchor text for `date` without writing anything. opts.timestamp stands in for the clock. */
  composeAnchor(date, opts) {
    const ts = (opts && opts.timestamp) || nowUtc();
    if (opts && opts.late !== undefined) throw new LedgerValueError("anchor_form", "late is set by the writer (section 5), not the caller");
    const a = this._composeAnchor(this._state(true), date, ts);
    return { text: a.text, date: a.date, head: a.head, seq: a.seq };
  }

  /* Compose the anchor text for `date`, write the anchor entry, and return {text, entry}: posting the text in a
     public place is the caller's. Refuses (day_open) while `date` has not closed in anchor_tz. */
  anchor(date, opts) {
    if (opts && opts.late !== undefined) throw new LedgerValueError("anchor_form", "late is set by the writer (section 5), not the caller");
    const ts = (opts && opts.timestamp) || nowUtc();
    let composed = null;
    const out = this._commit(r => {
      composed = this._composeAnchor(r, date, ts);
      return [["anchor", composed.fields, ts]];
    }, ts);
    return { text: composed.text, entry: out[out.length - 1] };
  }
}

module.exports = { Ledger, LedgerError, LedgerLocked, LedgerTamper, pidAlive, LOCK_TIMEOUT_MS, LOCK_STALE_MS, VERSION };
