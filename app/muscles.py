# Muscle groups for the body figures, and which muscles an exercise trains. Exercises are matched by name, first rule
# wins; primary muscles count a full set, secondary ones half a set (the usual "fractional sets" convention).
import re

# id: (label, Withings segment it sits in). Segment edges are approximate: Withings' arm segment is the limb, so
# shoulders and back count as trunk, glutes as legs.
MUSCLES = {
    'chest': ('Chest', 'trunk'),
    'front_delts': ('Front shoulders', 'trunk'),
    'side_delts': ('Side shoulders', 'trunk'),
    'rear_delts': ('Rear shoulders', 'trunk'),
    'traps': ('Traps', 'trunk'),
    'upper_back': ('Upper back', 'trunk'),
    'lats': ('Lats', 'trunk'),
    'lower_back': ('Lower back', 'trunk'),
    'abs': ('Abs', 'trunk'),
    'obliques': ('Obliques', 'trunk'),
    'biceps': ('Biceps', 'arms'),
    'triceps': ('Triceps', 'arms'),
    'forearms': ('Forearms', 'arms'),
    'glutes': ('Glutes', 'legs'),
    'quads': ('Quads', 'legs'),
    'hamstrings': ('Hamstrings', 'legs'),
    'calves': ('Calves', 'legs'),
}
SEGMENTS = {'arms': 'Arms', 'trunk': 'Trunk', 'legs': 'Legs'}

CARDIO = 'cardio'
RULES = [
    (r'treadmill|running|^rowing$|cycling|elliptical', CARDIO, ''),
    (r'calf|calves', 'calves', ''),
    (r'face pull', 'rear_delts', 'traps upper_back'),
    (r'reverse fl(y|ie)|rear delt|rear lateral', 'rear_delts', 'upper_back traps'),
    (r'lateral raise|upright row', 'side_delts', 'traps'),
    (r'front (two )?raise', 'front_delts', 'side_delts'),
    (r'shoulder press|military press|overhead press|standing dumbbell press|arnold', 'front_delts', 'side_delts triceps'),
    (r'shrug', 'traps', ''),
    (r'straight arm push|shoulder extension|pullover', 'lats', 'triceps'),
    (r'pull ?-? ?down|pull ?-? ?ups?|chin ?-? ?ups?', 'lats', 'biceps upper_back'),
    (r'\brows?\b|iso row|rowing', 'upper_back lats', 'biceps rear_delts'),
    (r'romanian deadlift|stiff.?leg', 'hamstrings', 'glutes lower_back'),
    (r'deadlift', 'hamstrings glutes lower_back', 'quads traps forearms'),
    (r'back extension|hyperextension|good morning', 'lower_back', 'glutes hamstrings'),
    (r'glute bridge|hip thrust|\bbridge\b|glute kick', 'glutes', 'hamstrings'),
    (r'lunge|split squat|step ?up', 'quads glutes', 'hamstrings'),
    (r'squat', 'quads glutes', 'hamstrings lower_back'),
    (r'leg press|hack', 'quads glutes', 'hamstrings'),
    (r'leg extension', 'quads', ''),
    (r'leg curl|hamstring curl', 'hamstrings', 'calves'),
    (r'wrist curl|reverse (barbell |ez bar )?curl|reverse grip curl', 'forearms', 'biceps'),
    (r'hammer curl', 'biceps forearms', ''),
    (r'tricep|french press|push ?down|kickback|skull|close grip bench', 'triceps', ''),
    (r'curl', 'biceps', 'forearms'),
    (r'\bdips?\b', 'chest triceps', 'front_delts'),
    (r'fly|flye|crossover|pec deck', 'chest', 'front_delts'),
    (r'bench press|chest press|push ?-? ?ups?', 'chest', 'triceps front_delts'),
    (r'oblique|cross body|russian twist|wood ?chop|side plank|side bend', 'obliques', 'abs'),
    (r'crunch|sit ?-? ?ups?|plank|leg raise|\bab\b|abdominal|air bike|v-?up|hollow', 'abs', 'obliques'),
]
_COMPILED = [(re.compile(p, re.I), prim.split(), sec.split()) for p, prim, sec in RULES]


def for_exercise(name):
    """(primary muscles, secondary muscles); ([], []) when not recognised, (['cardio'], []) for cardio."""
    for rx, prim, sec in _COMPILED:
        if rx.search(name or ''):
            return prim, sec
    return [], []


def weights(name):
    """{muscle: sets credited per set of this exercise}."""
    prim, sec = for_exercise(name)
    out = {m: 0.5 for m in sec if m in MUSCLES}
    out.update({m: 1.0 for m in prim if m in MUSCLES})
    return out
