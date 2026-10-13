"""Deterministic contact headers shared by every resume generation entry point."""
import re


_EMAIL = r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
_LINKEDIN = r'(?:https?://)?(?:[\w-]+\.)?linkedin\.com/[^\s<>)]+'
_PHONE = r'(?<!\w)(?:\+?\d|\(\d)[\d ().-]{5,}\d(?:\s*(?:ext\.?|x)\s*\d+)?(?!\w)'


def _is_phone(value: str, *, labelled: bool, whole_line: bool) -> bool:
    digits = sum(char.isdigit() for char in value)
    if not 7 <= digits <= 21:
        return False
    # Preserve years and numeric accomplishment ranges, such as 100000-150000.
    groups = [len(group) for group in re.findall(r'\d+', value)]
    grouped_number = digits >= 9 and len(groups) >= 3 and max(groups) <= 4
    return labelled or value.startswith('+') or '(' in value or grouped_number or (whole_line and len(groups) == 1)


def without_resume_contacts(markdown: str) -> str:
    """Remove source contact text before adding the explicitly selected header.

    Keep surrounding identity, location, and evidence; do not treat date ranges as
    telephone numbers. This covers conventional plain text and Markdown contacts.
    """
    lines = []
    for line in markdown.splitlines():
        line = re.sub(r'\[[^\]]*\]\((?:(?:mailto:|tel:)[^\s)]+|' + _LINKEDIN + r')\)', '', line, flags=re.I)
        line = re.sub(_EMAIL, '', line)
        line = re.sub(_LINKEDIN, '', line, flags=re.I)
        labelled_phone = bool(re.search(r'\b(?:phone|mobile|tel(?:ephone)?)\s*\*{0,2}:', line, re.I))
        line = re.sub(_PHONE, lambda match: '' if _is_phone(match[0], labelled=labelled_phone, whole_line=line.strip() == match[0]) else match[0], line, flags=re.I)
        line = re.sub(r'\b(?:phone|mobile|tel(?:ephone)?|e-?mail|linkedin)(?:\s+url)?\s*\*{0,2}:\s*', '', line, flags=re.I)
        line = re.sub(r'\*\*\s*\*\*', '', line)
        line = line.strip(' \t|·,;')
        if line and not re.fullmatch(r'[-*#\s]+', line):
            lines.append(line)
        elif not line:
            lines.append('')
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def apply_resume_contacts(markdown: str, contact: dict, *, candidate_name: str) -> str:
    if not contact:
        return markdown
    body = without_resume_contacts(markdown)
    lines = []
    if contact.get('include_phone') and contact.get('phone'):
        lines.append(f'Phone: {contact["phone"]}')
    if contact.get('include_email') and contact.get('email'):
        email = contact['email']
        lines.append(f'Email: [{email}](mailto:{email})')
    if contact.get('include_linkedin') and contact.get('linkedin_url'):
        url = contact['linkedin_url']
        lines.append(f'LinkedIn: [{url}]({url})')
    header = re.search(r'(?m)^# .+$', body)
    if not header:
        body = f'# {candidate_name}\n\n{body}'
        header = re.search(r'(?m)^# .+$', body)
    if lines:
        body = body[:header.end()] + '\n\n' + '\n\n'.join(lines) + '\n\n' + body[header.end():].lstrip()
    return body.rstrip() + '\n'
