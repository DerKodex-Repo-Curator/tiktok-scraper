// HTMX loader — loads HTMX from CDN if not vendored locally.
// This file exists so /static/js/htmx.js resolves without bundling the full
// library. For production, replace this with the vendored htmx.min.js.
(function () {
    if (window.htmx) return;
    var s = document.createElement("script");
    s.src = "https://unpkg.com/htmx.org@1.9.12";
    s.async = true;
    document.head.appendChild(s);
})();