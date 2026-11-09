"use strict";
/* styxx-ledger: a reference writer and verifier for the styxx ledger protocol v1 (PROTOCOL_v1.md). */
const verify = require("./verify");
const ledger = require("./ledger");
const day = require("./day");
const ots = require("./ots");

module.exports = Object.assign({}, verify, {
  Ledger: ledger.Ledger, LedgerError: ledger.LedgerError, LedgerLocked: ledger.LedgerLocked, LedgerTamper: ledger.LedgerTamper,
  nowUtc: day.nowUtc, ots, version: ledger.VERSION
});
