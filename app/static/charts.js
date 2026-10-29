// Draws the page's charts from the JSON the server embeds. Days are x values in ms on a linear axis, so gaps in the
// data stay gaps and no date adapter is needed. Colours come from the CSS tokens, so dark mode follows the page.
(function () {
  const specs = JSON.parse(document.getElementById('chart-data').textContent);
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  const toMs = (iso) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
  const pad = (n) => String(n).padStart(2, '0');
  const dmy = (ms) => { const d = new Date(ms); return `${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)}/${d.getUTCFullYear()}`; };
  const short = (ms, span) => {
    const d = new Date(ms);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return span > 400 * 864e5 ? `${months[d.getUTCMonth()]} ${d.getUTCFullYear()}` : `${d.getUTCDate()} ${months[d.getUTCMonth()]}`;
  };
  const fmt = (x) => Math.abs(x) >= 1000 ? Math.round(x).toLocaleString('en-GB') : (Math.round(x * 10) / 10).toString();

  function alpha(hex, a) {
    if (!hex.startsWith('#')) return hex;
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = v('--muted');

  for (const spec of specs) {
    const el = document.getElementById('c-' + spec.id);
    if (!el) continue;
    const all = spec.series.flatMap((s) => s.data.map((p) => toMs(p[0])));
    const min = spec.xmin ? toMs(spec.xmin) : Math.min(...all), max = spec.xmax ? toMs(spec.xmax) : Math.max(...all), span = max - min;
    const isBar = spec.kind === 'bar';
    // Bars get a width in ms: a week for weekly totals, a day otherwise.
    const firstBar = spec.series.find((s) => s.style === 'bar' && s.data.length > 1);
    const step = firstBar ? toMs(firstBar.data[1][0]) - toMs(firstBar.data[0][0]) : 864e5;
    const datasets = spec.series.map((s) => {
      // slot: a categorical slot number, or a token name such as 'l3' for ordered ramps (HR zones).
      const color = v(typeof s.slot === 'number' ? '--s' + s.slot : '--' + s.slot);
      const base = { label: s.label, data: s.data.map((p) => ({ x: toMs(p[0]), y: p[1] })), borderColor: color, backgroundColor: color };
      // A band is two datasets: the low edge (invisible) and the high edge, filled down to it.
      if (s.style === 'band_lo' || s.style === 'band_hi') return { ...base, type: 'line', borderWidth: 0, pointRadius: 0,
        pointHoverRadius: 0, tension: 0.25, backgroundColor: alpha(color, 0.14), fill: s.style === 'band_hi' ? '-1' : false, order: 3 };
      if (s.style === 'dots') return { ...base, type: 'line', showLine: false, pointRadius: 2, pointHoverRadius: 5,
        backgroundColor: alpha(color, 0.35), borderColor: alpha(color, 0.35), order: 2 };
      if (s.style === 'bar') return { ...base, type: 'bar', borderRadius: 4, borderSkipped: 'start', borderWidth: 0,
        barThickness: 'flex', categoryPercentage: 1, barPercentage: 0.9, order: 1 };
      return { ...base, type: 'line', borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.25,
        pointHoverBorderColor: v('--surface'), pointHoverBorderWidth: 2, spanGaps: 10 * 864e5, order: 1 };
    });
    const visible = spec.series.filter((s) => s.legend !== false);
    new Chart(el, {
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, parsing: true,
        interaction: { mode: 'x', intersect: false },
        plugins: {
          legend: { display: visible.length > 1, position: 'top', align: 'start',
            labels: { usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 10, boxHeight: 10, color: v('--ink-2'),
              filter: (item) => spec.series[item.datasetIndex].legend !== false } },
          tooltip: {
            backgroundColor: v('--surface'), titleColor: v('--ink'), bodyColor: v('--ink-2'), borderColor: v('--border'),
            borderWidth: 1, padding: 10, usePointStyle: true, boxPadding: 4,
            filter: (item) => !String(spec.series[item.datasetIndex].style).startsWith('band'),
            callbacks: {
              title: (items) => items.length ? (step >= 6 * 864e5 && isBar ? 'Week of ' : '') + dmy(items[0].parsed.x) : '',
              label: (item) => ` ${item.dataset.label}: ${fmt(item.parsed.y)}${spec.unit ? ' ' + spec.unit : ''}`,
            },
          },
        },
        scales: {
          x: { type: 'linear', min: isBar && !spec.xmin ? min - step / 2 : min, max: isBar && !spec.xmax ? max + step / 2 : max, stacked: spec.stacked,
            grid: { display: false }, border: { color: v('--axis') },
            ticks: { maxTicksLimit: 6, maxRotation: 0, callback: (x) => short(x, span) } },
          y: { stacked: spec.stacked, beginAtZero: spec.zero, grid: { color: v('--grid') }, border: { display: false },
            ticks: { maxTicksLimit: 5, callback: (y) => fmt(y) } },
        },
      },
    });
  }
})();
