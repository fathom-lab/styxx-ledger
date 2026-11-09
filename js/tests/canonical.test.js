"use strict";
/* unit: the canonical form (section 2) and the day arithmetic (section 1). */
const test = require("node:test");
const assert = require("node:assert/strict");
const { jcs, dump, LedgerValueError } = require("../lib/jcs");
const { dayOf, parseTimestamp, checkZone, nextDay } = require("../lib/day");

const code = fn => { try { fn(); return null; } catch (e) { return e instanceof LedgerValueError ? e.code : "uncoded:" + e.message; } };

test("dump: compact, keys by code unit, raw utf-8, json short escapes", () => {
  assert.equal(jcs({ b: 1, a: [true, null, "x"], A: {} }), '{"A":{},"a":[true,null,"x"],"b":1}');
  assert.equal(jcs({ s: "é☕🙂 \u007f" }), '{"s":"é☕🙂 \u007f"}');
  assert.equal(jcs("\b\f\n\r\t\u0001\u001f\"\\"), '"\\b\\f\\n\\r\\t\\u0001\\u001f\\"\\\\"');
  assert.equal(jcs([9007199254740992, -9007199254740992, 0]), "[9007199254740992,-9007199254740992,0]");
  assert.equal(jcs({ "~": 1, "": 2, "_": 3, "Z": 4 }), '{"":2,"Z":4,"_":3,"~":1}');
  assert.equal(jcs([]), "[]");
  assert.equal(jcs({}), "{}");
});

test("jcs refusals carry the protocol's codes", () => {
  assert.equal(code(() => jcs({ x: 1.5 })), "float");
  assert.equal(code(() => jcs({ x: NaN })), "float");
  assert.equal(code(() => jcs({ x: Infinity })), "float");
  assert.equal(code(() => jcs({ x: 9007199254740994 })), "int_range");
  assert.equal(code(() => jcs({ x: -9007199254740994 })), "int_range");
  assert.equal(code(() => jcs({ "é": 1 })), "non_ascii_key");
  assert.equal(code(() => jcs({ "\u007f": 1 })), "non_ascii_key");
  assert.equal(code(() => jcs({ x: "a\ud800b" })), "lone_surrogate");
  assert.equal(code(() => jcs({ x: "\udc00" })), "lone_surrogate");
  assert.equal(code(() => jcs({ x: 1n })), "type");
  assert.equal(code(() => jcs({ x: undefined })), "type");
  assert.equal(code(() => jcs({ x: new Date(0) })), "type");
  assert.equal(code(() => jcs({ x: new Map() })), "type");
  assert.equal(code(() => jcs({ x: () => 1 })), "type");
  assert.equal(code(() => jcs({ x: "🙂" })), null, "a paired surrogate is a character, not a refusal");
});

test("a key named __proto__ is an ordinary key", () => {
  const o = JSON.parse('{"__proto__":{"a":1},"b":2}');
  assert.equal(dump(o), '{"__proto__":{"a":1},"b":2}');
});

test("dayOf: america/new_york across the 2026-11-01 dst end", () => {
  const ny = "America/New_York";
  assert.equal(dayOf("2026-11-01T03:59:59Z", ny), "2026-10-31");
  assert.equal(dayOf("2026-11-01T04:00:00Z", ny), "2026-11-01");
  assert.equal(dayOf("2026-11-01T05:59:59Z", ny), "2026-11-01");
  assert.equal(dayOf("2026-11-01T06:00:00Z", ny), "2026-11-01");
  assert.equal(dayOf("2026-11-02T04:59:59Z", ny), "2026-11-01");
  assert.equal(dayOf("2026-11-02T05:00:00Z", ny), "2026-11-02");
  assert.equal(dayOf("2027-01-01T04:59:59Z", ny), "2026-12-31");
  assert.equal(dayOf("2027-01-01T05:00:00Z", ny), "2027-01-01");
  assert.equal(dayOf("2026-10-24T22:00:00Z", "Europe/Berlin"), "2026-10-25");
  assert.equal(dayOf("2026-12-31T23:59:59Z", "UTC"), "2026-12-31");
  assert.throws(() => dayOf("0099-06-01T12:00:00Z", "UTC"), e => e.code === "timestamp", "years run 1000..9998 since the fix pass (finding 2)");
  assert.equal(dayOf("1000-06-01T12:00:00Z", "UTC"), "1000-06-01");
});

test("timestamps: exactly YYYY-MM-DDTHH:MM:SSZ naming a real instant", () => {
  for (const bad of ["2026-11-01T01:00:00-04:00", "2026-11-01T05:00:00.5Z", "2026-02-30T00:00:00Z", "2026-11-01T24:00:00Z",
    "2026-12-31T23:59:60Z", "2026-13-01T00:00:00Z", "0000-01-01T00:00:00Z", "2026-11-01T05:00:00Z\n", " 2026-11-01T05:00:00Z",
    "2026-11-01 05:00:00Z", "", null, 1762000000]) {
    assert.equal(code(() => parseTimestamp(bad)), "timestamp", JSON.stringify(bad));
  }
  assert.equal(code(() => dayOf("bad", "Nowhere/Zone")), "timestamp", "the timestamp is checked before the zone");
});

test("zones: the platform's database, no fallback, no case variants, no offsets", () => {
  assert.equal(checkZone("America/New_York"), "America/New_York");
  assert.equal(checkZone("UTC"), "UTC");
  for (const bad of ["Nowhere/Zone", "utc", "america/new_york", "+01:00", "-05:00", "", "/etc/localtime", "../UTC", null, 5]) {
    assert.equal(code(() => checkZone(bad)), "anchor_tz", JSON.stringify(bad));
  }
  assert.equal(code(() => dayOf("2026-11-01T05:00:00Z", "Nowhere/Zone")), "anchor_tz");
});

test("nextDay crosses month and year ends", () => {
  assert.equal(nextDay("2026-10-31"), "2026-11-01");
  assert.equal(nextDay("2026-12-31"), "2027-01-01");
  assert.equal(nextDay("2028-02-28"), "2028-02-29");
});
