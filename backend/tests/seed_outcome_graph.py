#!/usr/bin/env python3
"""Seed only synthetic browser fixtures in validated /tmp/nautilus-playwright.*.

Uses existing Core commands/evidence events; never called from product routes.
"""
import argparse
import asyncio
import json
from pathlib import Path

from app.core.commands import ConfirmLearningSetup, StartSession, SaveTextArtifact, EndSession
from app.core.events import canonical
from app.evidence import EvidenceService, ModelObservationDraft
from app.evidence_events import EvidenceEventService
from app.learning_storage import open_learning_database
from app.learning_service import LearningService
from app.review import ReviewService
from app.state_derivation import StateDerivationService


def seed(data_dir, owner_id, prefix):
    original=Path(data_dir).expanduser()
    root=original.resolve()
    if original.is_symlink() or root.parent!=Path('/tmp') or not root.name.startswith('nautilus-playwright.'):
        raise ValueError('synthetic graph fixtures require /tmp/nautilus-playwright.*')
    if not prefix or len(prefix)>70:
        raise ValueError('invalid fixture prefix')
    database_path=root/'learning.sqlite3'
    if database_path.is_symlink() or database_path.resolve().parent != root or database_path.stat().st_nlink != 1:
        raise ValueError('synthetic database must be a direct, unshared file in the isolated directory')
    db=open_learning_database(database_path,migrate=False)
    try:
        identity=dict(db.fetchone('SELECT * FROM local_identity WHERE id=?',(owner_id,)))
        learning=LearningService(db)
        principal=learning.principal(identity)
        standard=learning.overview(identity)['standards'][0]
        criterion_id=prefix+'-criterion-v2'
        recipe={'dimensions':[
            {'id':'application','label':'合成应用检查','requirements':[{'method':'deterministic_check','condition':'with_materials','minimum':1}]},
            {'id':'syntax_semantics','label':'合成不同表现','requirements':[{'method':'deterministic_check','condition':'with_materials','minimum':1}]},
            {'id':'transfer','label':'合成迁移验证','requirements':[{'method':'transfer','condition':'independent','minimum':1}]}]}
        with db.transaction() as connection:
            connection.execute('''INSERT INTO learning_criterion_version SELECT ?,owner_id,package_id,outcome_id,
                (SELECT MAX(version)+1 FROM learning_criterion_version WHERE owner_id=? AND outcome_id=?),
                'synthetic D1 browser fixture',context_key,?,review_status,'synthetic-fixture',reviewed_at,created_at
                FROM learning_criterion_version WHERE id=?''',
                (criterion_id,owner_id,standard['outcome_id'],canonical(recipe),standard['id']))
        def setup(key,title,outcome_id=None,criterion=None,context='python-regex-basics'):
            return learning.core.execute(principal,ConfirmLearningSetup(original_intent='合成浏览器成果图检查',
                goal_title=title,plan_title=title,action_title=title+'任务',context_key=context,outcome_id=outcome_id,
                criterion_id=criterion,object_description=title+'对象',behavior='能解释并完成合成示例',
                outcome_context_key=context,boundaries='仅合成数据',stop_conditions='保存一份合成作答'),prefix+key)
        supported=setup('-support',prefix+'主计划',standard['outcome_id'],criterion_id)
        missing=setup('-missing',prefix+'另一个计划',context='synthetic-unqualified')
        extra=learning.create_outcome(identity,{'object_description':prefix+'无标准成果',
            'behavior':'能展示尚未验证的综合演示','context_key':'synthetic-unqualified'},prefix+'-no-standard')
        session=learning.core.execute(principal,StartSession(delegation_id=supported['delegation_id'],expected_version=2),prefix+'-session')
        artifact=learning.core.execute(principal,SaveTextArtifact(session_id=session['id'],content='regex: ^D1\\d+$\nsample: D142',expected_version=3),prefix+'-artifact')
        learning.core.execute(principal,EndSession(session_id=session['id'],disposition='ended',expected_version=4),prefix+'-end')
        events=EvidenceEventService(db)
        evidence=EvidenceService(learning,evidence_events=events)
        deterministic=evidence.analyzer
        evidence.analyzer=lambda request:[*deterministic(request),ModelObservationDraft(dimension_id='syntax_semantics',
            stance='refutes',statement='合成场景中观察到不同表现。',scope='artifact')]
        result=asyncio.run(evidence.analyze(identity,artifact['id'],prefix+'-analysis'))
        state=StateDerivationService(learning,events)
        review=ReviewService(learning,state,events)
        for claim in result['claims']:
            review.review(identity,claim['id'],'adopt','合成检查',prefix+'-review-'+claim['id'])
        return dict(support_outcome_id=standard['outcome_id'],no_standard_outcome_id=extra['id'],
            other_plan_outcome_id=missing['outcome_id'],plan_id=supported['plan_id'],other_plan_id=missing['plan_id'],
            artifact_id=artifact['id'],criterion_id=criterion_id,standard_v1_id=standard['id'],
            plan_title=prefix+'主计划',other_plan_title=prefix+'另一个计划',no_standard_label=prefix+'无标准成果')
    finally:
        db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',required=True)
    parser.add_argument('--owner-id',required=True)
    parser.add_argument('--prefix',required=True)
    args=parser.parse_args()
    print(json.dumps(seed(args.data_dir,args.owner_id,args.prefix),ensure_ascii=False))
