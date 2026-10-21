/* Accessible names for two Material for MkDocs regions that ship without one.
 *
 * Lighthouse (2026-10-21) flagged every page: the search overlay is role="dialog" and
 * the instant-navigation bar is role="progressbar", and neither has an accessible
 * name, so a screen reader announces only "dialog" or "progress bar". Overriding the
 * theme's partials would mean copying whole templates that change on every Material
 * release; naming the two existing elements is the smaller, safer change.
 * First-party only: no network request is made from here.
 */
(function () {
  "use strict";
  function name() {
    var search = document.querySelector('[data-md-component="search"][role="dialog"]');
    if (search && !search.hasAttribute("aria-label")) search.setAttribute("aria-label", "Search the documentation");
    var progress = document.querySelector('[data-md-component="progress"][role="progressbar"]');
    if (progress && !progress.hasAttribute("aria-label")) progress.setAttribute("aria-label", "Page loading");
  }
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(name);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", name);
  } else {
    name();
  }
})();
