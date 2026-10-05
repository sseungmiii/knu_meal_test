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
  const updated = data.updated_at ? new Date(data.updated_at.replace(' ', 'T') + '+09:00') : null;
  const stale = updated && Number.isFinite(updated.getTime()) && Date.now() - updated.getTime() > 8 * 86400000;
  const messages = [];
  if (data.crawl_status === 'failed') messages.push('식단 수집에 실패하여 이전 식단을 표시합니다.');
  if (stale) messages.push('식단 데이터가 8일 이상 갱신되지 않았습니다. 표시된 날짜를 확인해주세요.');
  if (data.notice && !messages.includes(data.notice)) messages.push(data.notice);
  const target = document.getElementById('noticeText') || banner;
  target.textContent = messages.join(' ');
  banner.style.display = messages.length ? 'block' : 'none';
}
