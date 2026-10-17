import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { normalizeDueDate, toRfc3339 } from "./Tasks.js";

describe("normalizeDueDate", () => {
  it("returns undefined for empty input", () => {
    assert.equal(normalizeDueDate(undefined), undefined);
    assert.equal(normalizeDueDate(""), undefined);
  });

  it("normalizes date-only strings to midnight UTC", () => {
    assert.equal(normalizeDueDate("2026-07-20"), "2026-07-20T00:00:00.000Z");
  });

  it("normalizes datetime strings using the UTC calendar day", () => {
    assert.equal(
      normalizeDueDate("2026-07-20T21:30:00Z"),
      "2026-07-20T00:00:00.000Z"
    );
  });

  it("rejects invalid dates", () => {
    assert.throws(() => normalizeDueDate("not-a-date"), /Invalid due date/);
  });
});

describe("toRfc3339", () => {
  it("returns undefined for empty input", () => {
    assert.equal(toRfc3339(undefined), undefined);
    assert.equal(toRfc3339(""), undefined);
  });

  it("treats date-only strings as midnight UTC", () => {
    assert.equal(toRfc3339("2026-10-10"), "2026-10-10T00:00:00.000Z");
  });

  it("keeps the instant of datetime strings", () => {
    assert.equal(
      toRfc3339("2026-10-10T09:30:00+09:00"),
      "2026-10-10T00:30:00.000Z"
    );
  });

  it("rejects invalid dates", () => {
    assert.throws(() => toRfc3339("nope"), /Invalid date/);
  });
});
