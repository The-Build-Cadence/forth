"""One instruction policy shared by UI, workers, and MCP generation."""
import re


def material_instructions(owner, job):
    if job.generation_instructions is not None:
        return job.generation_instructions
    return getattr(getattr(owner, 'candidate_profile', None), 'generation_instructions', '') or ''


def instruction_design(design, instructions):
    """Honor explicit supported style choices even when AI is unavailable."""
    selected = dict(design or {})
    for key, choices in {
        'template': ['modern', 'classic', 'minimal'],
        'density': ['compact', 'balanced', 'spacious'],
        'page_size': ['Letter', 'A4'],
    }.items():
        matches = [choice for choice in choices if re.search(r'\b' + choice + r'\b', instructions, re.I)]
        if len(matches) == 1:
            selected[key] = matches[0]
    colors = re.findall(r'#[0-9a-fA-F]{6}\b', instructions)
    if len(set(colors)) == 1:
        selected['accent'] = colors[0]
    return selected


def readable_match_summary(summary):
    """Translate old stored summaries without rescoring or changing evidence."""
    labels = {'fail': 'required condition mismatch', 'pass': 'meets required conditions', 'uncertain': 'required conditions need confirmation'}
    return re.sub(r'eligibility (fail|pass|uncertain)', lambda match: labels[match[1].lower()], summary or '', flags=re.I)
