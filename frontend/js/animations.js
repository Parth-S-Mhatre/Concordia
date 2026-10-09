// Concordia interactions — minimal, restrained. Reveal, counters, auth feedback.
// No tilt, no parallax, no shine. Respects prefers-reduced-motion.
(function () {
  'use strict';

  var reduce = function () {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  };

  // Scroll reveal — single observer, 12px rise, fires once.
  var revealObserver = null;
  function observeReveals(root) {
    var els = (root || document).querySelectorAll('[data-reveal]:not(.is-visible)');
    if (!els.length) return;
    if (reduce() || !('IntersectionObserver' in window)) {
      els.forEach(function (el) { el.classList.add('is-visible'); });
      return;
    }
    if (!revealObserver) {
      revealObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            revealObserver.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
    }
    els.forEach(function (el) { revealObserver.observe(el); });
  }

  // Counters — strip stats only, ease-out, tabular. Skips 0.
  function animateCount(el) {
    if (el.dataset.counted || reduce()) return;
    var m = String(el.textContent || '').match(/([\d,.]+)(\+?)/);
    if (!m) return;
    var target = parseFloat(m[1].replace(/,/g, ''));
    var suffix = m[2] || '';
    if (!(target > 0)) return;
    el.dataset.counted = '1';
    var t0 = null, dur = 800;
    function frame(ts) {
      if (!t0) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased).toLocaleString() + suffix;
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  function observeCounters() {
    var els = document.querySelectorAll('.strip-cell strong');
    if (!els.length || !('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { animateCount(entry.target); io.unobserve(entry.target); }
      });
    }, { threshold: 0.4 });
    els.forEach(function (el) { io.observe(el); });
  }

  // Auth — mode swap fade, error nudge, loading lock with timeout.
  function initAuthMotion() {
    var form = document.getElementById('auth-form');
    if (!form) return;
    ['tab-signin', 'tab-signup'].forEach(function (id) {
      var tab = document.getElementById(id);
      if (tab) tab.addEventListener('click', function () {
        ['auth-title', 'auth-subtitle'].forEach(function (eid) {
          var el = document.getElementById(eid);
          if (!el) return;
          el.classList.remove('mode-swap');
          void el.offsetWidth;
          el.classList.add('mode-swap');
        });
      });
    });
    var err = document.getElementById('auth-error');
    if (err && 'MutationObserver' in window) {
      new MutationObserver(function () {
        if (!err.hidden) {
          form.classList.remove('shake');
          void form.offsetWidth;
          form.classList.add('shake');
        }
      }).observe(err, { attributes: true, attributeFilter: ['hidden'] });
    }
    function lock(btn) {
      if (!btn) return;
      btn.classList.add('is-loading');
      setTimeout(function () { btn.classList.remove('is-loading'); }, 4000);
    }
    form.addEventListener('submit', function () { lock(document.getElementById('auth-submit')); });
    var g = document.getElementById('google-signin');
    if (g) g.addEventListener('click', function () { lock(g); });
    var gg = document.getElementById('google-signin-gate');
    if (gg) gg.addEventListener('click', function () { lock(gg); });
  }

  // Dashboard SPA — re-scan reveals after dynamic renders.
  function initDynamicRefresh() {
    if (!('MutationObserver' in window)) return;
    var deb = null;
    new MutationObserver(function () {
      if (deb) clearTimeout(deb);
      deb = setTimeout(function () { observeReveals(document); }, 80);
    }).observe(document.body, { childList: true, subtree: true });
  }

  function init() {
    observeReveals(document);
    observeCounters();
    initAuthMotion();
    initDynamicRefresh();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  window.ConcordiaAnimations = { refresh: function () { observeReveals(document); } };
})();
