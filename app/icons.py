# Line icons (24 × 24, stroked in the text colour) for the navigation, tiles and session lists. Use icon('name').
from markupsafe import Markup

PATHS = {
    'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
    'scale': '<rect x="3.5" y="3.5" width="17" height="17" rx="5"/><path d="M8 11a4 4 0 0 1 8 0M12 11l1.6-2.4"/>',
    'figure': '<circle cx="12" cy="4.8" r="2"/><path d="M5.5 9h13M12 9v5.5M12 14.5l-3 6.5M12 14.5l3 6.5"/>',
    'trend': '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
    'flame': '<path d="M12 3c.8 3.2 5 5.2 5 10a5 5 0 0 1-10 0c0-2.3 1.1-3.8 2.4-4.9.3 1.5 1 2.4 2 2.8-.2-2.8.2-5.3.6-7.9z"/>',
    'heart': '<path d="M12 20s-7.5-4.4-7.5-10.2A4.3 4.3 0 0 1 12 7a4.3 4.3 0 0 1 7.5 2.8C19.5 15.6 12 20 12 20z"/>',
    'utensils': '<path d="M7 3v18M4 3v5a3 3 0 0 0 6 0V3M17 21V3c-2.2 0-3.5 2.6-3.5 6 0 2.6 1.3 4 3.5 4"/>',
    'dumbbell': '<path d="M6.5 6.5v11M3.5 9v6M17.5 6.5v11M20.5 9v6M6.5 12h11"/>',
    'gear': '<circle cx="12" cy="12" r="3"/><path d="M12 2.5V5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
    'refresh': '<path d="M20 12a8 8 0 0 1-14.3 4.9M4 12a8 8 0 0 1 14.3-4.9M18.5 3.5v3.6h-3.6M5.5 20.5v-3.6h3.6"/>',
    'moon': '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    'pulse': '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    'steps': '<path d="M8.5 15.5c-1.6 0-2.6-1.5-2.6-3.8S6.9 6.5 8.5 6.5s2.6 2.4 2.6 5.2-1 3.8-2.6 3.8zM15.5 11.5c-1.6 0-2.6-1.5-2.6-3.8S13.9 2.5 15.5 2.5s2.6 2.4 2.6 5.2-1 3.8-2.6 3.8zM6.5 19.5h4M13.5 15.5h4"/>',
    'walk': '<circle cx="13" cy="4.5" r="1.8"/><path d="M10.5 21l1.8-5.5 2.7 2.5V21M8.5 12.5l1.5-4 3.5-.5 2 3.5 2.5 1M12.3 15.5l1.2-7"/>',
    'check': '<circle cx="12" cy="12" r="9"/><path d="M8.5 12.2l2.4 2.4 4.6-5"/>',
    'alert': '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.01"/>',
    'run': '<circle cx="14" cy="4.5" r="1.8"/><path d="M9.5 20.5l2.8-5.3 2.9 2.3v3.5M7 11.5l3.2-3 3.4.9 2.6 3.4M12.3 15.2l-1.1-6"/>',
    'flag': '<path d="M6 21V3.5M6 4h10.5l-2.2 3.8 2.2 3.7H6"/>',
    'bike': '<circle cx="6" cy="16" r="3.5"/><circle cx="18" cy="16" r="3.5"/><path d="M6 16l4-7h5l3 7M10 9l3 7M13.5 6H16"/>',
    'swim': '<path d="M3 17c1.5 0 1.5-1 3-1s1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1M8 13l3-5 4 3M15.5 7.5a1.8 1.8 0 1 0 0-.01"/>',
    'arrow': '<path d="M5 12h14M13 6l6 6-6 6"/>',
    'down': '<path d="M12 5v14M6.5 13.5 12 19l5.5-5.5"/>',
    'up': '<path d="M12 19V5M6.5 10.5 12 5l5.5 5.5"/>',
    'watch': '<rect x="6.5" y="6" width="11" height="12" rx="3"/><path d="M9 6l.7-3h4.6l.7 3M9 18l.7 3h4.6l.7-3M12 10v2.2l1.4 1"/>',
    'more': '<circle cx="6" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18" cy="12" r="1.3"/>',
    'users': '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.6 2.7-6 6-6s6 2.4 6 6M16 4.8a3.2 3.2 0 0 1 0 6.4M17.5 14.2c2.1.6 3.5 2.6 3.5 5.8"/>',
    'calendar': '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
}


def icon(name, size=18, stroke=1.75):
    return Markup(f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                  f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                  f'{PATHS.get(name, PATHS["pulse"])}</svg>')
