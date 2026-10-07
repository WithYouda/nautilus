"""Two actual chat kinds, immutable originals, source checks and erasure closure."""
import json
from uuid import uuid4
import httpx
import pytest
from test_model_control import (RecordingProvider, make_client, authorize, configure_provider,
    make_scope, send, checked, new_chat)
import sqlite3
from contextlib import closing
from app.purge_storage import register_backup, storage_lock


class ComparisonProvider(RecordingProvider):
    def __call__(self, request):
        payload = json.loads(request.content)
        try:
            sources = json.loads(payload['messages'][-1]['content'])
        except (ValueError, TypeError):
            sources = None
        if isinstance(sources, dict) and set(sources) == {'left', 'right'}:
            self.comparison_input = sources
            refs = [dict(side=side, id=items[-1]['id'], quote=items[-1]['text'][:80]) for side, items in sources.items()]
            result = dict(cards=[dict(topic='合成观点', relation='complement', conclusion='合成对比结论', references=refs)])
            return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}]})
        return super().__call__(request)


def fork(client, kind, identifier, answer):
    path = '/api/ai/conversations' if kind == 'conversation' else '/api/learning/discussions'
    result = checked(client.post(f'{path}/{identifier}/branches', json={
        'message_id' if kind == 'conversation' else 'turn_id': answer['id'], 'request_key': str(uuid4())}), 201)
    return result['conversation']['id'] if kind == 'conversation' else result['id']


def detail(client, kind, identifier):
    path = '/api/ai/conversations' if kind == 'conversation' else '/api/learning/discussions'
    return checked(client.get(f'{path}/{identifier}'))


def draft(client, kind, left, right):
    return checked(client.post(f'/api/branch-comparisons/{kind}/{left}/previews', json={'other_id':right}))


@pytest.mark.parametrize('kind', ['conversation','discussion'])
def test_compare_confirm_continue_and_purge_both_kinds(tmp_path, kind):
    provider = ComparisonProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); identity = client.app.state.auth.ensure_local_identity(); configure_provider(client)
        left, context, original = make_scope(client, provider, kind)
        first = send(client, kind, left, 'first')
        right = fork(client,kind,left,first)
        material = checked(client.post(f'/api/materials/{kind}/{right}',json={'title':'合成教材','content':'合成资料，仅用于清除检查'}), 201)
        right_answer = send(client,kind,right,'right',content='合成另一种思路',source_scope={'mode':'reference','version_ids':[material['id']]})
        before_left, before_right = detail(client,kind,left), detail(client,kind,right)
        events = client.app.state.learning.database.fetchone('SELECT COUNT(*) FROM learning_event')[0]
        preview = draft(client,kind,left,right)
        assert len(preview['cards']) == 1
        cache = client.app.state.branch_comparisons.drafts[identity['id']]
        assert '合成对比结论' not in json.dumps(cache,ensure_ascii=False)
        body = dict(preview_id=preview['preview_id'],title='合成合并结论',selected=[dict(id=preview['cards'][0]['id'],text='经本人编辑的合成结论')])
        merged = checked(client.post('/api/branch-comparisons/confirm',json=body))['id']
        assert checked(client.post('/api/branch-comparisons/confirm',json=body))['id'] == merged
        assert client.post('/api/branch-comparisons/confirm',json={**body,'title':'另一个标题'}).status_code == 409
        assert detail(client,kind,left) == before_left and detail(client,kind,right) == before_right
        assert client.app.state.learning.database.fetchone('SELECT COUNT(*) FROM learning_event')[0] == events
        result = detail(client,kind,merged)
        seed = result['messages'][-1] if kind == 'conversation' else result['turns'][-1]
        assert seed['branch_conclusion'] and seed['teaching'] is None
        assert (seed.get('content') or seed.get('assistant_content')) == '经本人编辑的合成结论'
        path = '/api/ai/conversations' if kind == 'conversation' else '/api/learning/discussions'
        node = next(n for n in checked(client.get(f'{path}/{merged}/branch-map'))['nodes'] if n['id'] == merged)
        assert {p['id'] for p in node['merge_sources']} == {left,right}
        followup = send(client,kind,merged,'followup',content='接着整理后的结论解释一个例子')
        assert '经本人编辑的合成结论' in json.dumps(provider.payloads[-1]['messages'],ensure_ascii=False)
        descendant = fork(client,kind,merged,followup)
        # Source loss invalidates an unconfirmed preview, and erases all accepted descendants.
        pending = draft(client,kind,left,right)
        db = client.app.state.conversations.database if kind == 'conversation' else client.app.state.learning.database
        backup = tmp_path / 'comparison-backup.sqlite3'
        with closing(sqlite3.connect(backup)) as c:
            db.connection.backup(c)
        materials = client.app.state.materials
        with storage_lock(materials.db.database_path):
            register_backup(materials.db.database_path, backup)
        purged = checked(client.post(f"/api/materials/{kind}/{right}/{material['material_id']}/purge"))
        assert purged['purge']['status'] == 'complete'
        with closing(sqlite3.connect(backup)) as c:
            assert '经本人编辑的合成结论' not in '\n'.join(c.iterdump())
        assert client.post('/api/branch-comparisons/confirm',json={**body,'preview_id':pending['preview_id'],'selected':[dict(id=pending['cards'][0]['id'],text='不能保存')] }).status_code == 409
        for identifier in [merged,descendant]:
            erased_detail = detail(client,kind,identifier)
            assert '经本人编辑的合成结论' not in json.dumps(erased_detail,ensure_ascii=False)


def test_unrelated_graph_and_unquoted_provider_output_are_rejected(tmp_path):
    provider = ComparisonProvider()
    with make_client(tmp_path,provider) as client:
        authorize(client); identity = client.app.state.auth.ensure_local_identity(); configure_provider(client)
        left, _, _ = make_scope(client,provider,'conversation')
        first = send(client,'conversation',left)
        right = fork(client,'conversation',left,first)
        unrelated = new_chat(client)
        assert client.post(f'/api/branch-comparisons/conversation/{left}/previews',json={'other_id':unrelated}).status_code == 422
        service = client.app.state.branch_comparisons
        from app.branch_comparisons import ComparisonError
        sources = service.sources(identity,'conversation',left,right)
        with pytest.raises(ComparisonError):
            service._validate_cards(dict(cards=[dict(topic='假引用',relation='same',conclusion='不能采用',references=[dict(side='left',id=first['id'],quote='原文没有这句话')])]),sources)


def test_comparison_reads_selected_path_not_later_messages(tmp_path):
    provider = ComparisonProvider()
    with make_client(tmp_path,provider) as client:
        authorize(client); configure_provider(client)
        left, _, _ = make_scope(client,provider,'conversation')
        first = send(client,'conversation',left,'first')
        right = fork(client,'conversation',left,first)
        later = send(client,'conversation',left,'later',content='LATER_PATH_MUST_NOT_APPEAR')
        current = checked(client.get(f'/api/conversation-state/conversation/{left}'))
        checked(client.put(f'/api/conversation-state/conversation/{left}',json=dict(
            leaf_id=first['id'],paths={},source_scope={'mode':'unspecified','version_ids':[]},search_override=None,expected_revision=current['revision'])))
        draft(client,'conversation',left,right)
        assert later['id'] not in json.dumps(provider.comparison_input)
        assert 'LATER_PATH_MUST_NOT_APPEAR' not in json.dumps(provider.comparison_input)


def test_cancel_releases_slot_wait_and_source_is_rechecked_before_dispatch(tmp_path):
    import asyncio
    from app.conversations import ConversationError
    provider = ComparisonProvider()
    with make_client(tmp_path,provider) as client:
        authorize(client); configure_provider(client)
        identity = client.app.state.auth.ensure_local_identity()
        left, _, _ = make_scope(client,provider,'conversation')
        first = send(client,'conversation',left,'first')
        right = fork(client,'conversation',left,first)
        service = client.app.state.branch_comparisons
        async def check():
            service.slots = asyncio.Semaphore(0)
            pending = asyncio.create_task(service.preview(identity,'conversation',left,right))
            await asyncio.sleep(0)
            assert service.locks[identity['id']].locked()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert not service.locks[identity['id']].locked()
            pending = asyncio.create_task(service.preview(identity,'conversation',left,right))
            await asyncio.sleep(0)
            service.chats.delete_conversation(identity['id'],left)
            service.slots.release()
            with pytest.raises(ConversationError):
                await pending
            assert not hasattr(provider,'comparison_input')
        asyncio.run(check())
