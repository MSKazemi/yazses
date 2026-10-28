// Run: node --test examples/hci-hf-lab/ui.test.js
//
// Drives the real app.js against a small stub DOM, so a render that throws or prints a placeholder
// ("NaN", "undefined", "null") fails the build. The resolver tests cannot see this: they never render.
// It is not a browser: layout, CSS and real input events are out of scope.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const LAB = __dirname;

// min/max as written in index.html, so the stub behaves like the real inputs (an absent attribute is "").
function inputLimits() {
  const html = fs.readFileSync(path.join(LAB, "index.html"), "utf8");
  const limits = new Map();
  for (const tag of html.match(/<input\b[^>]*>/g) || []) {
    const id = (tag.match(/\bid="([^"]+)"/) || [])[1];
    if (!id) continue;
    limits.set(id, { min: (tag.match(/\bmin="([^"]*)"/) || [, ""])[1], max: (tag.match(/\bmax="([^"]*)"/) || [, ""])[1] });
  }
  return limits;
}

function makeDom() {
  const byId = new Map();
  const all = [];
  const limits = inputLimits();

  function makeElement(tag) {
    const handlers = {};
    let value = "";
    const el = {
      tagName: String(tag || "div").toUpperCase(),
      min: "",
      max: "",
      checked: false,
      hidden: false,
      textContent: "",
      className: "",
      id: "",
      style: {},
      dataset: {},
      children: [],
      attributes: {},
      classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
      appendChild(child) { this.children.push(child); return child; },
      replaceChildren() { this.children = []; },
      setAttribute(name, value) { this.attributes[name] = String(value); },
      removeAttribute(name) { delete this.attributes[name]; },
      addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
      querySelector() { return makeElement("div"); },
      querySelectorAll() { return []; },
      focus() {},
      handlers,
      fire(type, extra) {
        for (const fn of handlers[type] || []) fn(Object.assign({ target: el, preventDefault() {} }, extra));
      },
    };
    // A DOM value is always a string.
    Object.defineProperty(el, "value", { get() { return value; }, set(v) { value = v === null || v === undefined ? "" : String(v); } });
    Object.defineProperty(el, "options", { get() { return el.children; } });
    Object.defineProperty(el, "innerText", { get() { return el.textContent; } });
    all.push(el);
    return el;
  }

  const document = {
    getElementById(id) {
      if (!byId.has(id)) {
        const el = makeElement("div");
        el.id = id;
        Object.assign(el, limits.get(id) || {});
        byId.set(id, el);
      }
      return byId.get(id);
    },
    createElement: makeElement,
    createTextNode(text) { const n = makeElement("#text"); n.textContent = String(text); return n; },
    querySelector() { return makeElement("div"); },
    querySelectorAll() { return []; },
    addEventListener(type, fn) { (document.handlers[type] = document.handlers[type] || []).push(fn); },
    handlers: {},
  };
  return { document, byId, all };
}

// `mutate` may change the fixtures after they load and before the page starts.
function boot(mutate) {
  const dom = makeDom();
  const window = {};
  const context = vm.createContext({ window, document: dom.document, console });
  for (const file of ["fixtures.js", "resolver.js", "app.js"]) {
    if (file === "app.js" && mutate) mutate(window.HCI_FIXTURES);
    vm.runInContext(fs.readFileSync(path.join(LAB, file), "utf8"), context, { filename: file });
  }
  return { dom, window };
}

function textOf(node, out) {
  if (node && typeof node.textContent === "string") out.push(node.textContent);
  for (const child of (node && node.children) || []) textOf(child, out);
  return out;
}

function pageText(dom) {
  const out = [];
  for (const el of dom.byId.values()) textOf(el, out);
  return out.join("\n");
}

const CONTROLS = [
  "gaze-connected", "gaze-x", "gaze-y", "gaze-conf", "gaze-age", "voice-intent", "voice-conf", "voice-target",
  "act-kind", "act-conf", "act-age", "act-hold", "act-bounce", "act-bounce-gap",
];

test("every scenario loads, activates and re-renders without throwing or printing a placeholder", () => {
  const { dom, window } = boot();
  const $ = (id) => dom.document.getElementById(id);
  for (const sc of window.HCI_FIXTURES.scenarios) {
    $("scenario").value = sc.id;
    $("scenario").fire("change");
    $("btn-activate").fire("click");
    for (const id of CONTROLS) {
      $(id).fire("input");
      $(id).fire("change");
    }
    $("btn-activate").fire("click");
    const text = pageText(dom);
    const bad = text.match(/[^\n]*(NaN|undefined|\bnull\b)[^\n]*/);
    assert.equal(bad, null, `${sc.id} printed a placeholder: ${bad && bad[0].slice(0, 120)}`);
  }
});

test("an unknown confidence stays unknown until the slider moves, and never crashes the render", () => {
  const { dom } = boot();
  const $ = (id) => dom.document.getElementById(id);
  $("scenario").value = "sensor_disconnection";
  $("scenario").fire("change");
  assert.equal($("gaze-conf-out").textContent, "unknown");

  // Edit an unrelated control, then reconnect the sensor: the unknown must survive both.
  $("voice-conf").value = "0.75";
  $("voice-conf").fire("input");
  $("gaze-connected").checked = true;
  $("gaze-connected").fire("change");
  $("btn-activate").fire("click");
  assert.equal($("gaze-conf-out").textContent, "unknown");
  assert.match($("gaze-readout").textContent, /confidence unknown/);
  assert.match(pageText(dom), /Gaze confidence is unknown/);

  // Moving the slider is the user supplying a value.
  $("gaze-conf").value = "0.9";
  $("gaze-conf").fire("input");
  assert.equal($("gaze-conf-out").textContent, "0.90");
  assert.match($("gaze-readout").textContent, /confidence 0\.90/);
});

test("the same holds for an unknown activation confidence", () => {
  const { dom } = boot((fx) => {
    fx.scenarios.find((x) => x.id === "correct_target").inputs.activation.confidence = null;
  });
  const $ = (id) => dom.document.getElementById(id);
  $("scenario").value = "correct_target";
  $("scenario").fire("change");
  assert.equal($("act-conf-out").textContent, "unknown");
  $("gaze-age").value = "120";
  $("gaze-age").fire("input");
  $("btn-activate").fire("click");
  assert.equal($("act-conf-out").textContent, "unknown");
  assert.match(pageText(dom), /Activation confidence is unknown/);
  $("act-conf").value = "0.88";
  $("act-conf").fire("input");
  assert.equal($("act-conf-out").textContent, "0.88");
});

test("the desktop's accessible name lists every window the desktop has", () => {
  const { dom, window } = boot();
  const $ = (id) => dom.document.getElementById(id);
  $("scenario").value = "correct_target";
  $("scenario").fire("change");
  const label = $("desktop").attributes["aria-label"];
  for (const w of window.HCI_FIXTURES.desktop.windows) assert.ok(label.includes(w.label), `${w.label} missing from: ${label}`);
});

test("the emergency stop key reaches the resolver from the page", () => {
  const { dom } = boot();
  const $ = (id) => dom.document.getElementById(id);
  $("scenario").value = "correct_target";
  $("scenario").fire("change");
  for (const fn of dom.document.handlers.keydown || []) fn({ key: "Escape", preventDefault() {} });
  assert.match(pageText(dom), /stop/i);
});
