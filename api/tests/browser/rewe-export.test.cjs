const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const {parseHTML} = require('linkedom');
const script = readFileSync(new URL('../../pricewatch_api/rewe_export.js', 'file://' + __filename),'utf8');
const fixture = readFileSync(new URL('../fixtures/rewe-offer-cards.html', 'file://' + __filename),'utf8');
function capture(html) {
  const {document} = parseHTML(html);
  const window = {__pricewatchCollectOnly:true};
  runInNewContext(script,{document,window,location:{hostname:'www.rewe.de',origin:'https://www.rewe.de',pathname:'/angebote/grafing/461766/rewe-leonhardstr-5-a/'},URL,Date,Map,Set});
  return JSON.parse(JSON.stringify(window.PriceWatchReweExporter.collect()));
}
test('real REWE cards: purchase price, bonus credit, IDs and explicit week dates', () => {
  const data = capture('<button role="tab" aria-selected="true"><span class="sos-week-tabs__tab-subtitle">28.9. bis 4.10.</span></button>'+fixture);
  assert.equal(data.products.length,4);
  assert.deepEqual(data.products.map(p=>p.price_cents),[1399,699,149,249]);
  assert.equal(data.products[3].bonus_credit_cents,20);
  assert.equal(data.products[3].requires_membership,false);
  assert.ok(data.products.every(p=>p.ean===null && p.source_store_id==='461766'));
  assert.equal(data.products[0].valid_from,'2026-09-28');
  assert.equal(data.products[0].valid_until,'2026-10-04');
});
test('duplicate cards deduplicate; missing dates remain unknown', () => {
  const data = capture(fixture+fixture);
  assert.equal(data.products.length,4);
  assert.equal(data.products[0].valid_until,null);
});
test('ambiguous or foreign-market cards are skipped, never guessed', () => {
  const data = capture(fixture.replace('13,99 €','nicht verfügbar').replaceAll('461766','999999'));
  assert.equal(data.products.length,0);
  assert.equal(data.issues.length,4);
});
test('JSON-LD product pages still work; organizations are not prices', () => {
  const data = capture('<script type="application/ld+json">'+JSON.stringify([
    {'@type':'Organization',name:'REWE'},
    {'@type':'Product',name:'Test',sku:'123',gtin13:'4006381333931',offers:{price:'1.29',priceCurrency:'EUR'}}
  ])+'</script>');
  assert.equal(data.products.length,1);
  assert.equal(data.products[0].price_cents,129);
  assert.equal(data.products[0].ean,'4006381333931');
});
test('ISO week year does not shift a December/January offer range by a year', () => {
  const data=capture('<button role="tab" aria-selected="true"><span class="sos-week-tabs__tab-subtitle">29.12. bis 4.1.</span></button>'+fixture.replaceAll('2026/40','2026/01'));
  assert.equal(data.products[0].valid_from,'2025-12-29');
  assert.equal(data.products[0].valid_until,'2026-01-04');
});
