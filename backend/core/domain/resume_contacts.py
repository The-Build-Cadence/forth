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


def without_resume_contacts(markdown: str, contact: dict | None = None) -> str:
    """Remove source contact text before adding the explicitly selected header.

    Keep surrounding identity, location, and evidence; do not treat date ranges as
    telephone numbers. This covers conventional plain text and Markdown contacts.
    """
    lines = []
    known_email = re.sub(r'[^a-z0-9]', '', (contact or {}).get('email', '').lower())
    for line in markdown.splitlines():
        # Remove only a standalone duplicate of the known address, including
        # the old username-derived display text that replaced dots with spaces.
        email_line = re.sub(r'^\s*(?:e-?mail\s*:)?\s*', '', line, flags=re.I)
        if known_email and re.sub(r'[^a-z0-9]', '', email_line.lower()) == known_email:
            continue
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
    body = without_resume_contacts(markdown, contact)
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


def import_resume_contacts(owner, text: str) -> dict:
    """Seed contacts from resume evidence only until the user has saved settings."""
    from core.models import CandidateProfile
    from django.db import transaction

    email = re.search(_EMAIL, text)
    linkedin = re.search(_LINKEDIN, text, re.I)
    phone = None
    for line in text.splitlines():
        for match in re.finditer(_PHONE, line, re.I):
            if _is_phone(match[0], labelled=bool(re.search(r'\b(phone|mobile|tel)\b', line, re.I)), whole_line=line.strip() == match[0]):
                phone = match[0].strip()
                break
        if phone:
            break
    url = linkedin[0].rstrip('.,;|') if linkedin else ''
    if url and not url.lower().startswith(('http://', 'https://')):
        url = 'https://' + url
    contact = {'email': email[0] if email else '', 'phone': phone or '', 'linkedin_url': url,
               'include_email': True, 'include_phone': True, 'include_linkedin': True}
    if not any(contact[field] for field in ('email', 'phone', 'linkedin_url')):
        return {}
    with transaction.atomic():
        profile, _ = CandidateProfile.objects.get_or_create(owner=owner)
        profile = CandidateProfile.objects.select_for_update().get(pk=profile.pk)
        if profile.resume_contact:
            return profile.resume_contact
        profile.resume_contact = contact
        profile.save(update_fields=['resume_contact', 'updated_at'])
    return contact


def without_design_notes(markdown: str) -> str:
    """Strip presentation commentary, not genuine design-related experience."""
    lines = markdown.splitlines()
    output = []
    skip_section = False
    labels = r'(?:resume\s+)?(?:design|layout|formatting|styling)(?:\s+(?:notes?|instructions?|direction))?'
    visual = r'\b(?:template|columns?|font|typeface|accent|#[0-9a-f]{6}|letter[- ]size|paper|pages?|spacing|margin|modern|minimal|classic)\b'
    for index, line in enumerate(lines):
        plain = re.sub(r'[*_`]', '', line).strip()
        if re.match(r'^#{1,6}\s', plain):
            skip_section = False
            if re.fullmatch(r'#{1,6}\s+' + labels + r'\s*:?', plain, re.I):
                upcoming = []
                for following in lines[index+1:]:
                    if re.match(r'^#{1,6}\s', following): break
                    upcoming.append(following)
                if re.search(visual, ' '.join(upcoming), re.I):
                    skip_section = True
                    continue
        if skip_section:
            continue
        plain = re.sub(r'^[-*]\s+', '', plain)
        if re.match(r'^' + labels + r'\s*[:—-]', plain, re.I) and re.search(visual, plain, re.I):
            continue
        output.append(line)
    return '\n'.join(output)


def resume_presentation_text(resume) -> str:
    """Clean legacy/generated output at every presentation/export boundary."""
    text = without_design_notes(resume.content_markdown)
    snapshot = (resume.content_json or {}).get('resume_contact') or {}
    if snapshot:
        contact = {**snapshot, **{'include_' + key: bool(snapshot.get(key if key != 'linkedin' else 'linkedin_url'))
                                 for key in ('phone', 'email', 'linkedin')}}
        heading = re.search(r'(?m)^# (.+)$', text)
        text = apply_resume_contacts(text, contact, candidate_name=heading[1] if heading else 'Candidate')
    return text
