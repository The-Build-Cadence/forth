"""One instruction policy shared by UI, workers, and MCP generation."""
import re


def material_instructions(owner, job):
    if job is not None and job.generation_instructions is not None:
        return job.generation_instructions
    return getattr(getattr(owner, 'candidate_profile', None), 'generation_instructions', '') or ''


DESIGN_CHOICES = {
    'template': ('modern', 'classic', 'minimal'),
    'density': ('compact', 'balanced', 'spacious'),
    'page_size': ('Letter', 'A4'),
    'layout': ('single', 'two_column'),
    'font': ('sans', 'humanist', 'serif'),
}


def normalize_design(design):
    supplied = design if isinstance(design, dict) else {}
    defaults = dict(template='modern', density='balanced', page_size='Letter', layout='single', font='sans')
    selected = {key: supplied.get(key) if supplied.get(key) in choices else defaults[key] for key, choices in DESIGN_CHOICES.items()}
    if 'font' not in supplied and selected['template'] == 'classic':
        selected['font'] = 'serif'
    selected['accent'] = supplied.get('accent') if re.fullmatch(r'#[0-9a-fA-F]{6}', str(supplied.get('accent', ''))) else '#177d69'
    pages = supplied.get('max_pages', 0)
    selected['max_pages'] = pages if type(pages) is int and pages in (0, 1, 2, 3) else 0
    selected['rationale'] = str(supplied.get('rationale', ''))[:1000]
    return selected


def instruction_design(design, instructions):
    """Explicit candidate choices override model defaults on every generation path."""
    selected = dict(design or {})
    for key, choices in {
        'template': ['modern', 'classic', 'minimal'],
        'density': ['compact', 'balanced', 'spacious'],
        'page_size': ['Letter', 'A4'],
    }.items():
        matches = list(re.finditer(r'\b(' + '|'.join(choices) + r')\b', instructions, re.I))
        if key == 'template':
            contextual = list(re.finditer(r'\b(modern|classic|minimal)(?=\s+(?:design|layout|style|resume)\b)', instructions, re.I))
            if contextual:
                matches = contextual
        if matches:
            # “polished, modern ... clean, minimal design” resolves to minimal.
            selected[key] = next(choice for choice in choices if choice.lower() == matches[-1][0].lower())
    colors = re.findall(r'#[0-9a-fA-F]{6}\b', instructions)
    if colors:
        selected['accent'] = colors[-1]
    columns = list(re.finditer(r'\b(single|one|two|1|2)[-\s]+column', instructions, re.I))
    if columns:
        selected['layout'] = 'two_column' if columns[-1][1].lower() in ('two', '2') else 'single'
    fonts = list(re.finditer(r'\b(Aptos|Calibri|Carlito|Helvetica|Arial|sans[- ]serif|Georgia|Times New Roman|serif)\b', instructions, re.I))
    if fonts:
        named = [match for match in fonts if match[0].lower() not in ('sans-serif', 'sans serif', 'serif')]
        name = (named[0] if named else fonts[0])[0].lower()
        selected['font'] = 'humanist' if name in ('aptos', 'calibri', 'carlito') else 'serif' if name in ('georgia', 'times new roman', 'serif') else 'sans'
    pages = re.search(r'\b(?:maximum of|max(?:imum)?|up to|at most|no more than|limit(?:ed)? to)\s+(one|two|three|[123])\s*pages?\b', instructions, re.I)
    if not pages:
        pages = re.search(r'\b(one|two|three|[123])[- ]page\s+(?:resume|limit|maximum)\b', instructions, re.I)
    if pages:
        selected['max_pages'] = {'one': 1, 'two': 2, 'three': 3}.get(pages[1].lower(), int(pages[1]) if pages[1].isdigit() else 0)
    return normalize_design(selected)


def readable_match_summary(summary):
    """Translate old stored summaries without rescoring or changing evidence."""
    labels = {'fail': 'required condition mismatch', 'pass': 'meets required conditions', 'uncertain': 'required conditions need confirmation'}
    return re.sub(r'eligibility (fail|pass|uncertain)', lambda match: labels[match[1].lower()], summary or '', flags=re.I)


def document_design(owner, job=None, proposed=None):
    """Saved explicit appearance wins over AI and prose on every generation path."""
    from core.models import AccountSettings
    saved = AccountSettings.objects.filter(owner=owner).values_list('document_design', flat=True).first()
    if saved:
        return normalize_design(saved)
    return instruction_design(proposed, material_instructions(owner, job))
