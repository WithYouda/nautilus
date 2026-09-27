use nautilus_core::{
    provider::generate,
    types::{ChatMessage, ProviderSettings},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::watch,
};
async fn server(body: &'static str) -> (ProviderSettings, tokio::task::JoinHandle<String>) {
    let socket = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = socket.local_addr().unwrap().port();
    let task = tokio::spawn(async move {
        let (mut stream, _) = socket.accept().await.unwrap();
        let mut received = Vec::new();
        loop {
            let mut buf = [0u8; 2048];
            let n = stream.read(&mut buf).await.unwrap();
            received.extend_from_slice(&buf[..n]);
            if let Some(end) = received.windows(4).position(|w| w == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&received[..end]);
                let length: usize = headers
                    .lines()
                    .find_map(|l| {
                        l.to_lowercase()
                            .strip_prefix("content-length: ")
                            .map(|x| x.parse().unwrap())
                    })
                    .unwrap();
                if received.len() >= end + 4 + length {
                    break;
                }
            }
        }
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len()).as_bytes()).await.unwrap();
        // Exercise splits inside both UTF-8 and SSE frame delimiters.
        for bytes in body.as_bytes().chunks(2) {
            stream.write_all(bytes).await.unwrap();
            tokio::task::yield_now().await;
        }
        String::from_utf8(received).unwrap()
    });
    (
        ProviderSettings {
            base_url: format!("http://127.0.0.1:{port}/v1"),
            model: "test".into(),
        },
        task,
    )
}
#[tokio::test]
async fn streams_unicode_reasoning_and_sends_no_tools() {
    let (settings,task)=server("data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"想法\"}}]}\r\n\r\ndata: {\"choices\":[{\"delta\":{\"content\":\"你好\"}}]}\n\ndata: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n").await;
    let (_tx, rx) = watch::channel(false);
    let (mut answer, mut reasoning) = (String::new(), String::new());
    generate(
        &settings,
        "synthetic-key",
        &[ChatMessage {
            role: "user".into(),
            content: "合成问题".into(),
        }],
        rx,
        |a, r| {
            answer.push_str(a);
            reasoning.push_str(r);
            Ok(())
        },
    )
    .await
    .unwrap();
    assert_eq!(answer, "你好");
    assert_eq!(reasoning, "想法");
    let request = task.await.unwrap();
    let body: serde_json::Value =
        serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert!(body.get("tools").is_none());
    assert_eq!(body["messages"][0]["content"], "合成问题");
}
#[tokio::test]
async fn unexpected_tools_are_not_executed() {
    let(settings,task)=server("data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"function\":{\"name\":\"search_web\",\"arguments\":\"private\"}}]}}]}\n\n").await;
    let (_tx, rx) = watch::channel(false);
    let result = generate(&settings, "test", &[], rx, |_, _| Ok(())).await;
    assert!(result.unwrap_err().contains("工具"));
    task.await.unwrap();
}
#[tokio::test]
async fn incomplete_answer_is_not_success() {
    let (settings, task) =
        server("data: {\"choices\":[{\"delta\":{\"content\":\"部分\"}}]}\n\n").await;
    let (_tx, rx) = watch::channel(false);
    let mut answer = String::new();
    assert!(generate(&settings, "test", &[], rx, |a, _| {
        answer.push_str(a);
        Ok(())
    })
    .await
    .is_err());
    assert_eq!(answer, "部分");
    task.await.unwrap();
}
#[tokio::test]
async fn cancel_stops_a_waiting_response() {
    let socket = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let settings = ProviderSettings {
        base_url: format!("http://{}/v1", socket.local_addr().unwrap()),
        model: "test".into(),
    };
    let (tx, rx) = watch::channel(false);
    let pending =
        tokio::spawn(async move { generate(&settings, "test", &[], rx, |_, _| Ok(())).await });
    let (_connection, _) = socket.accept().await.unwrap();
    tx.send(true).unwrap();
    assert_eq!(pending.await.unwrap().unwrap_err(), "已停止回答");
}

#[tokio::test]
async fn persisted_turn_survives_reopen_after_stream_and_replay() {
    use nautilus_core::store::Store;
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("local.sqlite3");
    let (settings, task) = server("data: {\"choices\":[{\"delta\":{\"content\":\"本机回答\"}}]}\n\ndata: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n").await;
    let mut store = Store::open(&path).unwrap();
    store.save_settings(settings).unwrap();
    let material = store
        .save_material(None, "合成资料".into(), "合成内容".into())
        .unwrap();
    let prepared = store
        .begin_turn("one".into(), "解释资料".into(), vec![material.id.clone()])
        .unwrap();
    let (_tx, rx) = watch::channel(false);
    let mut answer = String::new();
    generate(
        &prepared.turn.provider,
        "synthetic-secret",
        &prepared.messages,
        rx,
        |text, _| {
            answer.push_str(text);
            store.update_turn(&prepared.turn.id, &answer, "")
        },
    )
    .await
    .unwrap();
    store
        .finish_turn(&prepared.turn.id, "complete", None)
        .unwrap();
    let request = task.await.unwrap();
    assert!(request.contains("合成内容"));
    drop(store);
    let mut reopened = Store::open(&path).unwrap();
    reopened.recover().unwrap();
    assert_eq!(reopened.snapshot().unwrap().turns[0].answer, "本机回答");
    let replay = reopened
        .begin_turn("one".into(), "解释资料".into(), vec![material.id])
        .unwrap();
    assert!(!replay.created);
    assert!(replay.messages.is_empty());
    assert!(!String::from_utf8_lossy(&std::fs::read(path).unwrap()).contains("synthetic-secret"));
}
