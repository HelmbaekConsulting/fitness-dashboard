# The body figure: front and back views as SVG, one shape per muscle, each also tagged with its Withings segment.
# Shapes are drawn for the viewer's left half and mirrored. In the front view the viewer's left is the person's right;
# in the back view it's the person's left.
from markupsafe import Markup, escape

# (muscle or None for neutral parts, body part for segments, shape). Shapes: ('p', path) or ('e', cx, cy, rx, ry).
FRONT = [
    (None, 'head', ('e', 100, 32, 16, 20)),
    (None, 'trunk', ('p', 'M93,51 L107,51 L109,64 L91,64 Z')),
    ('traps', 'trunk', ('p', 'M91,60 C86,65 78,68 69,70 L79,74 C85,72 90,69 93,66 Z')),
    ('side_delts', 'trunk', ('p', 'M64,71 C54,74 47,84 46,97 C46,104 47,109 49,113 C50,100 54,88 63,79 Z')),
    ('front_delts', 'trunk', ('p', 'M68,71 L79,76 C73,84 64,96 59,111 L54,114 C53,100 57,86 66,77 Z')),
    ('chest', 'trunk', ('p', 'M99,74 L82,76 C72,81 65,92 64,103 C66,114 75,119 87,119 C93,119 97,117 99,114 Z')),
    ('biceps', 'arm', ('p', 'M52,117 C45,128 43,143 44,157 C45,164 51,167 57,162 C62,150 64,134 63,121 C61,114 56,113 52,117 Z')),
    ('forearms', 'arm', ('p', 'M44,169 C39,184 35,200 33,215 C33,222 38,225 42,221 C49,205 55,188 58,173 C56,165 48,162 44,169 Z')),
    (None, 'arm', ('e', 37, 233, 6, 10)),
    ('abs', 'trunk', ('p', 'M88,123 L99,123 L99,141 L88,141 Q86,141 86,139 L86,125 Q86,123 88,123 Z')),
    ('abs', 'trunk', ('p', 'M88,144 L99,144 L99,163 L88,163 Q86,163 86,161 L86,146 Q86,144 88,144 Z')),
    ('abs', 'trunk', ('p', 'M88,166 L99,166 L99,186 L88,186 Q86,186 86,184 L86,168 Q86,166 88,166 Z')),
    ('abs', 'trunk', ('p', 'M88,189 L99,189 L99,212 Q93,212 88,208 Q86,206 86,203 L86,191 Q86,189 88,189 Z')),
    ('obliques', 'trunk', ('p', 'M84,123 L75,121 C71,140 71,168 75,193 C78,200 81,204 84,206 Z')),
    (None, 'trunk', ('p', 'M84,209 L75,199 C72,212 72,224 75,231 L98,236 L99,215 C93,215 88,213 84,209 Z')),
    ('quads', 'leg', ('p', 'M97,239 L75,234 C69,252 67,274 69,297 C71,311 77,318 85,318 C91,316 95,306 96,292 Z')),
    (None, 'leg', ('e', 84, 326, 8, 6)),
    ('calves', 'leg', ('p', 'M78,335 C74,351 74,372 78,392 L88,392 C92,372 93,352 90,335 C86,332 81,332 78,335 Z')),
    (None, 'leg', ('e', 83, 402, 10, 5)),
]

BACK = [
    (None, 'head', ('e', 100, 32, 16, 20)),
    (None, 'trunk', ('p', 'M93,51 L107,51 L109,62 L91,62 Z')),
    ('traps', 'trunk', ('p', 'M99,56 L92,57 C87,64 77,68 67,71 L81,81 C89,85 95,93 99,103 Z')),
    ('side_delts', 'trunk', ('p', 'M63,72 C54,75 47,85 46,98 C46,104 47,109 49,113 C50,100 54,88 62,80 Z')),
    ('rear_delts', 'trunk', ('p', 'M67,72 L79,80 C72,88 64,99 59,111 L54,114 C53,100 57,86 66,78 Z')),
    ('upper_back', 'trunk', ('p', 'M99,107 C95,96 88,88 80,85 C76,95 76,108 79,118 C86,124 93,130 99,134 Z')),
    ('lats', 'trunk', ('p', 'M77,121 C74,111 73,99 75,90 C67,98 63,114 64,130 C67,151 75,170 85,185 L93,183 C89,166 86,148 86,131 Z')),
    ('lower_back', 'trunk', ('p', 'M99,138 C95,136 91,134 89,134 C89,153 91,170 95,186 L99,190 Z')),
    ('triceps', 'arm', ('p', 'M52,117 C45,128 43,143 44,157 C45,164 51,167 57,162 C62,150 64,134 63,121 C61,114 56,113 52,117 Z')),
    ('forearms', 'arm', ('p', 'M44,169 C39,184 35,200 33,215 C33,222 38,225 42,221 C49,205 55,188 58,173 C56,165 48,162 44,169 Z')),
    (None, 'arm', ('e', 37, 233, 6, 10)),
    (None, 'trunk', ('p', 'M85,189 L75,183 C72,192 71,200 72,206 C80,200 90,198 99,199 L99,193 Z')),
    ('glutes', 'leg', ('p', 'M99,202 C90,200 79,202 73,209 C67,219 67,233 72,242 C80,250 91,250 99,246 Z')),
    ('hamstrings', 'leg', ('p', 'M97,252 L74,248 C70,264 69,284 71,302 C73,313 79,319 86,318 C92,314 96,302 97,288 Z')),
    (None, 'leg', ('e', 84, 326, 8, 6)),
    ('calves', 'leg', ('p', 'M77,333 C71,345 71,362 76,376 C80,385 87,385 90,376 C94,362 94,345 90,333 C86,329 80,329 77,333 Z')),
    (None, 'leg', ('p', 'M79,384 L88,384 L89,396 L79,396 Z')),
    (None, 'leg', ('e', 84, 402, 10, 5)),
]


def _shape(s, cls, title, attrs):
    t = f'<title>{escape(title)}</title>' if title else ''
    if s[0] == 'e':
        return f'<ellipse cx="{s[1]}" cy="{s[2]}" rx="{s[3]}" ry="{s[4]}" class="{cls}" {attrs}>{t}</ellipse>'
    return f'<path d="{s[1]}" class="{cls}" {attrs}>{t}</path>'


def svg(view, paint, label=''):
    """paint(muscle, segment) -> (css class, tooltip). segment is right_arm, left_leg, trunk, head ..."""
    shapes = FRONT if view == 'front' else BACK
    # Viewer's left half is the person's right in the front view, the person's left in the back view.
    near, far = ('right', 'left') if view == 'front' else ('left', 'right')
    halves = []
    for side, transform in ((near, ''), (far, 'transform="translate(200,0) scale(-1,1)"')):
        parts = []
        for muscle, part, s in shapes:
            if part in ('head',) and side == far:
                continue
            seg = part if part in ('trunk', 'head') else f'{side}_{part}'
            cls, title = paint(muscle, seg)
            attrs = f'data-seg="{seg}"' + (f' data-muscle="{muscle}"' if muscle else '')
            parts.append(_shape(s, cls, title, attrs))
        halves.append(f'<g {transform}>{"".join(parts)}</g>')
    side_l, side_r = ('Right', 'Left') if view == 'front' else ('Left', 'Right')
    return Markup(
        f'<svg class="body-fig" viewBox="0 0 200 420" role="img" aria-label="{escape(label or view)}">'
        f'{"".join(halves)}'
        f'<text x="8" y="414" class="fig-side">{side_l}</text><text x="192" y="414" class="fig-side" text-anchor="end">{side_r}</text>'
        f'<text x="100" y="414" class="fig-view" text-anchor="middle">{"Front" if view == "front" else "Back"}</text></svg>')
