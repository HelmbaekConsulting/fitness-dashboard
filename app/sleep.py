# Sleep timing for the Recovery page: when you fell asleep and woke up each night (Garmin's sleep window), the
# averages, how much the bedtime varies, and how much later weekend nights start.
import math
import statistics
from datetime import date, timedelta

from . import queries as q
from .today import short_date


def hhmm(h):
    m = round(h * 60) % (24 * 60)
    return f'{m // 60:02d}:{m % 60:02d}'


def _minutes(h):
    m = round(abs(h) * 60)
    return f'{m} min' if m < 60 else f'{m // 60} h {m % 60:02d} min'


def schedule(end, nights=30):
    """Bars from bedtime to wake time for the last `nights` nights, on a clock axis running down from the evening.
    Bedtimes after midnight are stored as 24 and up (garmin._clock), so the averages need no wrap-around."""
    start = end - timedelta(days=nights - 1)
    bed, wake, slept = (dict(q.daily(m, start, end)) for m in ('bedtime', 'waketime', 'sleep_h'))
    rows = [(d, bed[d], wake[d] + 24) for d in sorted(bed) if d in wake and wake[d] + 24 > bed[d]]
    if len(rows) < 5:
        return None
    lo = math.floor(min(b for _, b, _ in rows)) - 0.5
    hi = math.ceil(max(w for _, _, w in rows)) + 0.5
    span = hi - lo
    pos = lambda h: (h - lo) / span * 100
    by_day = {d: (b, w) for d, b, w in rows}
    cols = []
    for i in range(nights):
        d = (start + timedelta(days=i)).isoformat()
        if d not in by_day:
            cols.append({'empty': True, 'title': f'{short_date(d, True)}: no sleep recorded'})
            continue
        b, w = by_day[d]
        asleep = f', {slept[d]:.1f} h asleep' if d in slept else ''
        cols.append({'top': pos(b), 'height': pos(w) - pos(b), 'weekend': date.fromisoformat(d).weekday() >= 5,
                     'title': f'{short_date(d, True)}: {hhmm(b)}–{hhmm(w)}{asleep}'})
    first_tick = math.ceil(lo / 2) * 2
    ticks = [{'label': hhmm(h), 'pos': pos(h)} for h in range(first_tick, math.floor(hi) + 1, 2)]
    beds, wakes = [b for _, b, _ in rows], [w for _, _, w in rows]
    spread = statistics.pstdev(beds) * 60
    regular = 'very regular' if spread <= 30 else 'fairly regular' if spread <= 60 else 'irregular'
    weekend = [b for d, b, _ in rows if date.fromisoformat(d).weekday() >= 5]  # Saturday and Sunday mornings: Friday and Saturday nights
    weekday = [b for d, b, _ in rows if date.fromisoformat(d).weekday() < 5]
    stats = [
        {'label': 'Average bedtime', 'value': hhmm(statistics.mean(beds))},
        {'label': 'Average wake time', 'value': hhmm(statistics.mean(wakes))},
        {'label': 'Bedtime varies', 'value': f'±{spread:.0f} min', 'note': regular.capitalize()},
    ]
    text = f'Your bedtime is {regular}: it varies by about {spread:.0f} minutes from night to night.'
    if len(weekend) >= 2 and len(weekday) >= 3:
        shift = statistics.mean(weekend) - statistics.mean(weekday)
        stats.append({'label': 'Weekend nights', 'value': _minutes(shift),
                      'note': 'later than weekdays' if shift >= 0 else 'earlier than weekdays'})
        if abs(shift) >= 0.75:
            text += (f' Friday and Saturday nights start {_minutes(shift)} {"later" if shift > 0 else "earlier"} than weekdays, '
                     'a shift sleep researchers call social jet lag.')
    return {'cols': cols, 'ticks': ticks, 'avg_bed': pos(statistics.mean(beds)), 'avg_wake': pos(statistics.mean(wakes)),
            'stats': stats, 'text': text, 'nights': len(rows), 'from': short_date(start.isoformat()), 'to': short_date(end.isoformat())}
