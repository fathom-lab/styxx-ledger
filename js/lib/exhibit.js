"use strict";
/* exhibit.js: re-derive a published ledger exhibit from its url (`styxx-ledger exhibit <url>`). The python
   package's styxx_ledger/exhibit.py is the same module; the two print the same report.

   What it fetches, from the exhibit's base url: ledger.jsonl, withheld.json, anchors/index.json and every anchor
   text and proof it names, witness/index.json and a sample of the witness proofs. What it asks the block
   explorers (each one; default blockstream.info and mempool.space): GET <explorer>/block-height/<h> -> the block
   hash, then GET <explorer>/block/<hash> -> {merkle_root, timestamp}. Every explorer must give the same hash,
   merkle root and time for a height, or that height is "explorers disagree: not verified".

   What it checks:
     chain    the ledger re-derives (v1 or v0 by the header's schema), withheld lines bridged on their digests
     anchors  each anchor text (the .txt the index names) equals the index's text and sha256 and holds against the
              chain (section 5); its .ots commits to the .txt bytes, verifies natively against the headers, and
              its lowest verified block is the block the index names
     witness  every record in witness/index.json names the chain's entry_id at its seq; a seeded sample of the
              attested records (seed = the ledger file's sha256) plus the earliest and latest attested lines: each
              proof commits to its entry_id and verifies to the block (and block time) the index states

   Transport and age, as in the python module: a file served from another host than the base url (a redirect off
   it, or from https to http) is a failed check unless allowRedirect; an explorer's HTTP 429 is retried on its
   Retry-After (at most 60 s) or on 2, 4, 8, 16 s, then that explorer is left out for the run and the report says it
   rate-limited; an explorer's 404 on block-height/<h> is its answer "no such block". The report gives the last
   holding anchor's age against the run day, each anchor's lag from its date to its lowest block (flagged above
   LATE_DAYS), and an anchor the index marks pending fails once its date is more than PENDING_MAX_DAYS before the run.

   Nothing here writes outside --save, and nothing is signed. The fetch is injectable (runExhibit(url, {get})). */
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const ots = require("./ots");
const v0 = require("./v0");
const { coverage } = require("./verify");
const { VERSION } = require("./ledger");

const DEFAULT_EXPLORERS = ["https://blockstream.info/api", "https://mempool.space/api"];
const TIMEOUT_MS = 30000;
const CAP_BYTES = 20 * 1024 * 1024;
const DEFAULT_SAMPLE = 20;
const RETRY_STATUS = new Set([429, 500, 502, 503, 504]);
const TRIES = 3;               // 5xx and no answer: 3 tries, 1.5 s then 3 s apart
const RATE_TRIES = 5;          // HTTP 429: 5 tries, on Retry-After (capped) or 2, 4, 8, 16 s
const RETRY_AFTER_CAP_S = 60;
const LATE_DAYS = 7;           // an anchor whose lowest block is more than this many days after its date is flagged
const PENDING_MAX_DAYS = 7;    // an anchor still pending this many days after its date fails (the calendars attest within hours)
const ANCHOR_TXT_RX = /^anchors\/[0-9]{4}-[0-9]{2}-[0-9]{2}\.txt$/;
const HEX64_RX = /^[0-9a-f]{64}$/;

const CAVEATS = [
  "reproducible by anyone: the same url gives the same bytes and these answers; the block headers are the " +
  "explorers' word, compared with each other, not read from a bitcoin node.",
  "a proof attests that bytes existed before a bitcoin block, not that they were published at a url or posted " +
  "anywhere at a time.",
  "the anchor texts come from the lab's page; the supergroup they were posted to needs an account to read.",
  "nothing is signed: the ledger, the indexes and the texts are the lab's statements; the proofs and the block " +
  "headers are the outside clock.",
  "a copy that is older but consistent passes every check here: compare the head and the last anchor date with the " +
  "posts, and with a run of your own on another day.",
];

/* What a fetch that got no http answer says, in the same words in both packages (exhibit.py's network_reason maps
   python's exceptions to them): until 2026-11-09 a dns failure read "TypeError: ENOTFOUND" here and "URLError: [Errno
   11001] getaddrinfo failed" there (improvements rank 45). */
const NET_DNS = "the host name did not resolve (dns)";
const NET_REFUSED = "the connection was refused";
const NET_RESET = "the connection was reset";
const NET_TLS = "the tls handshake failed (a certificate or protocol error)";
const netTimeout = ms => "no answer within " + ms / 1000 + " s";
const EXHIBIT_URL_EXAMPLE = "https://fathom-lab.github.io/styxx/ledger/";
/* a proof whose every block an explorer left unanswered: one reason, so the report says it once (rank 44) */
const EXPLORERS_SILENT = "the explorers did not all answer for the proof's blocks";

/* the shared words for a fetch that got no http answer: dns, refused, reset, tls, timeout; anything else reads
   "no answer (<name>: <detail>)". fetch() puts node's code on e.cause (an AggregateError's on its errors too). */
function networkReason(e, timeoutMs) {
  const c = e && e.cause;
  const code = [c, c && Array.isArray(c.errors) ? c.errors[0] : null, e]
    .map(x => (x && typeof x.code === "string" ? x.code : "")).find(Boolean) || "";
  if (["ENOTFOUND", "EAI_AGAIN", "EAI_NONAME", "EAI_NODATA", "EAI_FAIL"].includes(code)) return NET_DNS;
  if (code === "ECONNREFUSED") return NET_REFUSED;
  if (["ECONNRESET", "ECONNABORTED", "EPIPE", "UND_ERR_SOCKET", "UND_ERR_CLOSED"].includes(code)) return NET_RESET;
  if (["ETIMEDOUT", "UND_ERR_CONNECT_TIMEOUT", "UND_ERR_HEADERS_TIMEOUT"].includes(code)) return netTimeout(timeoutMs);
  if (/CERT|SSL|TLS|EPROTO/.test(code)) return NET_TLS;
  return "no answer (" + ((e && e.name) || "Error") + ": " + (code || (c && c.message) || (e && e.message) || String(e)) + ")";
}

class FetchError extends Error {
  /* kind: http (a status the server gave), network (no answer, timeout), too_large (over the cap). */
  constructor(url, kind, message, status, retryAfter) {
    super(message); this.name = "FetchError"; this.url = url; this.kind = kind; this.status = status === undefined ? null : status;
    this.retryAfter = retryAfter === undefined ? null : retryAfter; this.tries = 1;
  }
}

/* Retry-After in seconds (the delta form; an http-date is not read) */
const retryAfter = v => (typeof v === "string" && /^\s*[0-9]+\s*$/.test(v) ? Number(v.trim()) : null);

/* GET url -> {status, body (Buffer), url (the final url after redirects)}. One overall deadline; a body over cap
   bytes is refused. */
async function httpGet(url, opts) {
  const o = opts || {};
  const timeout = o.timeout || TIMEOUT_MS, cap = o.cap || CAP_BYTES;
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeout);
  try {
    let res;
    try {
      res = await fetch(url, { signal: ac.signal, redirect: "follow", headers: { "User-Agent": "styxx-ledger/" + VERSION + " (javascript)", Accept: "*/*" } });
    } catch (e) {
      throw new FetchError(url, "network", ac.signal.aborted ? netTimeout(timeout) : networkReason(e, timeout));
    }
    if (!res.ok) {
      try { await res.body?.cancel(); } catch (e) { /* the status is the answer */ }
      throw new FetchError(url, "http", "HTTP " + res.status, res.status, retryAfter(res.headers.get("retry-after")));
    }
    const cl = res.headers.get("content-length");
    if (cl && /^\s*[0-9]+\s*$/.test(cl) && Number(cl) > cap) {
      try { await res.body?.cancel(); } catch (e) { /* refused anyway */ }
      throw new FetchError(url, "too_large", cl.trim() + " bytes is over the " + cap + " byte cap");
    }
    const chunks = [];
    let n = 0;
    try {
      if (res.body) {
        for await (const chunk of res.body) {
          n += chunk.length;
          if (n > cap) { ac.abort(); throw new FetchError(url, "too_large", "over the " + cap + " byte cap"); }
          chunks.push(Buffer.from(chunk));
        }
      }
    } catch (e) {
      if (e instanceof FetchError) throw e;
      throw new FetchError(url, "network", ac.signal.aborted ? "no complete answer within " + timeout / 1000 + " s" : networkReason(e, timeout));
    }
    return { status: res.status, body: Buffer.concat(chunks), url: res.url || url };
  } finally { clearTimeout(timer); }
}

const sha = b => crypto.createHash("sha256").update(b).digest("hex");
const utc = t => (Number.isInteger(t) ? new Date(t * 1000).toISOString().replace(/\.\d{3}Z$/, "Z") : null);
const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
const isInt = x => Number.isInteger(x) && typeof x === "number";
/* whole days from date a to date b (YYYY-MM-DD each); null when either is unreadable */
function days(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return null;
  const rx = /^([0-9]{4})-([0-9]{2})-([0-9]{2})/;
  const x = rx.exec(a), y = rx.exec(b);
  if (!x || !y) return null;
  const ta = Date.UTC(+x[1], +x[2] - 1, +x[3]), tb = Date.UTC(+y[1], +y[2] - 1, +y[3]);
  const back = (m, t) => { const d = new Date(t); return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3]; };
  if (!back(x, ta) || !back(y, tb)) return null;
  return Math.round((tb - ta) / 86400000);
}
/* a file served from another host than the base url, or moved from https to http */
function offHost(base, fin) {
  if (!fin) return false;
  let b, f;
  try { b = new URL(base); f = new URL(fin); } catch (e) { return true; }
  return f.host.toLowerCase() !== b.host.toLowerCase() || (b.protocol === "https:" && f.protocol !== "https:");
}
const s_ = n => (n === 1 ? "" : "s");

class Fetcher {
  /* every GET goes through here: retried on 429 / 5xx / no answer (3 tries), recorded, optionally saved */
  constructor(get, saveDir, sleep) { this.get = get; this.saveDir = saveDir; this.sleep = sleep; this.files = []; this.explorerCalls = 0; this.waitedMs = 0; }
  /* {status, body, ms, url (final)}. 5xx / no answer: TRIES tries; 429: RATE_TRIES tries on Retry-After. */
  async _get(url) {
    let attempt = 0;
    for (;;) {
      const t0 = Date.now();
      try {
        const r = await this.get(url);
        return { status: r.status, body: Buffer.from(r.body), ms: Date.now() - t0, url: typeof r.url === "string" && r.url ? r.url : url };
      } catch (e) {
        if (!(e instanceof FetchError)) throw e;
        attempt++;
        e.tries = attempt;
        if (e.kind === "too_large" || (e.kind === "http" && !RETRY_STATUS.has(e.status))) throw e;
        const limited = e.kind === "http" && e.status === 429;
        if (attempt >= (limited ? RATE_TRIES : TRIES)) throw e;
        const waitS = limited ? (e.retryAfter !== null ? Math.min(e.retryAfter, RETRY_AFTER_CAP_S) : Math.min(2 * 2 ** (attempt - 1), 30)) : 1.5 * attempt;
        this.waitedMs += waitS * 1000;
        await this.sleep(waitS * 1000);
      }
    }
  }
  _save(rel, body) {
    if (!this.saveDir) return;
    const p = path.join(this.saveDir, ...rel.split("/"));
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
  async file(base, rel) {
    const url = new URL(rel, base).href;
    const rec = { path: rel, url, final_url: null, status: null, bytes: null, sha256: null, ms: null, error: null, error_kind: null };
    let r;
    try { r = await this._get(url); } catch (e) {
      if (!(e instanceof FetchError)) throw e;
      Object.assign(rec, { status: e.status, error: e.message, error_kind: e.kind });
      this.files.push(rec);
      return { body: null, rec };
    }
    Object.assign(rec, { status: r.status, final_url: r.url, bytes: r.body.length, sha256: sha(r.body), ms: r.ms });
    this.files.push(rec);
    this._save(rel, r.body);
    return { body: r.body, rec };
  }
  async explorer(base, p) {
    this.explorerCalls++;
    const url = base.replace(/\/+$/, "") + p;
    const r = await this._get(url);
    let host;
    try { host = new URL(base).host || "explorer"; } catch (e) { host = "explorer"; }
    this._save("_explorers/" + host.replace(/[^A-Za-z0-9._-]/g, "_") + p, r.body);
    return r.body;
  }
}

class Explorers {
  /* the block header source verifyProofAsync asks: every explorer, compared; cached per height */
  constructor(bases, fetcher) { this.bases = bases; this.f = fetcher; this.heights = new Map(); this.dead = new Map(); this.limited = new Map(); }
  async _ask(base, height) {
    const ans = { explorer: base, hash: null, merkle_root: null, timestamp: null, error: null, error_kind: null };
    if (this.dead.has(base)) return Object.assign(ans, { error: "not asked: no answer earlier in this run (" + this.dead.get(base) + ")", error_kind: "network" });
    if (this.limited.has(base)) return Object.assign(ans, { error: "not asked: it rate-limited this run (HTTP 429 after " + this.limited.get(base) + " tries)", error_kind: "rate_limited" });
    try {
      let rawH;
      try { rawH = await this.f.explorer(base, "/block-height/" + height); } catch (e) {
        if (e instanceof FetchError && e.kind === "http" && e.status === 404) return Object.assign(ans, { error: "no such block (HTTP 404 on block-height/" + height + ")", error_kind: "absent" });
        throw e;
      }
      const h = rawH.toString("latin1").trim();
      if (!HEX64_RX.test(h)) throw new SyntaxError("block-height/" + height + " did not answer a block hash");
      const doc = JSON.parse((await this.f.explorer(base, "/block/" + h)).toString("utf8"));
      if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new SyntaxError("block/" + h + " is not a json object");
      const mr = doc.merkle_root, ts = doc.timestamp;
      if (typeof mr !== "string" || !HEX64_RX.test(mr.toLowerCase())) throw new SyntaxError("block/" + h + " carries no merkle_root");
      if (!isInt(ts)) throw new SyntaxError("block/" + h + " carries no integer timestamp");
      if ((doc.id !== undefined && doc.id !== null && doc.id !== h) || (doc.height !== undefined && doc.height !== null && doc.height !== height)) {
        throw new SyntaxError("block/" + h + " names another block (id " + doc.id + ", height " + doc.height + ")");
      }
      Object.assign(ans, { hash: h, merkle_root: mr.toLowerCase(), timestamp: ts });
    } catch (e) {
      if (e instanceof FetchError) {
        Object.assign(ans, { error: e.message + " (" + e.url + ")", error_kind: e.kind });
        if (e.kind === "network") this.dead.set(base, e.message);
        else if (e.kind === "http" && e.status === 429) {
          this.limited.set(base, e.tries);
          Object.assign(ans, { error: "HTTP 429 after " + e.tries + " tries (" + e.url + ")", error_kind: "rate_limited" });
        }
      } else if (e instanceof SyntaxError) Object.assign(ans, { error: "unreadable answer: " + e.message, error_kind: "answer" });
      else throw e;
    }
    return ans;
  }
  async header(height) {
    if (this.heights.has(height)) return this.heights.get(height).result;
    const answers = [];
    for (const b of this.bases) answers.push(await this._ask(b, height));
    const good = answers.filter(a => a.error === null);
    const absent = answers.filter(a => a.error_kind === "absent");
    const silent = answers.filter(a => a.error !== null && a.error_kind !== "absent");
    let rec;
    if (silent.length) {
      const miss = silent.map(a => a.explorer + ": " + a.error).join(", ");
      rec = { verdict: "unanswered", result: { error: "not every explorer answered: " + miss } };
    } else if (absent.length && !good.length) {
      rec = { verdict: "absent", result: { error: "block " + height + " does not exist at any explorer asked" } };
    } else if (absent.length) {
      rec = { verdict: "disagree", result: { error: "explorers disagree on whether block " + height + " exists: not verified" } };
    } else if (new Set(good.map(a => a.hash + "|" + a.merkle_root + "|" + a.timestamp)).size > 1) {
      rec = { verdict: "disagree", result: { error: "explorers disagree: not verified" } };
    } else {
      const a = good[0];
      rec = { verdict: "agree", result: { hash: a.hash, merkle_root: a.merkle_root, timestamp: a.timestamp } };
    }
    rec.height = height; rec.answers = answers;
    this.heights.set(height, rec);
    return rec.result;
  }
  verdict(height) { const r = this.heights.get(height); return r ? r.verdict : null; }
}

/* [verdict, why]: pass | fail | pending | unchecked. One bad path fails the proof; any explorer disagreement on a
   height the proof attests means not verified; a height no explorer knows fails; the lowest verified block must be
   the block the index states, and an index that states none (or, wantTime, no block time) fails. A proof the index
   marks pending stays pending until PENDING_MAX_DAYS after its date (pendingDays), then fails. */
function judgeProof(rep, ex, statedBlock, statedTime, indexStatus, wantTime, pendingDays) {
  const st = rep.status;
  if (st === "refused") return ["fail", "the proof is refused (" + rep.code + "): " + rep.reason];
  if (st === "commitment_mismatch") return ["fail", "commitment mismatch: " + rep.reason];
  if (st === "failed") return ["fail", rep.reason];
  if (st === "no_attestation") return ["fail", "the proof carries no attestation"];
  const heights = Array.from(new Set(rep.bitcoin.map(b => b.height))).sort((a, b) => a - b);
  const disagree = heights.filter(h => ex && ex.verdict(h) === "disagree");
  if (disagree.length) return ["fail", "explorers disagree on block" + s_(disagree.length) + " " + disagree.join(", ") + ": not verified"];
  const absent = heights.filter(h => ex && ex.verdict(h) === "absent");
  if (absent.length) return ["fail", "block" + s_(absent.length) + " " + absent.join(", ") + " do" + (absent.length > 1 ? "" : "es") + " not exist at any explorer asked"];
  if (st === "pending") {
    if (indexStatus === "pending") {
      if (pendingDays !== null && pendingDays !== undefined && pendingDays > PENDING_MAX_DAYS) {
        return ["fail", "pending for " + pendingDays + " days after the anchor date (the rule here: at most " + PENDING_MAX_DAYS + "; the calendars attest within hours)"];
      }
      return ["pending", "calendar receipts only, as the index says; no block yet"];
    }
    return ["fail", "the index does not mark it pending (block " + (statedBlock === null ? "none" : statedBlock) + "); the proof carries calendar receipts only"];
  }
  const unanswered = heights.filter(h => ex && ex.verdict(h) === "unanswered");
  if (st === "unverified") {   // one reason for every proof whose blocks all went unanswered, so the report collapses them
    if (heights.length && unanswered.length === heights.length) return ["unchecked", EXPLORERS_SILENT];
    return ["unchecked", "no block header for any of the proof's blocks (" + heights.join(", ") + ")"];
  }
  const lo = rep.lowest;
  if (indexStatus === "pending") return ["fail", "the index says pending; the proof verifies to block " + lo.height];
  if (statedBlock === null) return ["fail", "the index names no block; the proof's lowest verified block is " + lo.height];
  if (wantTime && statedTime === null) return ["fail", "the index names no block time; block " + lo.height + "'s header says " + lo.time];
  if (lo.height !== statedBlock) {
    if (unanswered.includes(statedBlock)) return ["unchecked", "the explorers did not all answer for block " + statedBlock + ", the block the index states"];
    return ["fail", "the index says block " + statedBlock + "; the proof's lowest verified block is " + lo.height];
  }
  if (statedTime !== null && lo.time !== statedTime) return ["fail", "the index says block time " + statedTime + "; block " + lo.height + "'s header says " + lo.time];
  let note = "verified, block " + lo.height + " (" + utc(lo.time) + ")";
  if (unanswered.length) note += "; not every explorer answered for block" + s_(unanswered.length) + " " + unanswered.join(", ");
  return ["pass", note];
}

/* why the ledger did not arrive, with the url fetched and what to check. a typo in the url is not evidence against
   the publisher, so the check is unchecked (exit 2), never failed (improvements 2026-11-09 rank 45). */
function ledgerMissing(rec) {
  if (rec.error_kind === "http" && rec.status === 404) {
    return rec.url + " answered HTTP 404: there is no ledger.jsonl at that url; check that the url names the exhibit's " +
      "folder, the one that holds ledger.jsonl (e.g. " + EXHIBIT_URL_EXAMPLE + ")";
  }
  if (rec.error_kind === "http") return rec.url + " answered " + rec.error;
  if (rec.error_kind === "network") return rec.url + " did not answer: " + rec.error + "; check the url and this machine's network";
  return rec.url + ": " + rec.error;
}

const ranges = rs => rs.map(([a, b]) => (a === b ? String(a) : a + "-" + b)).join(", ");
const short = h => (typeof h === "string" && h.length > 16 ? h.slice(0, 8) + "..." + h.slice(-6) : String(h));
const parseJson = buf => JSON.parse(buf.toString("utf8"));

/* The whole run; resolves to the report (renderText prints it). exit_code: 0 every check passed, 1 any failed, 2 a
   check could not be made (a file or an explorer did not answer) and none failed. */
async function runExhibit(baseUrl, opts) {
  const o = opts || {};
  const t0 = Date.now();
  const base = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";
  const exps = o.explorers && o.explorers.length ? o.explorers.slice() : DEFAULT_EXPLORERS.slice();
  const sample = o.sample === undefined ? DEFAULT_SAMPLE : o.sample;
  const noOts = !!o.noOts;
  const allowRedirect = !!o.allowRedirect;
  if (o.saveDir) fs.mkdirSync(o.saveDir, { recursive: true });
  const f = new Fetcher(o.get || httpGet, o.saveDir || null, o.sleep || (ms => new Promise(r => setTimeout(r, ms))));
  const ex = noOts ? null : new Explorers(exps, f);
  const checks = [];
  const check = (name, verdict, detail) => checks.push({ name, verdict, detail });
  const rep = {
    tool: "styxx-ledger exhibit", implementation: "javascript", version: VERSION, base_url: base, started_at: now(),
    explorers: noOts ? [] : exps, ots: !noOts, sample, ripemd160_available: ots.ripemd160Available(), caveats: CAVEATS, allow_redirect: allowRedirect,
  };
  const runDay = o.today || rep.started_at.slice(0, 10);
  rep.run_day = runDay;
  const finish = () => {
    const off = f.files.filter(x => offHost(base, x.final_url)).map(x => ({ path: x.path, url: x.url, final_url: x.final_url }));
    rep.off_host = off;
    if (off.length) {
      check("files served from the exhibit's host", allowRedirect ? "pass" : "fail",
        off.length + " file" + s_(off.length) + " served from another host or moved off https (" + Array.from(new Set(off.map(x => x.final_url))).sort().slice(0, 3).join(", ") + ")" + (allowRedirect ? "; allowed by --allow-redirect" : ""));
    }
    rep.checks = checks;
    const n = {};
    for (const v of ["pass", "fail", "pending", "unchecked"]) n[v] = checks.filter(c => c.verdict === v).length;
    rep.counts = Object.assign(n, { total: checks.length });
    rep.ok = n.fail === 0 && n.unchecked === 0;
    rep.exit_code = n.fail ? 1 : (n.unchecked ? 2 : 0);
    rep.fetched = f.files;
    rep.fetched_bytes = f.files.reduce((s, x) => s + (x.bytes || 0), 0);
    rep.explorer_calls = f.explorerCalls;
    rep.explorer_answers = ex ? Array.from(ex.heights.keys()).sort((a, b) => a - b).map(h => ex.heights.get(h)) : [];
    rep.explorers_rate_limited = ex ? Object.fromEntries(ex.limited) : {};
    // an explorer that gave no answer at all (dns, refused, timeout, ...): asked once, then left out for the run
    rep.explorers_unanswered = ex ? Object.fromEntries(exps.filter(b => ex.dead.has(b)).map(b => [b, ex.dead.get(b)])) : {};
    rep.retry_wait_s = Math.round(f.waitedMs / 100) / 10;
    rep.finished_at = now();
    rep.wall_clock_s = Math.round(Date.now() - t0) / 1000;
    return rep;
  };

  // ---- the ledger and its withheld list
  const lr = await f.file(base, "ledger.jsonl");
  if (lr.body === null) {   // nothing can be verified, so nothing failed: exit 2, never the exit of a failed check
    check("ledger.jsonl fetched", "unchecked", ledgerMissing(lr.rec));
    rep.chain = null;
    return finish();
  }
  const raw = lr.body;
  const wr = await f.file(base, "withheld.json");
  let withheld = [];
  if (wr.body === null) {
    if (wr.rec.status === 404) rep.withheld_note = "no withheld.json at the exhibit (404): read as no withheld lines";
    else check("withheld.json fetched", "unchecked", wr.rec.error);
  } else {
    try {
      let doc = parseJson(wr.body);
      if (doc && typeof doc === "object" && !Array.isArray(doc)) doc = doc.withheld || [];
      if (!Array.isArray(doc)) throw new Error("not a list");
      withheld = doc.filter(w => w && typeof w === "object" && !Array.isArray(w));
    } catch (e) { check("withheld.json reads", "fail", "withheld.json is not a list of {seq, entry_id}: " + e.message); }
  }
  const r = v0.verifyAuto(raw, { withheld });
  const proto = r.protocol;
  const entries = r.entries;
  const bySeq = new Map();
  for (const { entry: e } of entries) if (isInt(e.seq) && typeof e.entry_id === "string") bySeq.set(e.seq, e.entry_id);
  // a withheld record counts only when the chain reader bridged it: a later published line's prev names its digest
  const bound = new Set(r.bridged);
  const wmap = new Map();
  for (const w of withheld) if (isInt(w.seq)) wmap.set(w.seq, w.entry_id);
  const wbound = withheld.filter(w => bound.has(w.seq));
  const unbound = [];
  for (const s of Array.from(wmap.keys()).filter(x => !bound.has(x)).sort((a, b) => a - b)) {
    unbound.push({ seq: s, why: bySeq.has(s) ? "withheld.json names seq " + s + ", which is published" : "withheld.json names seq " + s + ", which no published line binds (no later line's prev names its digest)" });
  }
  for (const s of bound) if (!bySeq.has(s)) bySeq.set(s, wmap.get(s));
  const lastSeq = bySeq.size ? Math.max(...bySeq.keys()) : 0;
  const nb = bound.size;
  rep.chain = { protocol: proto, rederives: r.ok, lines: entries.length + nb, published: entries.length, withheld: nb,
    bridged: r.bridged, head: r.head, last_seq: lastSeq, problems: r.problems.length, problem_records: r.problems.slice(0, 50),
    withheld_records: wmap.size, withheld_unbound: unbound, file_sha256: r.file_sha256, file_bytes: raw.length };
  let detail = (entries.length + nb) + " lines (" + entries.length + " published + " + nb + " withheld), head " + r.head + ", " + r.problems.length + " problems";
  if (unbound.length) detail += "; " + unbound.slice(0, 5).map(u => u.why).join("; ");
  check("chain re-derives, every withheld record bound by a later line", r.ok && !unbound.length ? "pass" : "fail", detail);

  // ---- anchors
  const ar = await f.file(base, "anchors/index.json");
  const anchorsOut = [], holdingSeqs = [];
  if (ar.body === null) check("anchors/index.json fetched", ar.rec.error_kind === "http" ? "fail" : "unchecked", ar.rec.error);
  else {
    let alist;
    try {
      const aidx = parseJson(ar.body);
      alist = aidx && typeof aidx === "object" ? aidx.anchors : null;
      if (!Array.isArray(alist)) throw new Error("no anchors list");
    } catch (e) { check("anchors/index.json reads", "fail", "anchors/index.json is not {anchors: [...]}: " + e.message); alist = []; }
    for (let i = 0; i < alist.length; i++) {
      const ai = alist[i] && typeof alist[i] === "object" ? alist[i] : {};
      const date = typeof ai.date === "string" ? ai.date : "#" + i;
      const idx = {};
      for (const k of ["text", "text_sha256", "seq", "head", "block", "status", "ots_sha256", "file", "ots"]) idx[k] = ai[k] === undefined ? null : ai[k];
      const a = { date, index: idx };
      anchorsOut.push(a);
      const rel = ai.file;
      if (typeof rel !== "string" || !ANCHOR_TXT_RX.test(rel)) {
        a.text_check = { verdict: "fail", why: "the index names no anchors/<date>.txt file (" + JSON.stringify(rel === undefined ? null : rel) + ")" };
        check("anchor " + date + " text", "fail", a.text_check.why);
        continue;
      }
      let orel = typeof ai.ots === "string" ? ai.ots : rel + ".ots";
      if (orel !== rel + ".ots") { orel = rel + ".ots"; a.ots_path_note = "the index's ots path is not <file>.ots; read " + orel; }
      const tr = await f.file(base, rel);
      if (tr.body === null) {
        const v = tr.rec.error_kind === "http" ? "fail" : "unchecked";
        a.text_check = { verdict: v, why: "the text file did not arrive: " + tr.rec.error };
        check("anchor " + date + " text", v, a.text_check.why);
        continue;
      }
      const txt = tr.body;
      const text = txt.toString("utf8");
      a.text = text; a.text_sha256 = sha(txt);
      const why = [];
      if (typeof ai.text === "string" && ai.text !== text) why.push("the .txt is not the index's text");
      if (typeof ai.text_sha256 === "string" && ai.text_sha256 !== a.text_sha256) why.push("the .txt's sha256 is not the index's");
      a.text_check = { verdict: why.length ? "fail" : "pass", why: why.length ? why.join("; ") : "the .txt is the index's text and sha256" };
      check("anchor " + date + " text matches the index", a.text_check.verdict, a.text_check.why);
      const parsed = v0.parseAnchorAuto(text, proto);
      if (!parsed) {
        const form = proto === "v0" ? "gate anchor <date> head <64 hex> seq <n>" : "<agent> anchor <date> head <64 hex> seq <n>";
        a.chain_check = { verdict: "fail", why: "not in the anchor form '" + form + "'" };
      } else {
        const c = v0.checkAnchorAuto(r, parsed, wbound);
        const cw = [];
        if (!c.agent_matches) cw.push("the agent is not the header's");
        if (!c.in_chain) {
          if (wmap.has(c.seq) && !bound.has(c.seq) && !bySeq.has(c.seq)) cw.push("not in chain: seq " + c.seq + " is a withheld digest no published line binds");
          else cw.push(c.seq > lastSeq ? "not in chain: seq " + c.seq + " is after the last line (seq " + lastSeq + ")" : "not in chain: the line at seq " + c.seq + " carries another digest");
        }
        if (c.day_lines_after) cw.push(c.day_lines_after + " line" + s_(c.day_lines_after) + " of " + c.date + " after seq " + c.seq);
        const own = c.ledger_anchor_line;
        if (own && !own.agrees) cw.push("the ledger's own anchor entry (seq " + own.seq + ") disagrees");
        a.seq = c.seq; a.head = c.head;
        let held = "holds";
        if (c.ok && c.via_withheld) {
          const later = Array.from(bySeq.keys()).filter(x => x > c.seq && !bound.has(x));
          held = "holds on a withheld digest that seq " + (later.length ? Math.min(...later) : "?") + " binds";
        }
        a.chain_check = Object.assign({}, c, { verdict: c.ok ? "pass" : "fail", why: c.ok ? held : cw.join("; ") });
        if (c.ok) holdingSeqs.push(c.seq);
      }
      check("anchor " + date + " holds against the chain", a.chain_check.verdict, a.chain_check.why);
      if (noOts) continue;
      const pr0 = await f.file(base, orel);
      if (pr0.body === null) {
        const v = pr0.rec.error_kind === "http" ? "fail" : "unchecked";
        a.proof = { verdict: v, why: "the proof did not arrive: " + pr0.rec.error };
        check("anchor " + date + " proof", v, a.proof.why);
        continue;
      }
      const pr = await ots.verifyProofAsync(pr0.body, { target: txt, getHeader: h => ex.header(h) });
      const stated = isInt(ai.block) ? ai.block : null;
      let [verdict, pwhy] = judgeProof(pr, ex, stated, null, ai.status, false, days(typeof ai.date === "string" ? ai.date : null, runDay));
      if (verdict === "pass" && typeof ai.ots_sha256 === "string" && ai.ots_sha256 !== sha(pr0.body)) { verdict = "fail"; pwhy = "the .ots's sha256 is not the index's (" + pwhy + ")"; }
      a.proof = { verdict, why: pwhy, status: pr.status, stated_block: stated, lowest: pr.lowest, ots_sha256: sha(pr0.body), report: pr };
      if (verdict === "pass" && pr.lowest) {
        const lag = days(date, utc(pr.lowest.time));
        a.proof.lag_days = lag;
        a.proof.late = lag !== null && lag > LATE_DAYS;
      }
      check("anchor " + date + " proof verifies", verdict, pwhy);
    }
  }
  rep.anchors = anchorsOut;
  rep.coverage = coverage(entries, wbound, holdingSeqs);
  const holding = anchorsOut.filter(a => (a.chain_check || {}).verdict === "pass");
  if (holding.length) {
    const last = holding.reduce((m, a) => (a.seq > m.seq ? a : m), holding[0]);
    rep.last_holding_anchor = { date: last.date, seq: last.seq, days_before_run: days(last.date, runDay), lines_after: rep.coverage.after_last_anchor };
  } else rep.last_holding_anchor = null;
  const ledgerAnchorDates = Array.from(new Set(entries.filter(({ entry: e }) => e.kind === "anchor" && typeof e.anchor_date === "string").map(({ entry: e }) => e.anchor_date))).sort();
  const idxDates = new Set(anchorsOut.map(a => a.date));
  rep.ledger_anchor_entries = { dates: ledgerAnchorDates, not_in_index: ledgerAnchorDates.filter(d => !idxDates.has(d)) };

  // ---- witness
  const wit = { present: false };
  rep.witness = wit;
  const wr2 = await f.file(base, "witness/index.json");
  if (wr2.body === null) {
    if (wr2.rec.status === 404) wit.note = "no witness/index.json at the exhibit (404): no witness check";
    else check("witness/index.json fetched", "unchecked", wr2.rec.error);
    return finish();
  }
  let wents;
  try {
    const widx = parseJson(wr2.body);
    wents = widx && typeof widx === "object" ? widx.entries : null;
    if (!wents || typeof wents !== "object" || Array.isArray(wents)) throw new Error("no entries object");
  } catch (e) { check("witness/index.json reads", "fail", "witness/index.json is not {entries: {...}}: " + e.message); return finish(); }
  wit.present = true;
  const statuses = {}, matched = [], mismatched = [], outside = [];
  for (const eid of Object.keys(wents)) {
    const w = wents[eid] && typeof wents[eid] === "object" ? wents[eid] : {};
    const st = typeof w.status === "string" ? w.status : "?";
    statuses[st] = (statuses[st] || 0) + 1;
    const s = w.seq;
    if (!isInt(s) || !bySeq.has(s)) outside.push({ entry_id: eid, seq: s === undefined ? null : s });
    else if (bySeq.get(s) !== eid) mismatched.push({ entry_id: eid, seq: s, chain_entry_id: bySeq.get(s) });
    else matched.push([eid, w]);
  }
  const covered = new Set(matched.map(([, w]) => w.seq));
  Object.assign(wit, { records: Object.keys(wents).length, statuses, at_their_seq: matched.length, name_another_digest: mismatched.length,
    mismatches: mismatched.slice(0, 50), not_in_chain: outside.length, not_in_chain_records: outside.slice(0, 50),
    chain_lines: bySeq.size, chain_lines_with_record: covered.size });
  check("witness records name the chain's entry_id at their seq", mismatched.length ? "fail" : "pass",
    matched.length + " of " + Object.keys(wents).length + " records at their seq; " + mismatched.length + " name another digest; " + outside.length + " name a line not in the chain");
  const seed = r.file_sha256;
  const rank = eid => sha(Buffer.concat([Buffer.from(seed, "hex"), Buffer.from(eid, "hex")]));
  const attested = matched.filter(([eid, w]) => w.status === "bitcoin" && HEX64_RX.test(eid));
  const picked = new Map();
  if (sample > 0 && !noOts && attested.length) {
    const ranked = attested.map(([eid, w]) => [rank(eid), eid, w]).sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
    for (const [, eid] of ranked.slice(0, sample)) picked.set(eid, { why: "seeded" });
    let lo = attested[0], hi = attested[0];
    for (const x of attested) { if (x[1].seq < lo[1].seq) lo = x; if (x[1].seq > hi[1].seq) hi = x; }
    for (const [eid, why] of [[lo[0], "earliest attested line"], [hi[0], "latest attested line"]]) {
      if (picked.has(eid)) picked.get(eid).why += ", " + why; else picked.set(eid, { why });
    }
  }
  Object.assign(wit, {
    sample_rule: "attested records (status bitcoin, at their seq in the chain) ranked by sha256(bytes(seed) + bytes(entry_id)), seed = the ledger file's sha256; the top n, plus the earliest and latest attested lines",
    seed, sample_n: sample, attested: attested.length, sampled: [] });
  for (const eid of Array.from(picked.keys()).sort((x, y) => wents[x].seq - wents[y].seq)) {
    const w = wents[eid];
    const item = { entry_id: eid, seq: w.seq, picked: picked.get(eid).why, stated_block: w.block === undefined ? null : w.block, stated_time: w.block_time === undefined ? null : w.block_time };
    wit.sampled.push(item);
    const prel = w.proof;
    if (prel !== "proofs/" + eid + ".ots") {
      Object.assign(item, { verdict: "fail", why: "the index names the proof " + JSON.stringify(prel === undefined ? null : prel) + ", not proofs/<entry_id>.ots" });
      check("witness seq " + w.seq + " proof", "fail", item.why);
      continue;
    }
    const pf = await f.file(base, "witness/" + prel);
    if (pf.body === null) {
      const v = pf.rec.error_kind === "http" ? "fail" : "unchecked";
      Object.assign(item, { verdict: v, why: "the proof did not arrive: " + pf.rec.error });
      check("witness seq " + w.seq + " proof", v, item.why);
      continue;
    }
    const pr = await ots.verifyProofAsync(pf.body, { digest: eid, getHeader: h => ex.header(h) });
    const [verdict, pwhy] = judgeProof(pr, ex, isInt(w.block) ? w.block : null, isInt(w.block_time) ? w.block_time : null, "bitcoin", true, null);
    Object.assign(item, { verdict, why: pwhy, status: pr.status, lowest: pr.lowest, ots_sha256: sha(pf.body), report: pr });
    check("witness seq " + w.seq + " proof commits and verifies", verdict, pwhy);
  }
  return finish();
}

function lagSummary(pv) {
  const lags = pv.map(a => a.proof.lag_days).filter(x => Number.isInteger(x)).sort((a, b) => a - b);
  if (!lags.length) return "none";
  return lags[0] !== lags[lags.length - 1] ? lags[0] + " to " + lags[lags.length - 1] + " days" : lags[0] + " days";
}

function renderText(rep) {
  const L = [];
  const say = s => L.push(s === undefined ? "" : s);
  say("styxx-ledger exhibit (" + rep.implementation + " " + rep.version + "): " + rep.base_url);
  const nexp = rep.explorer_answers.length;
  say("fetched " + rep.fetched.length + " files (" + rep.fetched_bytes + " bytes) from the exhibit; " + rep.explorer_calls + " explorer calls for " + nexp + " block" + s_(nexp) + "; every sha256 and answer is in --json");
  if (rep.ripemd160_available === false) say("note: this node's crypto has no ripemd160; a proof that needs it is refused (ripemd160_unavailable)");
  const silent = rep.explorers_unanswered || {};
  for (const b of rep.explorers || []) {   // the reason, once, before the lines it explains (rank 44)
    if (Object.prototype.hasOwnProperty.call(silent, b)) say("explorer " + b + " did not answer: " + silent[b] + "; check the network, or pass --explorer <url> to ask another esplora api");
  }
  say();
  const c = rep.chain;
  if (!c) {
    const bad = rep.checks.filter(x => x.verdict !== "pass");
    say("ledger.jsonl: " + (bad.length ? bad[0].detail : "not fetched"));
    say("nothing was verified: every other check needs the ledger");
  } else {
    say("chain (protocol " + c.protocol + "): " + (c.rederives ? "re-derives:" : "DOES NOT re-derive:") + " " + c.lines + " lines = " + c.published + " published + " + c.withheld + " withheld, head " + c.head + " (seq " + c.last_seq + "), " + c.problems + " problem record" + s_(c.problems));
    if (c.bridged.length) say("  withheld lines bridged on their published digests (the publisher's word for what they hold back): seq " + c.bridged.join(","));
    for (const u of c.withheld_unbound || []) say("  FAIL " + u.why);
    for (const p of c.problem_records.slice(0, 10)) {
      const text = p.problem || (p.problems || []).join("; ");
      say("  line " + p.line + " seq " + p.seq + " " + (p.codes || [p.code || "?"]).join(",") + ": " + text);
    }
  }
  const an = rep.anchors || [];
  if (an.length) {
    const hold = an.filter(a => (a.chain_check || {}).verdict === "pass").length;
    const tm = an.filter(a => (a.text_check || {}).verdict === "pass").length;
    say("anchors: " + hold + " of " + an.length + " anchor texts hold against the chain (section 5 of protocol " + (c ? c.protocol : "?") + "); " + tm + " of " + an.length + " .txt files are the index's text");
    if (rep.ots) {
      const pv = an.filter(a => (a.proof || {}).verdict === "pass");
      const lows = new Map();
      for (const a of pv) lows.set(a.proof.lowest.height, (lows.get(a.proof.lowest.height) || 0) + 1);
      const lowText = Array.from(lows.entries()).sort((x, y) => x[0] - y[0]).map(([h, n]) => (n > 1 ? h + " x" + n : String(h))).join(", ") || "none";
      const npend = an.filter(a => (a.proof || {}).verdict === "pending").length;
      const nunch = an.filter(a => (a.proof || {}).verdict === "unchecked").length;
      say("anchor proofs: " + pv.length + " of " + an.length + " verify natively against bitcoin block headers, each to the block the index names (lowest blocks: " + lowText + ")" + (npend ? "; " + npend + " of " + an.length + " pending" : "") + (nunch ? "; " + nunch + " of " + an.length + " not checked" : ""));
      const late = pv.filter(a => a.proof.late);
      say("  lag from an anchor's date to its lowest block: " + lagSummary(pv) + "; " + late.length + " of " + pv.length + " over " + LATE_DAYS + " days (the proof pins such a text from its block, not from its date)");
    }
    for (const a of an) {
      const parts = [];
      const tc = a.text_check || {}, cc = a.chain_check || null, pf = a.proof || null;
      if (tc.verdict !== "pass") parts.push("text: " + tc.why);
      if (cc) parts.push("chain: " + cc.why);
      if (pf) parts.push(pf.verdict === "pass" ? "proof " + pf.why + ", index says block " + pf.stated_block + ", " + pf.lag_days + " day" + s_(pf.lag_days) + " after the anchor date" + (pf.late ? " (late)" : "") : "proof " + (pf.verdict === "fail" ? "FAILS" : pf.verdict) + ": " + pf.why);
      const vs = [tc, cc, pf].filter(Boolean).filter(x => Object.keys(x).length).map(x => x.verdict);
      const label = vs.every(v => v === "pass") ? "ok  " : (vs.every(v => v === "pass" || v === "pending") ? "PEND"
        : (vs.includes("fail") ? "FAIL" : "----"));   // ----: nothing failed, something could not be checked
      say("  " + a.date + " seq " + String(a.seq === undefined ? "?" : a.seq).padEnd(4) + " " + label + " " + parts.join("; "));
    }
  } else if (c) say("anchors: none read");
  const cov = rep.coverage;
  const la = rep.last_holding_anchor;
  if (c && cov) say("coverage: " + cov.pinned + " of " + c.published + " published entries pinned by holding anchors; " + cov.unpinned_by_withholding + " unpinned by withholding [" + ranges(cov.unpinned_ranges) + "]; " + cov.after_last_anchor + " after the last holding anchor (seq " + cov.last_anchor_seq + "); " + cov.withheld + " withheld");
  if (c && la) say("age: the last holding anchor is " + la.date + " (seq " + la.seq + "), " + la.days_before_run + " day" + s_(la.days_before_run) + " before this run (" + rep.run_day + "); " + la.lines_after + " line" + s_(la.lines_after) + " after it " + (la.lines_after === 1 ? "is" : "are") + " pinned by nothing here");
  const w = rep.witness || {};
  if (w.present) {
    const st = Object.entries(w.statuses).sort((x, y) => y[1] - x[1]).map(([k, n]) => n + " " + k).join(", ");
    say("witness index: " + w.records + " records (" + st + "); " + w.chain_lines_with_record + " of " + w.chain_lines + " chain lines carry one at their seq; " + w.name_another_digest + " name another digest; " + w.not_in_chain + " name a line not in the chain");
    if (rep.ots && w.sample_n > 0) {
      const sm = w.sampled;
      const ok = sm.filter(x => x.verdict === "pass");
      const blocks = Array.from(new Set(ok.map(x => x.lowest.height))).sort((a, b) => a - b);
      const seeded = sm.filter(x => x.picked.startsWith("seeded")).length;
      const ends = sm.filter(x => x.picked.includes("attested line")).map(x => x.seq);
      say("witness proofs: " + sm.length + " sampled of " + w.attested + " attested (" + seeded + " by the seeded rule, seed = the ledger's sha256 " + short(w.seed) + ", plus the earliest and latest attested lines, seq " + (ends.join(" and ") || "-") + "): " + ok.length + " of " + sm.length + " commit to their entry_id and verify to their stated block (" + (blocks.join(", ") || "none") + ")");
      const unch = new Map();   // unchecked proofs that share a reason: said once, with their seqs (rank 44)
      for (const x of sm) if (x.verdict === "unchecked") { if (!unch.has(x.why)) unch.set(x.why, []); unch.get(x.why).push(x.seq); }
      const said = new Set();
      for (const x of sm) {
        if (x.verdict === "pass") continue;
        if (x.verdict === "unchecked" && unch.get(x.why).length > 1) {
          if (!said.has(x.why)) { said.add(x.why); say("  " + unch.get(x.why).length + " of " + sm.length + " sampled, seq " + unch.get(x.why).join(",") + ": unchecked: " + x.why); }
          continue;
        }
        say("  seq " + x.seq + " " + short(x.entry_id) + ": " + (x.verdict === "fail" ? "FAILS" : x.verdict) + ": " + x.why);
      }
    } else if (!rep.ots) say("witness proofs: not checked (--no-ots)");
    else say("witness proofs: not sampled (--sample 0)");
  } else if (w.note) say("witness: " + w.note);
  if (!c) {
    // no ledger: nothing was asked of an explorer, and the lines below would only count zeros
  } else if (rep.ots) {
    const ea = rep.explorer_answers;
    const agree = ea.filter(h => h.verdict === "agree").length;
    const dis = ea.filter(h => h.verdict === "disagree").map(h => String(h.height));
    const un = ea.filter(h => h.verdict === "unanswered").map(h => String(h.height));
    say("explorers: " + rep.explorers.join(" and ") + ": " + agree + " of " + ea.length + " blocks asked agree on hash, merkle root and time" + (dis.length ? "; disagree on " + dis.join(", ") : "") + (un.length ? "; not every explorer answered for " + un.join(", ") : ""));
    const ab = ea.filter(h => h.verdict === "absent").map(h => String(h.height));
    if (ab.length) say("  no explorer asked knows block" + s_(ab.length) + " " + ab.join(", "));
    for (const b of Object.keys(rep.explorers_rate_limited || {}).sort()) {
      let host = b;
      try { host = new URL(b).host || b; } catch (e) { /* keep the url */ }
      say("  " + host + " rate-limited this run (HTTP 429 after " + rep.explorers_rate_limited[b] + " tries) and was not asked again; run again in a minute, or name another esplora instance with --explorer");
    }
    if (rep.explorers.length < 2) say("  one explorer only: nothing to compare its headers with");
  } else say("proofs and explorers: not checked (--no-ots)");
  say();
  const n = rep.counts;
  if (rep.exit_code === 0) say("result: every check passed, " + n.pass + " of " + n.total + (n.pending ? "; " + n.pending + " pending, as the index says" : "") + " (exit 0)");
  else {
    say("result: " + n.pass + " of " + n.total + " checks passed; " + n.fail + " failed; " + n.unchecked + " could not be made" + (n.pending ? "; " + n.pending + " pending" : "") + " (exit " + rep.exit_code + ")");
    const same = new Map();   // checks not made for one reason: one line (rank 44); each failure keeps its own
    for (const x of rep.checks) if (x.verdict === "unchecked") { if (!same.has(x.detail)) same.set(x.detail, []); same.get(x.detail).push(x.name); }
    const said = new Set();
    for (const x of rep.checks) {
      if (x.verdict === "fail") say("  FAILED: " + x.name + ": " + x.detail);
      else if (x.verdict === "unchecked" && same.get(x.detail).length === 1) say("  not made: " + x.name + ": " + x.detail);
      else if (x.verdict === "unchecked" && !said.has(x.detail)) {
        said.add(x.detail);
        const names = same.get(x.detail);
        say("  not made: " + names.length + " checks, " + names[0] + " to " + names[names.length - 1] + ": " + x.detail);
      }
    }
  }
  for (const x of rep.off_host || []) say("  served from another host: " + x.path + " -> " + x.final_url);
  say("wall clock " + rep.wall_clock_s.toFixed(1) + " s");
  say();
  say("how to read this:");
  for (const cv of rep.caveats) say("  - " + cv);
  return L.join("\n") + "\n";
}

module.exports = { runExhibit, renderText, httpGet, FetchError, networkReason, DEFAULT_EXPLORERS, DEFAULT_SAMPLE, TIMEOUT_MS, CAP_BYTES, CAVEATS, LATE_DAYS, PENDING_MAX_DAYS, RATE_TRIES, EXPLORERS_SILENT };
