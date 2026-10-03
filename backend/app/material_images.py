"""Material image bytes are resolved only for the active outbound request."""
from __future__ import annotations

import base64
import json

from .learning_domain import DomainError
from .material_files import render_material_page


def image_materials(frozen):
    return [item for item in (frozen or {}).get('materials', []) if item.get('input_mode') == 'image']


def require_image_capability(chats, owner, profile_id, model_name, frozen=None):
    if frozen is not None and not image_materials(frozen):
        return
    chats._provider_by_id(owner, profile_id)
    row = chats.database.fetchone('SELECT capabilities_json FROM provider_model WHERE provider_profile_id=? AND model_id=? AND enabled=1',
                                  (profile_id, model_name))
    support = json.loads(row['capabilities_json'] or '{}').get('supports_image_input') if row else None
    if support is not True:
        raise DomainError('image_model_unsupported' if support is False else 'image_model_unverified', 422)


def check_image_sources(materials, identity, kind, scope_id, frozen):
    if not image_materials(frozen):
        return
    with materials.lock:
        owner = materials._owned_scope(identity['id'], kind, scope_id)
        for item in image_materials(frozen):
            row = materials.db.fetchone('''SELECT 1 FROM learning_task_material m
                JOIN learning_task_material source ON source.id=? AND source.owner_id=m.owner_id AND source.material_id=m.material_id
                JOIN learning_material_original o ON o.version_id=source.id
                WHERE m.id=? AND m.owner_id=? AND m.material_id=? AND m.purged_at IS NULL AND source.purged_at IS NULL
                AND o.purged_at IS NULL AND o.content IS NOT NULL''',
                (item.get('source_version_id', item['id']), item['id'], owner, item['material_id']))
            if row is None:
                raise DomainError('material_not_found', 404)


def attach_material_images(materials, identity, kind, scope_id, frozen, messages, check=None):
    sources = image_materials(frozen)
    if not sources:
        return messages
    images, labels = [], []
    for item in sources:
        if check:
            check()
        with materials.lock:
            check_image_sources(materials, identity, kind, scope_id, frozen)
            original = materials.original(identity, kind, scope_id, item['id'])
        marker = next(index for index, source in enumerate(frozen['materials'], 1) if source['id'] == item['id'])
        for page in item['page_numbers']:
            if check:
                check()
            raw, media_type = render_material_page(original['content'], original['media_type'], page)
            if check:
                check()
            images.append({'media_type': media_type, 'data': base64.b64encode(raw).decode('ascii')})
            labels.append(f'附图 {len(images)} 对应【资料{marker}】第 {page} 页。')
    check_image_sources(materials, identity, kind, scope_id, frozen)
    result = [dict(message) for message in messages]
    for message in reversed(result):
        if message.get('role') == 'user':
            message['content'] = message['content'] + '\n\n' + '\n'.join(labels)
            message['_images'] = images
            return result
    raise DomainError('image_input_message_missing', 422)
