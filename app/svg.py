# Path builders for the small server-drawn graphics on Today: sparkline lines, bars and bands, and the readiness ring.
# Sparklines use a 200 × 44 box drawn with preserveAspectRatio="none", so they stretch to any tile width.
import math

W, H = 200, 44


def _f(v):
    return f'{v:.1f}'


def scale(d0, d1, r0, r1):
    span = (d1 - d0) or 1
    return lambda v: r0 + (v - d0) / span * (r1 - r0)


def line(points):
    return ' '.join(f'{"L" if i else "M"}{_f(x)} {_f(y)}' for i, (x, y) in enumerate(points))


def spark_line(values, lo=None, hi=None):
    """values: [(x 0..1, y)]; y is scaled into the box with a little room top and bottom."""
    ys = [y for _, y in values]
    lo = min(ys) if lo is None else lo
    hi = max(ys) if hi is None else hi
    sy = scale(lo, hi, H - 3, 3)
    return line((x * W, sy(y)) for x, y in values), sy


def spark_band(upper, lower, sy):
    """Closed area between two [(x 0..1, y)] edges, in the same y scale as the line."""
    top = line((x * W, sy(y)) for x, y in upper)
    back = ' '.join(f'L{_f(x * W)} {_f(sy(y))}' for x, y in reversed(lower))
    return f'{top} {back}Z' if upper and lower else ''


def spark_bars(values, top, gap=8):
    """One path per bar (None for a missing week), heights against `top`."""
    bw = W / max(1, len(values))
    out = []
    for i, v in enumerate(values):
        if v is None:
            out.append('')
            continue
        h = max(1.5, v / top * (H - 2)) if top else 1.5
        out.append(f'M{_f(i * bw + gap / 2)} {H}v{_f(-h)}h{_f(bw - gap)}v{_f(h)}z')
    return out


def level(v, top):
    """y of a horizontal reference line (such as the 7-hour sleep mark) in the bar scale."""
    return _f(H - v / top * (H - 2))


def arc(a1, a2, r=70, c=84):
    """Clockwise arc between two angles in degrees, 0 at three o'clock."""
    x1, y1 = c + r * math.cos(math.radians(a1)), c + r * math.sin(math.radians(a1))
    x2, y2 = c + r * math.cos(math.radians(a2)), c + r * math.sin(math.radians(a2))
    return f'M{_f(x1)} {_f(y1)}A{r} {r} 0 {1 if a2 - a1 > 180 else 0} 1 {_f(x2)} {_f(y2)}'


def ring(n, gap=20):
    """n equal segments starting at twelve o'clock, with a gap between them."""
    if n == 1:
        return [arc(-90 + gap / 2, 270 - gap / 2)]
    step = 360 / n
    return [arc(-90 + i * step + gap / 2, -90 + (i + 1) * step - gap / 2) for i in range(n)]
