import re
from pathlib import Path

from tools.schemas import Corpus, CorpusBullet, CorpusRole


def _slugify(text: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower())
    return slug.strip('-')


def parse_corpus(path: str = "experience.md") -> Corpus:
    """Parse experience.md into a Corpus object."""
    content = Path(path).read_text()

    name_match = re.search(r'^# (.+?)(?:\s*[-—]|$)', content, re.MULTILINE)
    name = name_match.group(1).strip() if name_match else "Unknown"

    sections = re.split(r'^## ', content, flags=re.MULTILINE)

    roles = []
    projects = []
    education = []
    other = {}

    for section in sections[1:]:
        lines = section.split('\n')
        header = lines[0].strip()
        body = '\n'.join(lines[1:]).strip()

        header_lower = header.lower()
        if 'personal project' in header_lower or header_lower == 'projects':
            projects = _parse_bullets(body, role_id="personal-projects")
        elif 'education' in header_lower:
            education = _parse_education(body)
        elif _looks_like_role(header):
            roles.append(_parse_role(header, body))
        else:
            other[header] = body

    return Corpus(
        name=name,
        roles=roles,
        projects=projects,
        education=education,
        other=other,
    )


def _looks_like_role(header: str) -> bool:
    return '(' in header or ' - ' in header or ' | ' in header


def _parse_role(header: str, body: str) -> CorpusRole:
    m = re.match(r'^(.+?)\s*\((.+?)\)$', header)
    if m:
        company = m.group(1).strip()
        title = m.group(2).strip()
    else:
        company = header
        title = ""

    role_id = _slugify(f"{company}-{title}")

    dates_match = re.search(r'\*\*Dates?:\*\*\s*(.+)', body)
    dates = dates_match.group(1).strip() if dates_match else ""

    stack_match = re.search(r'\*\*Tech [Ss]tack:\*\*\s*(.+)', body)
    tech_stack = []
    if stack_match:
        tech_stack = [s.strip() for s in stack_match.group(1).split(',')]

    bullets_text = re.sub(
        r'\*\*(?:Dates?|Tech [Ss]tack|Team):\*\*.+\n',
        '', body
    )
    bullets = _parse_bullets(bullets_text, role_id=role_id)

    return CorpusRole(
        role_id=role_id,
        company=company,
        title=title,
        dates=dates,
        tech_stack=tech_stack,
        bullets=bullets,
    )


def _parse_bullets(body: str, role_id: str) -> list[CorpusBullet]:
    bullets = []
    sections = re.split(r'^### ', body, flags=re.MULTILINE)
    for section in sections[1:]:
        lines = section.split('\n', 1)
        title = lines[0].strip()
        text = lines[1].strip() if len(lines) > 1 else ""
        if not text:
            continue
        bullets.append(CorpusBullet(
            role_id=role_id,
            bullet_id=_slugify(title),
            title=title,
            text=text,
        ))
    return bullets


def _parse_education(body: str) -> list[str]:
    return [
        line.strip() for line in body.split('\n')
        if line.strip() and not line.strip().startswith('#')
    ]
