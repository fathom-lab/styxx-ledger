"use strict";
/* styxx-ledger: a reference writer and verifier for the styxx ledger protocol v1 (PROTOCOL_v1.md); v0 reads
   protocol v0 ledgers (darkflobi.gate/log/v0); ots reads OpenTimestamps proofs natively (no dependency); exhibit re-derives a published exhibit by url. */
const verify = require("./verify");
const ledger = require("./ledger");
const day = require("./day");
const ots = require("./ots");
const v0 = require("./v0");
const exhibit = require("./exhibit");

module.exports = Object.assign({}, verify, {
  v0, verifyBytesV0: v0.verifyBytesV0, parseAnchorTextV0: v0.parseAnchorTextV0, checkAnchorV0: v0.checkAnchorV0,
  anchorTextV0: v0.anchorTextV0, headerDigestV0: v0.headerDigestV0, detectProtocol: v0.detectProtocol, verifyAuto: v0.verifyAuto,
  Ledger: ledger.Ledger, LedgerError: ledger.LedgerError, LedgerLocked: ledger.LedgerLocked, LedgerTamper: ledger.LedgerTamper,
  nowUtc: day.nowUtc, ots, exhibit, runExhibit: exhibit.runExhibit, version: ledger.VERSION
});
