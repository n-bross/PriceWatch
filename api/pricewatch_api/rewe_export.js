/* Public REWE offer cards and JSON-LD only; no cookies or account data. */
(() => {
  'use strict';
  if (!['rewe.de', 'www.rewe.de'].includes(location.hostname)) {
    alert('Bitte zuerst die REWE-Seite mit dem ausgewählten Markt öffnen.');
    return;
  }
  const cents = text => {
    const amount = String(text || '').trim().replace(/\s*€$/, '').trim();
    if (!/^\d+(?:[.,]\d{1,2})?$/.test(amount)) return null;
    return Math.round(Number(amount.replace(',', '.')) * 100);
  };
  const collect = (doc = document) => {
    const products = new Map(), issues = [];
    const source = location.origin + location.pathname;
    const market = location.pathname.match(/\/angebote\/[^/]+\/(\d+)\//)?.[1] || null;
    for (const card of doc.querySelectorAll('article.cor-offer-renderer-tile')) {
      const title = card.querySelector('[data-offer-nan][data-offer-title]');
      const prices = card.querySelectorAll('.cor-offer-price__tag-price');
      const price = prices.length === 1 ? cents(prices[0].textContent) : null;
      if (!title || price === null) { issues.push('Angebotskarte ohne eindeutigen Preis'); continue; }
      const store = title.getAttribute('data-offer-wwident');
      if (market && store !== market) { issues.push('Abweichender Markt'); continue; }
      const name = title.getAttribute('data-offer-title');
      const week = title.getAttribute('data-offer-week');
      const bonus = card.querySelector('.cor-loyalty-badge');
      const bonusMatch = title.getAttribute('aria-label')?.match(/\+\s*(\d+[,.]\d{2})\s*€\s*REWE Bonus Guthaben/);
      const bonusCredit = bonusMatch ? cents(bonusMatch[1]) : null;
      const bonusPercent = title.getAttribute('aria-label')?.match(/\+\s*(\d+(?:[,.]\d+)?)%\s*REWE Bonus Guthaben/);
      const label = card.querySelector('.cor-offer-price__tag-label')?.textContent.trim() || '';
      const details = [...card.querySelectorAll('.cor-offer-information__additional')]
        .map(node => node.textContent.trim()).join(' ').replace(/\s+/g, ' ').slice(0,300);
      let validFrom = null, validUntil = null;
      // Only an explicit selected week date range; the week number supplies the year.
      const dates = doc.querySelector('[role="tab"][aria-selected="true"] .sos-week-tabs__tab-subtitle')
        ?.textContent.match(/^(\d{1,2})\.(\d{1,2})\.\s*bis\s*(\d{1,2})\.(\d{1,2})\.$/);
      if (dates && /^\d{4}\/\d{2}$/.test(week || '')) {
        const year = Number(week.slice(0,4));
        const startYear = year - (week.endsWith('/01') && Number(dates[2]) === 12 ? 1 : 0);
        const iso = (d,m,y) => `${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        validFrom = iso(dates[1],dates[2],startYear);
        validUntil = iso(dates[3],dates[4],startYear + (Number(dates[4]) < Number(dates[2]) ? 1 : 0));
      }
      const product = {source_product_id:title.getAttribute('data-offer-nan'), name,
        price_cents:price, source_url:source, kind:'offer', ean:null, brand:null,
        package_label:details || null, requires_membership:['Aktion','Knaller'].includes(label) || /^UVP \d/.test(label) ? false : null,
        valid_from:validFrom, valid_until:validUntil, bonus_credit_cents:bonusCredit,
        bonus_credit_percent:bonusPercent ? Number(bonusPercent[1].replace(',','.')) : null,
        conditions_text:bonus ? title.getAttribute('aria-label').slice(0,1000) : null,
        source_store_id:store, source_offer_week:week};
      products.set(JSON.stringify([store, week, product.source_product_id, name, price]), product);
    }
    const walk = node => {
      if (!node || typeof node !== 'object') return;
      const types = Array.isArray(node['@type']) ? node['@type'] : [node['@type']];
      if (types.includes('Product') && typeof node.name === 'string') {
        const offers = Array.isArray(node.offers) ? node.offers : [node.offers];
        for (const offer of offers) {
          if (!offer || offer.priceCurrency !== 'EUR') continue;
          const price = cents(offer.price);
          if (price === null) continue;
          let url;
          try { url = new URL(offer.url || node.url || source, source); } catch (_) { continue; }
          if (url.protocol !== 'https:' || !['rewe.de','www.rewe.de'].includes(url.hostname)) continue;
          url.search = ''; url.hash = '';
          const id = String(node.sku || node.productID || (node.url ? url.href : '')).trim();
          if (!id || id.length > 300) continue;
          const codes = [...new Set([node.gtin8,node.gtin13,node.gtin14,node.gtin].filter(Boolean).map(String))];
          products.set(id + ':' + price, {source_product_id:id, name:node.name,
            price_cents:price, source_url:url.href, kind:'unknown', requires_membership:null,
            ean:codes.length === 1 ? codes[0] : null,
            brand:typeof node.brand === 'string' ? node.brand : node.brand?.name || null,
            package_label:null,
            valid_from:/^\d{4}-\d{2}-\d{2}/.test(offer.validFrom || '') ? offer.validFrom.slice(0,10) : null,
            valid_until:/^\d{4}-\d{2}-\d{2}/.test(offer.validThrough || node.priceValidUntil || '')
              ? (offer.validThrough || node.priceValidUntil).slice(0,10) : null});
        }
      }
      for (const value of Object.values(node)) if (typeof value === 'object') walk(value);
    };
    for (const script of doc.querySelectorAll('script[type="application/ld+json"]')) {
      try { walk(JSON.parse(script.textContent)); } catch (_) { /* malformed metadata */ }
    }
    return {captured_at:new Date().toISOString(), source_page:source, store_id:market,
      products:[...products.values()], pending_cards:doc.querySelectorAll('.sos-offer__skeleton').length, issues};
  };
  let cursor = 0;
  const loadMore = async (steps = 20) => {
    // Visiting each public card triggers REWE's own lazy loader, without private endpoints.
    const cards = [...document.querySelectorAll('.sos-offer')];
    for (let step = 0; step < Math.min(steps,40) && cursor < cards.length; step++,cursor++) {
      const card = cards[cursor];
      if (!card.querySelector('.sos-offer__skeleton')) continue;
      card.scrollIntoView({block:'center'});
      await new Promise(resolve => setTimeout(resolve,400));
    }
    const result = collect();
    return {visited:cursor, total_cards:cards.length, products:result.products.length,
      pending_cards:result.pending_cards, finished:cursor >= cards.length};
  };
  window.PriceWatchReweExporter = {collect,loadMore};
  if (window.__pricewatchCollectOnly) return;
  (async () => {
    const before = {x:scrollX,y:scrollY};
    try {
      let progress;
      do { progress = await loadMore(20); } while (!progress.finished);
      const payload = collect();
      if (!payload.products.length) {
        alert('Keine eindeutig lesbaren REWE-Produktpreise gefunden. Bitte eine Angebots- oder Produktseite öffnen.');
        return;
      }
      if (payload.pending_cards || payload.issues.length)
        alert(`Export enthält ${payload.products.length} Preise; ${payload.pending_cards} Karten noch ungeladen und ${payload.issues.length} Karten nicht eindeutig. Der Export ist unvollständig.`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = 'rewe-preise.json'; link.click();
      setTimeout(() => URL.revokeObjectURL(url),1000);
    } finally { scrollTo(before.x,before.y); }
  })().catch(error => alert('REWE-Export fehlgeschlagen: ' + error.message));
})();
