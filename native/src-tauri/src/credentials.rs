//! Device-local credentials. Only encrypted blobs live outside the business databases.
use sha2::{Digest, Sha256};
use std::{
    io::Write,
    path::{Path, PathBuf},
};

const READ_ERROR: &str = "无法读取本机 Key，请重新保存或删除后再设置";
const WRITE_ERROR: &str = "无法保存本机 Key，原有 Key 未被替换";

pub fn scope(base_url: &str) -> Result<String, String> {
    nautilus_core::provider::validate_settings(&nautilus_core::types::ProviderSettings {
        base_url: base_url.to_owned(),
        model: "credential".into(),
    })?;
    url::Url::parse(base_url.trim_end_matches('/'))
        .map(|url| url.to_string())
        .map_err(|_| "服务地址格式不正确".into())
}
fn path(dir: &Path, scope: &str) -> PathBuf {
    dir.join("credentials")
        .join(format!("{:x}.key", Sha256::digest(scope.as_bytes())))
}
pub fn exists(dir: &Path, scope: &str) -> Result<bool, String> {
    match std::fs::metadata(path(dir, scope)) {
        Ok(metadata) if metadata.is_file() => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        _ => Err(READ_ERROR.into()),
    }
}
pub async fn save(
    app: &tauri::AppHandle,
    dir: &Path,
    scope: &str,
    key: &str,
) -> Result<(), String> {
    if key.trim().is_empty() {
        return Err("请先输入 Key".into());
    }
    let encrypted = protect(app, key, scope).await?;
    let target = path(dir, scope);
    let parent = target.parent().ok_or(WRITE_ERROR)?;
    std::fs::create_dir_all(parent).map_err(|_| WRITE_ERROR)?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent).map_err(|_| WRITE_ERROR)?;
    temporary
        .write_all(encrypted.as_bytes())
        .map_err(|_| WRITE_ERROR)?;
    temporary.as_file().sync_all().map_err(|_| WRITE_ERROR)?;
    temporary.persist(target).map_err(|_| WRITE_ERROR)?;
    Ok(())
}
pub async fn load(
    app: &tauri::AppHandle,
    dir: &Path,
    scope: &str,
) -> Result<Option<String>, String> {
    let encrypted = match std::fs::read_to_string(path(dir, scope)) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(READ_ERROR.into()),
    };
    unprotect(app, &encrypted, scope).await.map(Some)
}
pub fn delete(dir: &Path, scope: &str) -> Result<(), String> {
    match std::fs::remove_file(path(dir, scope)) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("无法删除本机 Key，请重试".into()),
    }
}

#[cfg(target_os = "windows")]
fn dpapi(data: &[u8], scope: &str, encrypt: bool) -> Result<Vec<u8>, String> {
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::Cryptography::{
            CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
        },
    };
    let input = CRYPT_INTEGER_BLOB {
        cbData: data.len().try_into().map_err(|_| WRITE_ERROR)?,
        pbData: data.as_ptr() as *mut u8,
    };
    let entropy = CRYPT_INTEGER_BLOB {
        cbData: scope.len().try_into().map_err(|_| WRITE_ERROR)?,
        pbData: scope.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    // DPAPI allocates the returned buffer; it must be released with LocalFree.
    unsafe {
        let success = if encrypt {
            CryptProtectData(
                &input,
                std::ptr::null(),
                &entropy,
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } else {
            CryptUnprotectData(
                &input,
                std::ptr::null_mut(),
                &entropy,
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        };
        if success == 0 {
            return Err(if encrypt { WRITE_ERROR } else { READ_ERROR }.into());
        }
        let result = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        std::ptr::write_bytes(output.pbData, 0, output.cbData as usize);
        LocalFree(output.pbData.cast());
        Ok(result)
    }
}
#[cfg(target_os = "windows")]
async fn protect(_app: &tauri::AppHandle, key: &str, scope: &str) -> Result<String, String> {
    use base64::Engine;
    dpapi(key.as_bytes(), scope, true)
        .map(|bytes| base64::engine::general_purpose::STANDARD.encode(bytes))
}
#[cfg(target_os = "windows")]
async fn unprotect(
    _app: &tauri::AppHandle,
    encrypted: &str,
    scope: &str,
) -> Result<String, String> {
    use base64::Engine;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(encrypted)
        .map_err(|_| READ_ERROR)?;
    String::from_utf8(dpapi(&bytes, scope, false)?).map_err(|_| READ_ERROR.into())
}

#[cfg(target_os = "android")]
pub struct AndroidCredentials(tauri::plugin::PluginHandle<tauri::Wry>);
#[cfg(target_os = "android")]
pub fn plugin() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    use tauri::Manager;
    tauri::plugin::Builder::new("credentials")
        .setup(|app, api| {
            app.manage(AndroidCredentials(api.register_android_plugin(
                "com.nautilus.validation",
                "CredentialPlugin",
            )?));
            Ok(())
        })
        .build()
}
#[cfg(target_os = "android")]
async fn protect(app: &tauri::AppHandle, key: &str, scope: &str) -> Result<String, String> {
    use tauri::Manager;
    #[derive(serde::Deserialize)]
    struct Encrypted {
        ciphertext: String,
    }
    let result: Encrypted = app
        .state::<AndroidCredentials>()
        .0
        .run_mobile_plugin_async(
            "encrypt",
            serde_json::json!({"plaintext": key, "scope": scope}),
        )
        .await
        .map_err(|_| WRITE_ERROR)?;
    Ok(result.ciphertext)
}
#[cfg(target_os = "android")]
async fn unprotect(app: &tauri::AppHandle, encrypted: &str, scope: &str) -> Result<String, String> {
    use tauri::Manager;
    #[derive(serde::Deserialize)]
    struct Plain {
        plaintext: String,
    }
    let result: Plain = app
        .state::<AndroidCredentials>()
        .0
        .run_mobile_plugin_async(
            "decrypt",
            serde_json::json!({"ciphertext": encrypted, "scope": scope}),
        )
        .await
        .map_err(|_| READ_ERROR)?;
    Ok(result.plaintext)
}
#[cfg(not(any(target_os = "windows", target_os = "android")))]
async fn protect(_: &tauri::AppHandle, _: &str, _: &str) -> Result<String, String> {
    Err("此平台尚未接入系统 Key 保存".into())
}
#[cfg(not(any(target_os = "windows", target_os = "android")))]
async fn unprotect(_: &tauri::AppHandle, _: &str, _: &str) -> Result<String, String> {
    Err("此平台尚未接入系统 Key 保存".into())
}
