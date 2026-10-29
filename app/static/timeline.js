// Month slider for "Training vs body": swaps the colour class of every muscle and segment shape to that month's
// values. Frames come from the server; each holds [css class, tooltip] per muscle and per segment.
(function () {
  const frames = JSON.parse(document.getElementById('frames').textContent);
  const slider = document.getElementById('tl-slider');
  const label = document.getElementById('tl-month');
  const play = document.getElementById('tl-play');
  const panels = document.querySelectorAll('.panel');
  const levels = ['l1', 'l2', 'l3', 'l4', 'l5', 'l6', 'dn3', 'dn2', 'dn1', 'd0', 'dp1', 'dp2', 'dp3'];
  let timer = null;

  function paint(el, entry) {
    el.classList.remove(...levels);
    if (entry && entry[0]) el.classList.add(entry[0]);
    let t = el.querySelector('title');
    if (!t) { t = document.createElementNS('http://www.w3.org/2000/svg', 'title'); el.appendChild(t); }
    t.textContent = entry ? entry[1] : '';
  }

  function show(i) {
    const f = frames[i];
    label.textContent = f.month;
    // First panel: muscles by sets/week; second: segments by change in muscle mass.
    panels[0]?.querySelectorAll('[data-muscle]').forEach((el) => paint(el, f.muscles[el.dataset.muscle]));
    panels[1]?.querySelectorAll('[data-seg]').forEach((el) => {
      if (el.dataset.seg !== 'head') paint(el, f.segments[el.dataset.seg]);
    });
  }

  function stop() { clearInterval(timer); timer = null; play.textContent = '▶ Play'; }

  slider.addEventListener('input', () => { stop(); show(+slider.value); });
  play.addEventListener('click', () => {
    if (timer) return stop();
    if (+slider.value >= frames.length - 1) slider.value = 0;
    play.textContent = '❚❚ Pause';
    show(+slider.value);
    timer = setInterval(() => {
      if (+slider.value >= frames.length - 1) return stop();
      slider.value = +slider.value + 1;
      show(+slider.value);
    }, 900);
  });
})();
