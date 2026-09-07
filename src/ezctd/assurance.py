"""Per-rule evaluation accounting. Absence of a finding is not a pass.

A PASS means a bounded local predicate completed, never CDE equivalence.
Unimplemented exhaustive scans and missing context remain INDETERMINATE.
"""
from __future__ import annotations
from types import SimpleNamespace
from .applicability import resolve

# These predicates have observable completion conditions in the current observer.
BOUNDED_NEGATIVE_RULES = {'6.16', '6.19', '6.21', '6.22', '6.23'}


def assess_result(result: dict, context=None) -> dict:
    context = context or SimpleNamespace(**{k: result.get('context', {}).get(k)
                                           for k in ('node_id', 'document_role', 'language')})
    observations = result.setdefault('observations', {})
    diagnostics = result.get('diagnostics', {})
    opened = diagnostics.get('pikepdf_open') == 'PASS'
    candidates = {f['rule_id']: f for f in result.get('findings', [])}
    rows = []
    for number in range(1, 27):
        rule_id = f'6.{number}'
        applies = resolve(rule_id, context)
        candidate = candidates.get(rule_id)
        if not applies.applicable:
            state, reason = 'NOT_APPLICABLE', applies.reason
        elif not applies.known:
            state, reason = 'INDETERMINATE', applies.reason
        elif candidate and candidate.get('confidence', 'high') == 'high':
            state, reason = 'FAIL', 'Explicit local condition observed; official calibration not established'
        elif candidate:
            state, reason = 'INDETERMINATE', 'Candidate finding requires semantic or technical review'
        elif not opened:
            state, reason = 'NOT_RUN', 'PDF could not be inspected without errors or credentials'
        elif rule_id in BOUNDED_NEGATIVE_RULES:
            state, reason = 'PASS', 'Bounded local property check completed'
        else:
            state, reason = 'INDETERMINATE', 'Exhaustive rule coverage has not been demonstrated'
        rows.append({'rule_id': rule_id, 'status': state, 'reason': reason,
                     'candidate_finding_present': candidate is not None,
                     'official_calibration': 'NOT_ESTABLISHED'})
        if candidate is not None:
            candidate['local_evaluation_status'] = state
    result['rule_evaluations'] = rows
    observations['rules_evaluated'] = [x['rule_id'] for x in rows if x['status'] in ('PASS', 'FAIL')]
    result['completion_assurance'] = 'PARTIAL_RULE_COVERAGE' if any(x['status'] in ('NOT_RUN', 'INDETERMINATE') for x in rows) else 'LOCAL_PREDICATES_COMPLETED'
    result['compliance_conclusion'] = 'NOT_ESTABLISHED'
    return result
