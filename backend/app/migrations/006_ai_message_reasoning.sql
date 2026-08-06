-- Provider 明确返回的推理内容与最终正文分开保存，支持刷新恢复和默认折叠展示。
ALTER TABLE message
    ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT '';
