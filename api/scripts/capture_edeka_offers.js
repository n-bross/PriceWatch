// Evaluate in the normal T3 public browser on https://www.edeka.de/angebote/.
// Save the returned object as JSON for import_edeka_browser.py. No network calls.
(() => {
  if (location.origin !== "https://www.edeka.de" || location.pathname !== "/angebote/") {
    throw new Error("Expected official EDEKA offers page");
  }
  const text = (element) => element?.textContent.replace(/\s+/g, " ").trim() || "";
  const periods = [...new Set([...text(document.body).matchAll(
    /Gültig vom (\d{2}\.\d{2}\.\d{4}) bis zum (\d{2}\.\d{2}\.\d{4})/g,
  )].map((match) => match[0]))];
  if (periods.length !== 1) throw new Error("Expected one explicit validity period");
  const dates = periods[0].match(/\d{2}\.\d{2}\.\d{4}/g);
  const isoDate = (value) => value.split(".").reverse().join("-");
  const products = [...document.querySelectorAll('dialog[id^="dialog-angebot-"]')].map((dialog) => {
    const heading = dialog.querySelector("h3");
    if (!heading) throw new Error("Missing offer heading");
    const starts = [...new Set(text(dialog).match(/\bab \d{2}\.\d{2}\./g) || [])];
    if (starts.length > 1) throw new Error("Ambiguous offer start");
    return {
      id: dialog.id,
      name: text(heading).replace(/^Angebot:\s*/, ""),
      description: text(dialog.querySelector("p.line-clmap-2, p.line-clamp-2")) || null,
      terms: text(dialog.querySelector(".autoformat")),
      prices: [...dialog.querySelectorAll("span.sr-only")].map(text),
      start: starts[0] || null,
    };
  });
  if (!products.length) throw new Error("No public offer dialogs");
  return {
    observed_at: new Date().toISOString(),
    source_url: location.href,
    capture_method: "public_browser_dom",
    period_text: periods[0],
    valid_from: isoDate(dates[0]),
    valid_until: isoDate(dates[1]),
    products,
  };
})()
