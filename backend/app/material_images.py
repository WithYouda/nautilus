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
    result = [dict(message) for message in messages]
    attachment_ids = [message.pop('_attachment_version_ids', None) for message in result]
    sources = image_materials(frozen)
    if not sources:
        return result
    user_indexes = [index for index, message in enumerate(result) if message.get('role') == 'user']
    if not user_indexes:
        raise DomainError('image_input_message_missing', 422)
    current = user_indexes[-1]
    current_ids = attachment_ids[current]
    # An image belongs to the message that attached it, not every subsequent
    # question. Explicitly reattaching it moves its pixels to the current turn.
    placements = {}
    legacy_images, legacy_labels = [], []
    for item in sources:
        if current_ids is None or item['id'] in current_ids or len(user_indexes) == 1 and not current_ids:
            target = current
        else:
            target = next((index for index in reversed(user_indexes[:-1])
                           if item['id'] in (attachment_ids[index] or [])), None)
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
            images, labels = placements.setdefault(target, ([], [])) if target is not None else (legacy_images, legacy_labels)
            images.append({'media_type': media_type, 'data': base64.b64encode(raw).decode('ascii')})
            labels.append(f'附图 {len(images)} 对应【资料{marker}】第 {page} 页。')
    check_image_sources(materials, identity, kind, scope_id, frozen)
    for target, (images, labels) in placements.items():
        result[target]['content'] += '\n\n' + '\n'.join(labels)
        result[target]['_images'] = images
    if legacy_images:
        # Older records or a truncated history may lack the original message.
        # Keep their reference context separate; never call them new uploads.
        result.insert(user_indexes[0], {'role': 'user', 'content':
            '此前保存的历史图片参考（不是本轮新附件；仅在用户明确提及时使用）：\n' + '\n'.join(legacy_labels),
            '_images': legacy_images})
    return result
