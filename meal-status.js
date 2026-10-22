function sortedShopsForMenu(shops, data, day, meal) {
  const meals = meal === 'ALL' ? ['조식', '중식', '석식'] : [meal];
  const hasMenu = shop => meals.some(type =>
    (data[shop]?.[day]?.[type]?.items?.length || 0) > 0);
  // Stable sort preserves the original order within each group; keep all cards.
  return [...shops].sort((a, b) => Number(hasMenu(b)) - Number(hasMenu(a)));
}

function currentMenuDay(now = new Date()) {
  const kst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const weekday = ['일', '월', '화', '수', '목', '금', '토'][kst.getUTCDay()];
  const month = String(kst.getUTCMonth() + 1).padStart(2, '0');
  const day = String(kst.getUTCDate()).padStart(2, '0');
  return `${weekday}(${month}/${day})`;
}

function showMenuStatus(data) {
  document.getElementById('updatedAt').textContent =
    `식단 갱신: ${data.updated_at || '정보 없음'} · 최근 점검: ${data.last_checked || '정보 없음'}`;
  let banner = document.getElementById('noticeBanner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'noticeBanner';
    banner.setAttribute('role', 'status');
    banner.style.cssText = 'padding:12px;margin:12px 0;background:#fff3cd;color:#664d03;border-radius:8px;';
    document.querySelector('header').after(banner);
  }
  const messages = menuStatusMessages(data);
  const target = document.getElementById('noticeText') || banner;
  target.textContent = messages.join(' ');
  banner.style.display = messages.length ? 'block' : 'none';
}

function menuStatusMessages(data, now = new Date()) {
  const parseStamp = value => value ? Date.parse(value.replace(' ', 'T') + '+09:00') : NaN;
  const messages = [];
  if (data.crawl_status === 'failed') messages.push('식단 수집에 실패하여 이전 식단을 표시합니다.');
  if (data.crawl_status === 'partial') messages.push('일부 식당 수집에 실패했습니다. 해당 식당은 이전 식단을 표시합니다.');
  const failed = Object.entries(data.shop_status || {}).filter(([, info]) => info.status === 'failed').map(([shop]) => shop);
  if (failed.length) messages.push(`확인 필요 식당: ${failed.join(', ')}`);
  const checked = parseStamp(data.last_checked);
  if (!Number.isFinite(checked) || checked > now.getTime() || now.getTime() - checked > 30 * 3600000) {
    messages.push('최근 점검이 없거나 30시간 이상 지났습니다. 자동 수집 상태를 확인해주세요.');
  }
  const updated = parseStamp(data.updated_at);
  if (!Number.isFinite(updated)) messages.push('식단 갱신 시각을 확인할 수 없습니다.');
  else if (now.getTime() - updated > 8 * 86400000) messages.push('식단 내용이 8일 이상 변경되지 않았습니다. 표시된 날짜를 확인해주세요.');
  const today = currentMenuDay(now);
  const normalize = day => day.replace(/\s/g, '');
  const nextWeekSunday = today.startsWith('일') && data.is_next_week;
  if (!(data.days || []).some(day => normalize(day) === today) && !nextWeekSunday) {
    messages.push('오늘 날짜가 식단에 없습니다. 휴무 또는 식단 등록 여부를 확인해주세요.');
  } else if (!nextWeekSunday) {
    const missing = (data.shops || []).filter(shop => {
      const weekly = data.data?.[shop] || {};
      const key = Object.keys(weekly).find(day => normalize(day) === today);
      return !Object.values(weekly[key] || {}).some(meal => meal.items?.length);
    });
    if (missing.length) messages.push(`오늘 식단 미등록: ${missing.join(', ')}. 휴무 여부를 확인해주세요.`);
  }
  if (data.notice && !messages.includes(data.notice)) messages.push(data.notice);
  return messages;
}
