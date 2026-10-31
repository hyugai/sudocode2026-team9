import test from 'node:test';
import assert from 'node:assert/strict';
import { createPurchaseStore, quote, resolveItem, selection, stockFor, validateDelivery, parseCart, CART_KEY, SESSION_KEY } from '../utils/commerce.ts';
import { getProductDetails } from '../utils/catalog.ts';

const memory = () => { const data = new Map(); return { getItem: key => data.get(key) ?? null, setItem: (key,value) => data.set(key,value), removeItem: key => data.delete(key) }; };
const item = (productSku, quantity = 1, sku = productSku) => ({ productSku, sku, quantity });
const delivery = { name: 'Khách Demo', phone: '0901234567', address: '12 Đường Mẫu, phường Mẫu, quận Mẫu, Hà Nội', region: 'inner', payment: 'COD' };
const setup = (delay) => { const local=memory(), session=memory(); let count=0;const store=createPurchaseStore(()=>local,()=>session,()=>`test-${++count}`,delay || (()=>Promise.resolve()));store.hydrate();return { store,local,session }; };

test('Variant price deltas and inventory timeline override static parent/variant stock', () => {
  const product = getProductDetails('SKU-SN-RUN2');
  const variant = product.variants.find(v=>v.size===43);
  assert.equal(selection(product,variant.variant_sku).unitPrice, product.list_price_vnd+variant.price_delta_vnd);
  assert.equal(stockFor('SKU-SN-RUN2-41-DEN',999),3);
  assert.equal(stockFor('SKU-SN-RUN2-41-DEN',999,'2026-10-22'),0);
  assert.equal(stockFor('SKU-SN-RUN2-41-DEN',999,'2026-10-24'),12);
  assert.equal(resolveItem(item('SKU-MB-STR1')).stock,2);
  assert.throws(()=>selection(product, product.sku), /chọn/);
  assert.throws(()=>resolveItem(item('SKU-XM-4P')), /chỉ còn 0/);
  assert.throws(()=>resolveItem(item('SKU-AP-X-2024')), /chỉ còn 0/);
  for (const quantity of [0,-1,1.5,NaN,Infinity,41]) assert.throws(()=>resolveItem(item('SKU-AP-X',quantity)));
});

test('Snapshot totals use exact line quantities, base shipping, bulky surcharge and policy freeship', () => {
  let q=quote([item('SKU-AP-FLT-X')],'inner');
  assert.equal(q.shipping,25000);assert.equal(q.total,q.subtotal+25000);
  q=quote([item('SKU-AP-X',2)],'province');assert.equal(q.shipping,0);assert.equal(q.total,9780000);
  q=quote([item('SKU-WF-RO9')],'province');assert.equal(q.baseShipping,0);assert.equal(q.surcharge,30000);assert.equal(q.shipping,30000);
  assert.throws(()=>quote([item('SKU-WF-RO9')],'remote'), /cồng kềnh/);
  q=quote([item('SKU-MB-BAG',10)],'province');assert.equal(q.shipping,0);
  assert.throws(()=>quote([],'inner'),/trống/);
  assert.throws(()=>quote([item('SKU-AP-X'),item('SKU-AP-X')],'inner'),/không hợp lệ/);
});

test('Address/payment validation and COD policy boundary are enforced', () => {
  assert.deepEqual(validateDelivery(delivery,9999999),{});
  assert.ok(validateDelivery(delivery,10000000).payment);
  assert.ok(validateDelivery({...delivery,name:'',phone:'x',address:''},1).address);
  assert.deepEqual(validateDelivery({...delivery,payment:'bank'},20000000),{});
  assert.throws(()=>parseCart([{sku:'SKU-AP-X',productSku:'SKU-AP-X',quantity:'2'}]));
});

test('Cart merges, updates, removes and survives a new store; buy-now does not replace it', () => {
  const {store,local,session}=setup();
  store.add(item('SKU-AP-X'));store.add(item('SKU-AP-X'));assert.equal(store.getSnapshot().cart[0].quantity,2);
  store.update('SKU-AP-X',3);assert.equal(store.getSnapshot().cart[0].quantity,3);
  store.checkout('buy-now',item('SKU-AF-4L'));
  assert.equal(store.getSnapshot().cart[0].sku,'SKU-AP-X');assert.equal(store.getSnapshot().buyNow[0].sku,'SKU-AF-4L');
  const restored=createPurchaseStore(()=>local,()=>session);restored.hydrate();
  assert.deepEqual(restored.getSnapshot().cart,store.getSnapshot().cart);
  restored.remove('SKU-AP-X');assert.equal(restored.getSnapshot().cart.length,0);
});

test('Review requires valid data; explicit confirmation plus concurrent clicks creates one receipt and replay is idempotent', async () => {
  let release;const {store,local,session}=setup(()=>new Promise(r=>{release=r;}));
  store.add(item('SKU-AP-X'));store.checkout('cart');
  assert.throws(()=>store.review());store.setDelivery(delivery);store.review();
  await assert.rejects(store.submit(false), /xác nhận/);
  const first=store.submit(true),second=store.submit(true);assert.equal(first,second);assert.equal(store.getSnapshot().submitting,true);
  release();const [a,b]=await Promise.all([first,second]);assert.equal(a.id,b.id);assert.match(a.id,/^DEMO-/);assert.equal(a.paymentStatus,'unpaid');assert.equal(store.getSnapshot().orders.length,1);assert.equal(store.getSnapshot().cart.length,0);
  assert.equal((await store.submit(true)).id,a.id);
  const restored=createPurchaseStore(()=>local,()=>session);restored.hydrate();assert.equal((await restored.submit(true)).id,a.id);
});

test('Editing a reviewed order invalidates confirmation; demo failures preserve cart and never auto-retry', async () => {
  const {store}=setup();store.add(item('SKU-AP-X'));store.setDelivery(delivery);store.checkout('cart');store.review();store.update('SKU-AP-X',2);
  await assert.rejects(store.submit(true),/kiểm tra/);
  for(const scenario of ['order-failure','payment-failure','unavailable']){
    store.setDelivery({...delivery,payment:'bank'});store.setScenario(scenario);store.review();await assert.rejects(store.submit(true));
    assert.equal(store.getSnapshot().orders.length,0);assert.equal(store.getSnapshot().cart.length,1);assert.equal(store.getSnapshot().submitting,false);
  }
  store.setScenario('success');store.review();assert.match((await store.submit(true)).id,/^DEMO-/);
});

test('Storage failures do not announce an order or lose the cart; corrupted saved data can be reset', async () => {
  const {store,local,session}=setup();store.add(item('SKU-AP-X'));store.setDelivery(delivery);store.checkout('cart');store.review();
  const save=session.setItem;session.setItem=()=>{throw Error('quota');};await assert.rejects(store.submit(true),/lưu/);assert.equal(store.getSnapshot().orders.length,0);assert.equal(store.getSnapshot().cart.length,1);
  session.setItem=save;await store.submit(true);assert.equal(store.getSnapshot().orders.length,1);
  local.setItem(CART_KEY,'not-json');const corrupt=createPurchaseStore(()=>local,()=>session);corrupt.hydrate();assert.ok(corrupt.getSnapshot().error);corrupt.reset();assert.equal(local.getItem(CART_KEY),null);assert.equal(session.getItem(SESSION_KEY),null);
});

test('Form storage failure retains typed fields and cart persistence failure rolls session back', () => {
  const {store,local,session}=setup();store.add(item('SKU-AP-X'));
  const saveSession=session.setItem;session.setItem=()=>{throw Error('quota');};
  store.setDelivery({...delivery,name:'Nội dung vẫn được giữ'});
  assert.equal(store.getSnapshot().delivery.name,'Nội dung vẫn được giữ');assert.ok(store.getSnapshot().error);
  session.setItem=saveSession;store.setDelivery(delivery);
  const saved=session.getItem(SESSION_KEY),cart=local.getItem(CART_KEY),saveLocal=local.setItem;
  local.setItem=()=>{throw Error('quota');};assert.throws(()=>store.add(item('SKU-AF-4L')));
  assert.equal(store.getSnapshot().cart.length,1);assert.equal(session.getItem(SESSION_KEY),saved);assert.equal(local.getItem(CART_KEY),cart);local.setItem=saveLocal;
});

test('Shipping selection can be corrected at checkout instead of trapping a cart behind an unsupported region', () => {
  const {store}=setup();store.add(item('SKU-WF-RO9'));store.setDelivery({...delivery,region:'remote'});
  assert.doesNotThrow(()=>store.checkout('cart'));assert.throws(()=>store.review(),/cồng kềnh/);
  store.setDelivery({...delivery,region:'province'});assert.equal(store.review().quote.shipping,30000);
});

test('Different SKU lines remain distinct and failed over-stock merge leaves the cart intact', () => {
  const {store}=setup();store.add(item('SKU-AP-X'));store.add(item('SKU-AF-4L'));
  assert.equal(store.getSnapshot().cart.length,2);assert.equal(quote(store.getSnapshot().cart,'inner').total,6780000);
  assert.throws(()=>store.add(item('SKU-AF-4L',2)),/chỉ còn/);
  assert.equal(store.getSnapshot().cart.find(i=>i.sku==='SKU-AF-4L').quantity,1);
});
