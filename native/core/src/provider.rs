use crate::types::{ChatMessage, ProviderSettings};
use futures_util::StreamExt;
use serde_json::{json, Value};
use tokio::sync::watch;

pub fn validate_settings(settings: &ProviderSettings) -> Result<(), String> {
    if settings.model.trim().is_empty() {
        return Err("请填写模型名称".into());
    }
    endpoint(settings).map(|_| ())
}

fn endpoint(settings: &ProviderSettings) -> Result<reqwest::Url, String> {
    let url = reqwest::Url::parse(&format!(
        "{}/chat/completions",
        settings.base_url.trim_end_matches('/')
    ))
    .map_err(|_| "服务地址格式不正确".to_string())?;
    if url.scheme() != "https"
        && !(url.scheme() == "http"
            && matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]")))
    {
        return Err("模型服务须使用 HTTPS 地址".into());
    }
    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("服务地址不能包含账号、查询参数或片段".into());
    }
    Ok(url)
}

pub async fn generate(
    settings: &ProviderSettings,
    key: &str,
    messages: &[ChatMessage],
    mut cancel: watch::Receiver<bool>,
    mut on_delta: impl FnMut(&str, &str) -> Result<(), String>,
) -> Result<(), String> {
    if *cancel.borrow() {
        return Err("已停止回答".into());
    }
    let url = endpoint(settings)?;
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "无法创建网络连接".to_string())?;
    let request = client
        .post(url)
        .bearer_auth(key)
        .json(&json!({"model":settings.model,"messages":messages,"stream":true}));
    let mut stream = tokio::select! {
        biased;
        _ = cancel.changed() => return Err("已停止回答".into()),
        response = request.send() => {
            let response = response.map_err(|_| "无法连接模型服务，请检查网络与服务地址".to_string())?;
            if !response.status().is_success() { return Err(format!("模型服务返回 {}，请核对设置", response.status().as_u16())); }
            response.bytes_stream()
        }
    };
    let mut buffer = Vec::new();
    let mut event = String::new();
    let mut finished = false;
    loop {
        let chunk = tokio::select! {
            biased;
            _ = cancel.changed() => return Err("已停止回答".into()),
            chunk = stream.next() => chunk,
        };
        let Some(chunk) = chunk else { break };
        buffer.extend_from_slice(&chunk.map_err(|_| "连接中断，已保留收到的内容".to_string())?);
        while let Some(end) = buffer.iter().position(|b| *b == b'\n') {
            let line: Vec<u8> = buffer.drain(..=end).collect();
            let line = std::str::from_utf8(&line)
                .map_err(|_| "模型服务返回无效文本".to_string())?
                .trim_end_matches(['\r', '\n']);
            if line.is_empty() {
                if !event.is_empty() {
                    if event.trim() == "[DONE]" {
                        return if finished {
                            Ok(())
                        } else {
                            Err("回答未正常结束，已保留收到的内容".into())
                        };
                    }
                    let data: Value = serde_json::from_str(&event)
                        .map_err(|_| "模型服务返回无效数据".to_string())?;
                    if data.get("error").is_some() {
                        return Err("模型服务未能完成回答".into());
                    }
                    if let Some(choice) = data["choices"].as_array().and_then(|c| c.first()) {
                        let delta = &choice["delta"];
                        if delta.get("tool_calls").is_some() || delta.get("function_call").is_some()
                        {
                            return Err("此独立验证版尚未开放搜索或工具调用".into());
                        }
                        let text = delta["content"]
                            .as_str()
                            .or_else(|| delta["refusal"].as_str())
                            .unwrap_or("");
                        let reasoning = delta["reasoning_content"]
                            .as_str()
                            .or_else(|| delta["reasoning"].as_str())
                            .unwrap_or("");
                        if !text.is_empty() || !reasoning.is_empty() {
                            on_delta(text, reasoning)?;
                        }
                        if let Some(reason) = choice["finish_reason"].as_str() {
                            if reason != "stop" {
                                return Err("回答提前结束，已保留收到的内容".into());
                            }
                            finished = true;
                        }
                    }
                    event.clear();
                }
            } else if let Some(data) = line.strip_prefix("data:") {
                if !event.is_empty() {
                    event.push('\n');
                }
                event.push_str(data.strip_prefix(' ').unwrap_or(data));
            }
        }
    }
    if finished && buffer.is_empty() && event.is_empty() {
        Ok(())
    } else {
        Err("连接中断，回答未完整结束，已保留收到的内容".into())
    }
}
