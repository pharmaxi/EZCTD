"""Used-font inventory through inherited resources and Form XObjects.

Names below are the exact published list, not PDF Base-14 substitutions.
Alias resolution intentionally remains unconfirmed. Failures are explicit.
"""
from __future__ import annotations
import pikepdf

CDE_STANDARD_FONT_NAMES = frozenset({
    '宋体', '黑体', 'Times New Roman', 'Times New Roman Italic', 'Times New Roman Bold',
    'Times New Roman Bold Italic', 'Arial', 'Arial Italic', 'Arial Bold', 'Arial Bold Italic',
    'Courier New', 'Courier New Italic', 'Courier New Bold', 'Courier New Bold Italic',
    'Symbol', 'Zapf Dingbats',
})


def collect_page_resources(page: pikepdf.Page) -> dict:
    fonts, issues, seen = [], [], set()
    node, resources = page.obj, None
    for _ in range(64):
        resources = node.get('/Resources')
        if resources is not None:
            break
        node = node.get('/Parent')
        if node is None:
            break
    if resources is None:
        return {'fonts': [], 'issues': ['PAGE_RESOURCES_UNRESOLVED']}

    def visit(stream, resources, depth):
        if depth > 32 or len(seen) > 10000:
            issues.append('RESOURCE_TRAVERSAL_LIMIT')
            return
        identity = (getattr(stream, 'objgen', (0, 0)), id(stream) if getattr(stream, 'objgen', (0, 0)) == (0, 0) else 0)
        if identity in seen:
            issues.append('RESOURCE_CYCLE_OR_REUSE')
            return
        seen.add(identity)
        try:
            instructions = pikepdf.parse_content_stream(stream, operators='Tf Do')
            for instruction in instructions:
                op = str(instruction.operator)
                values = instruction.operands
                if op == 'Tf' and values:
                    name = str(values[0])
                    font = resources.get('/Font', {}).get(name)
                    if font is None:
                        issues.append('FONT_RESOURCE_MISSING:' + name)
                    else:
                        fonts.append({'name': name, 'font': font})
                elif op == 'Do' and values:
                    obj = resources.get('/XObject', {}).get(str(values[0]))
                    if obj is None:
                        issues.append('XOBJECT_RESOURCE_MISSING')
                    elif obj.get('/Subtype') == '/Form':
                        visit(obj, obj.get('/Resources', resources), depth + 1)
        except Exception as exc:
            issues.append('CONTENT_PARSE_FAILED:' + type(exc).__name__)
    visit(page, resources, 0)
    return {'fonts': fonts, 'issues': issues}
