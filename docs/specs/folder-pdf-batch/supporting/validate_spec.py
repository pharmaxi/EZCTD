#!/usr/bin/env python3
"""Validate spec references only. Does NOT inspect or modify any PDF."""
from __future__ import annotations
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def validate(root: Path) -> dict[str, Any]:
    data = json.loads((root / 'supporting/traceability.json').read_text(encoding='utf-8'))
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: Any = None) -> None:
        checks.append({'name': name, 'passed': bool(condition), 'detail': detail})

    rules, tasks = data['rules'], data['tasks']
    rule_ids = [r['id'] for r in rules]
    check('complete_current_rules', rule_ids == [f'6.{i}' for i in range(1, 27)], rule_ids)
    severities = dict(Counter(r['severity'] for r in rules))
    check('severity_counts', severities == {'错误': 16, '警告': 8, '提示信息': 2}, severities)
    expected_crosswalk = {f'4.{i}': f'6.{j}' for i, j in enumerate([1,21,16,17,19,20,23,24,25,2,3,4,5,6,7,8,9,10,11,12,13,14,15,26],1)}
    actual_crosswalk = {r['legacy']: r['id'] for r in rules if r['legacy']}
    check('all_24_legacy_mappings', actual_crosswalk == expected_crosswalk, actual_crosswalk)
    check('two_additional_current_rules', {r['id'] for r in rules if r['legacy'] is None} == {'6.18','6.22'})
    check('material_content_rule_not_overinterpreted', next(r for r in rules if r['id']=='6.24')['legacy_mapping']=='TOPIC_ONLY')
    check('bookmark_wording_change_recorded', next(r for r in rules if r['id']=='6.23')['legacy_mapping']=='WORDING_CHANGED')
    check('scope_unchanged', data['scope']==['5','2.5','2.7'], data['scope'])
    check('reference_exceptions_do_not_skip_readability_password', {r['id'] for r in rules if r['applicability']=='ALL'}=={'6.1','6.21'})
    task_ids = [t['id'] for t in tasks]
    check('unique_task_ids', len(set(task_ids))==len(task_ids), len(task_ids))
    check('contiguous_task_ids', task_ids==[f'T-{i:03d}' for i in range(1,len(tasks)+1)])
    task_set = set(task_ids)
    bad_deps = [(t['id'], d) for t in tasks for d in t['dependencies'] if d not in task_set or d==t['id']]
    check('task_dependencies_exist', not bad_deps, bad_deps)
    adj = {t['id']: t['dependencies'] for t in tasks}
    seen, active, order = set(), set(), []
    cycle = []
    def visit(tid: str) -> None:
        if tid in active:
            cycle.append(tid)
            return
        if tid in seen:
            return
        active.add(tid)
        for dep in adj.get(tid, []):
            visit(dep)
        active.remove(tid)
        seen.add(tid)
        order.append(tid)
    for tid in task_ids:
        visit(tid)
    check('acyclic_task_graph', not cycle, cycle)
    known_reqs = ({r['id'] for r in data['requirements']} |
                  {r['requirement_id'] for r in rules} |
                  {r['id'] for r in data['supplemental_requirements']})
    referenced = {r for t in tasks for r in t['requirements']}
    check('all_requirements_have_tasks', not (known_reqs-referenced), sorted(known_reqs-referenced))
    check('no_unknown_requirement_references', not (referenced-known_reqs), sorted(referenced-known_reqs))
    tests = data['rule_acceptance_tests'] + data['integration_tests']
    test_ids = [t['id'] for t in tests]
    known_tests = set(test_ids)
    ref_tests = {i for t in tasks for i in t['test_ids']}
    check('unique_test_ids', len(known_tests)==len(test_ids), len(test_ids))
    check('78_rule_test_specs', len(data['rule_acceptance_tests'])==78)
    check('36_integration_specs', len(data['integration_tests'])==36)
    check('all_test_specs_attached_to_tasks', not (known_tests-ref_tests), sorted(known_tests-ref_tests))
    check('no_unknown_test_references', not (ref_tests-known_tests), sorted(ref_tests-known_tests))
    check('no_product_test_claim', all(t['status']=='PLANNED_NOT_RUN' for t in tests))
    check('all_development_tasks_uncompleted', all(t['status']=='TODO' and not t['completion_evidence'] for t in tasks))
    milestones = {m['id'] for m in data['milestones']}
    check('seven_milestones', milestones=={f'M{i}' for i in range(7)})
    check('all_tasks_have_valid_stage', all(t['milestone'] in milestones for t in tasks))
    check('official_attachment_hash_not_fabricated', next(s for s in data['sources'] if s['id']=='S02')['sha256'] is None)
    check('mirror_hash_not_substituted', next(s for s in data['sources'] if s['id']=='S03')['sha256'] is None)
    source_ids = {s['id'] for s in data['sources']}
    docs = {}
    for name in ('requirements.md','design.md','tasks.md'):
        path = root / name
        check(f'{name}_exists', path.is_file())
        if not path.is_file():
            continue
        text=path.read_text(encoding='utf-8')
        docs[name] = text
        check(f'{name}_no_encoding_replacements', '\ufffd' not in text)
        check(f'{name}_balanced_code_fences', len(re.findall(r'^```',text,re.M))%2==0)
        check(f'{name}_baseline_recorded', data['baseline_commit'] in text)
        refs=set(re.findall(r'\[(S\d{2})\]',text))
        check(f'{name}_source_ids_resolve', refs<=source_ids, sorted(refs-source_ids))
        check(f'{name}_not_placeholder_only', len(text)>10000, len(text))
    reqtext=docs.get('requirements.md','')
    tasktext=docs.get('tasks.md','')
    check('all_rule_sections_in_requirements', all(f'### {r["requirement_id"]} ·' in reqtext for r in rules))
    check('all_task_cards_present', all(f'### {t["id"]} ·' in tasktext for t in tasks))
    check('no_checked_development_boxes', '- [x]' not in tasktext.lower())
    return {
        'validation_scope':'SPEC_STATIC_CONSISTENCY_ONLY',
        'status':'PASS' if all(c['passed'] for c in checks) else 'FAIL',
        'checks':checks,
        'counts':{'checks':len(checks),'passed':sum(c['passed'] for c in checks),
                  'rules':len(rules),'requirements_including_rules_and_extras':len(known_reqs),
                  'development_tasks':len(tasks),'milestones':len(milestones),
                  'rule_test_specifications':len(data['rule_acceptance_tests']),
                  'integration_test_specifications':len(data['integration_tests']),
                  'product_tests_executed':0},
        'task_topological_order':order,
        'milestone_task_counts':dict(Counter(t['milestone'] for t in tasks)),
        'not_proven':['PDF operation correctness','actual implementation availability','Windows/NAS compatibility',
                      'official validator equivalence','byte identity of mirror and CDE attachment'],
    }


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    try:
        result = validate(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Spec validation failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    output=root/'supporting/spec_validation.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],**result['counts']},ensure_ascii=False))
    return 0 if result['status']=='PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
