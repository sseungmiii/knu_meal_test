const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('meal-status.js', 'utf8'), context);
const now = new Date('2026-10-23T03:00:00Z');
const data = {
  updated_at: '2026-10-22 09:00:00', last_checked: '2026-10-23 09:00:00',
  crawl_status: 'success', days: ['금(10/23)'], shops: ['A'],
  data: { A: { '금(10/23)': { '중식': { items: ['비빔밥'] } } } }
};
const messages = value => context.menuStatusMessages(value, now).join(' ');
assert.equal(messages(data), '');
assert.match(messages({...data, crawl_status: 'partial', shop_status: {A: {status: 'failed'}}}), /확인 필요 식당: A/);
assert.match(messages({...data, last_checked: '2026-10-21 09:00:00'}), /30시간/);
assert.match(messages({...data, last_checked: 'invalid'}), /최근 점검/);
assert.match(messages({...data, days: ['월(10/19)']}), /오늘 날짜가/);
assert.match(messages({...data, data: {A: {}}}), /오늘 식단 미등록: A/);
assert.equal(context.currentMenuDay(new Date('2026-10-22T15:01:00Z')), '금(10/23)');
assert.equal(context.menuStatusMessages({...data, days: ['월(10/26)'], is_next_week: true,
  last_checked: '2026-10-25 09:00:00'}, new Date('2026-10-25T03:00:00Z')).join(' '), '');
console.log('8 status/date checks passed');
