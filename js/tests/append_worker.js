"use strict";
/* append_worker.js: a child process for the concurrency test. node append_worker.js <log> <n> <tag> */
const { Ledger } = require("../lib/ledger");

const [log, n, tag] = process.argv.slice(2);
const led = new Ledger(log, { lockTimeoutMs: 60000 });
for (let i = 0; i < Number(n); i++) led.append("note", { worker: tag, i });
